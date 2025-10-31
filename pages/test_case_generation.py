import json
import urllib.request
import urllib.error

import streamlit as st
import concurrent.futures
import time
import socket
import os
import tempfile
from pathlib import Path


WEBHOOK_URL = "https://natasha1.app.n8n.cloud/webhook/f6d8b7ed-cf2f-48d1-adb4-fe7a78694981"

def safe_rerun():
    """
    Call Streamlit's rerun function if available; different streamlit versions
    expose this API under different names (experimental_rerun or rerun).
    This wrapper avoids static typing errors and safely ignores failures.
    """
    rerun = getattr(st, "experimental_rerun", None) or getattr(st, "rerun", None)
    if callable(rerun):
        try:
            rerun()
        except Exception:
            pass


def render():
    """Render the Test Case Generation page with a form that submits to an n8n webhook."""
    st.header("Test Case Generation")
    st.write("Use this page to generate automated test cases for your game.")
    # Layout: form on the left, response table/download on the right
    left_col, right_col = st.columns([2, 3])

    resp_text = None
    resp_data = None

    # Display stored test cases (read from Reports/test_cases.json) in the right column.
    with right_col:
        st.subheader("Saved Test Cases")
        try:
            repo_root = Path(__file__).resolve().parents[1]
            stored = repo_root / "Reports" / "test_cases.json"
            if stored.exists():
                try:
                    with stored.open("r", encoding="utf-8") as f:
                        stored_data = json.load(f)
                except Exception as e:
                    st.warning(f"Failed to read saved test cases: {e}")
                    stored_data = None

                if stored_data is None:
                    st.info("No saved test cases or file unreadable.")
                else:
                    # Prefer to show as a table if it's a list of records
                    if isinstance(stored_data, list):
                        try:
                            st.dataframe(stored_data)
                        except Exception:
                            st.json(stored_data)
                    elif isinstance(stored_data, dict):
                        try:
                            st.dataframe([stored_data])
                        except Exception:
                            st.json(stored_data)
                    else:
                        st.json(stored_data)

                    # Download button for convenience
                    try:
                        import io, csv

                        output = io.StringIO()
                        # If list of dicts, compute headers and write CSV
                        if isinstance(stored_data, list) and len(stored_data) > 0 and isinstance(stored_data[0], dict):
                            headers = list({k for row in stored_data for k in (row.keys() if isinstance(row, dict) else [])})
                            writer = csv.DictWriter(output, fieldnames=headers)
                            writer.writeheader()
                            for row in stored_data:
                                writer.writerow({k: (row.get(k, "") if isinstance(row, dict) else "") for k in headers})
                        elif isinstance(stored_data, dict):
                            headers = list(stored_data.keys())
                            writer = csv.DictWriter(output, fieldnames=headers)
                            writer.writeheader()
                            writer.writerow({k: stored_data.get(k, "") for k in headers})
                        else:
                            output.write(json.dumps(stored_data, ensure_ascii=False))

                        csv_bytes = output.getvalue().encode("utf-8")
                        st.download_button("Download saved test cases (CSV/JSON)", data=csv_bytes, file_name="test_cases.csv", mime="text/csv")
                    except Exception:
                        pass

                    # Manual refresh button
                    if st.button("Refresh test cases"):
                        safe_rerun()
            else:
                st.info("No saved test cases yet.")
        except Exception as e:
            st.warning(f"Error while loading saved test cases: {e}")

    with left_col:
        with st.form("tc_form"):
            os_field = st.text_input("OS")
            # sheet = st.text_input("Sheet")
            ticket_id = st.text_input("Ticket ID")
            module = st.text_input("Module")
            summary = st.text_input("Summary")
            ac = st.text_area("Acceptance Criteria")
            # desc = st.text_area("Description")
            # Type: show choices as radio buttons so both options are visible immediately
            type_choices = {"Test Case": "tc", "Test Scenario": "ts"}
            selection_label = st.radio("Type", list(type_choices.keys()))
            dropdown = type_choices[selection_label]

            submitted = st.form_submit_button("Submit to n8n")

    if submitted:
        payload = {
            "os": os_field,
            "sheet": sheet,
            "ticketId": ticket_id,
            "module": module,
            "summary": summary,
            "ac": ac,
            "desc": desc,
            "dropdown": dropdown,
        }

        # Send JSON payload to the webhook
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        # Run the network request in a background thread and poll with a progress bar
        def do_request(r):
            with urllib.request.urlopen(r, timeout=60) as resp:
                return resp.read().decode("utf-8").strip()

        future = None
        try:
            # place a small progress bar in a narrow sub-column to keep it compact
            pcol, _ = left_col.columns([1, 6])
            pbar = pcol.progress(0)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(do_request, req)

                start = time.time()
                timeout_seconds = 60
                interval = 0.5
                while True:
                    if future.done():
                        break
                    elapsed = time.time() - start
                    frac = min(1.0, elapsed / timeout_seconds)
                    pbar.progress(int(frac * 100))
                    if elapsed >= timeout_seconds:
                        break
                    time.sleep(interval)

                # Attempt to get result (may raise exceptions from the worker)
                try:
                    resp_text = future.result(timeout=0)
                except concurrent.futures.TimeoutError:
                    # timed out waiting for result after polling
                    st.error("Timed out waiting for webhook response (60s).")
                    return

            # mark progress complete when we have the response
            try:
                pbar.progress(100)
            except Exception:
                pass
        except urllib.error.HTTPError as e:
            st.error(f"Request failed: {e.code} {e.reason}")
            return
        except (urllib.error.URLError, socket.timeout) as e:
            st.error(f"Network error or timeout when contacting the webhook: {e}")
            return

        if resp_text:
            # Try to parse JSON
            try:
                resp_data = json.loads(resp_text)
            except Exception:
                resp_data = None

            # Show a success message (toast-like)
            st.success("Submission successful.")
            st.balloons()

            # Persist JSON responses so other pages can use them.
            # We only persist when we successfully parsed JSON into resp_data.
            if resp_data is not None:
                try:
                    # repo root is two levels up from this file: /<repo>/pages/test_case_generation.py
                    repo_root = Path(__file__).resolve().parents[1]
                    reports_dir = repo_root / "Reports"
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    target = reports_dir / "test_cases.json"

                    # Load existing data (if any) and normalize to a list
                    existing = []
                    if target.exists():
                        try:
                            with target.open("r", encoding="utf-8") as f:
                                existing = json.load(f)
                                if not isinstance(existing, list):
                                    existing = [existing]
                        except Exception:
                            # If file is corrupted or unreadable, start fresh
                            existing = []

                    # Normalize new entries to a list
                    if isinstance(resp_data, dict):
                        new_entries = [resp_data]
                    elif isinstance(resp_data, list):
                        new_entries = resp_data
                    else:
                        new_entries = []

                    # Determine Test Case ID prefix and max existing number
                    prefix = None
                    max_num = 0
                    try:
                        import re

                        prefix_counts = {}
                        for item in existing:
                            if not isinstance(item, dict):
                                continue
                            tcid = item.get("Test Case ID") or item.get("TestCaseID")
                            if not isinstance(tcid, str):
                                continue
                            s = tcid.strip()
                            # match a trailing number, capture prefix and number
                            m = re.match(r"^(.*?)(?:[_\-\s])?(\d+)\s*$", s)
                            if m:
                                # remove trailing separators (underscore, space, hyphen) and strip whitespace
                                ppart = (m.group(1) or "").rstrip(" _-").strip()
                                try:
                                    n = int(m.group(2))
                                except Exception:
                                    continue
                                if ppart == "":
                                    # fallback prefix when none found
                                    ppart = "SG"
                                prefix_counts[ppart] = prefix_counts.get(ppart, 0) + 1
                                if n > max_num:
                                    max_num = n

                        # pick the most common prefix if any, else default to 'SG' or 'TC'
                        if prefix_counts:
                            prefix = max(prefix_counts.items(), key=lambda kv: kv[1])[0]
                        else:
                            # fallback: look for explicit SG_ occurrences
                            if any(isinstance(item, dict) and isinstance(item.get("Test Case ID"), str) and item.get("Test Case ID").strip().startswith("SG") for item in existing):
                                prefix = "SG"
                            else:
                                prefix = "TC"
                    except Exception:
                        prefix = "TC"

                    # Assign Test Case ID to new entries that don't have one
                    try:
                        next_num = max_num + 1
                        for entry in new_entries:
                            if not isinstance(entry, dict):
                                continue
                            tcid = entry.get("Test Case ID") or entry.get("TestCaseID")
                            if not tcid:
                                entry["Test Case ID"] = f"{prefix}_{next_num}"
                                next_num += 1
                    except Exception:
                        pass

                    # Append-only behavior: simply concatenate existing records with new entries.
                    # The user requested to append all new test cases without deduplication.
                    combined = existing + new_entries

                    # Atomic write: write to a temp file then replace
                    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(reports_dir), encoding="utf-8") as tf:
                        json.dump(combined, tf, ensure_ascii=False, indent=2)
                        tempname = tf.name
                    os.replace(tempname, str(target))
                    st.info(f"Saved webhook response to: {target}")
                    # Refresh the page so the Saved Test Cases table reloads with the new data
                    try:
                        safe_rerun()
                    except Exception:
                        # If rerun isn't allowed in this context, it's non-fatal — the user can press Refresh.
                        pass
                except Exception as e:
                    st.warning(f"Could not save webhook response to disk: {e}")

            # Display response side-by-side in the right column
            with right_col:
                st.subheader("Webhook response")
                if resp_data is None:
                    st.warning("Response is not valid JSON; showing raw text.")
                    st.code(resp_text)
                else:
                    # If data is a list of dicts or dict -> display as table
                    if isinstance(resp_data, list):
                        # list of records
                        try:
                            st.dataframe(resp_data)
                        except Exception:
                            st.json(resp_data)

                        # Offer CSV download (Excel-readable)
                        try:
                            import io, csv

                            output = io.StringIO()
                            # determine headers
                            if len(resp_data) > 0 and isinstance(resp_data[0], dict):
                                headers = list({k for row in resp_data for k in row.keys()})
                                writer = csv.DictWriter(output, fieldnames=headers)
                                writer.writeheader()
                                for row in resp_data:
                                    writer.writerow({k: row.get(k, "") for k in headers})
                                csv_bytes = output.getvalue().encode("utf-8")
                                st.download_button(
                                    "Download CSV (Excel)",
                                    data=csv_bytes,
                                    file_name="response.csv",
                                    mime="text/csv",
                                )
                        except Exception:
                            pass

                    elif isinstance(resp_data, dict):
                        # Show single-record dict as table (one row)
                        try:
                            st.dataframe([resp_data])
                        except Exception:
                            st.json(resp_data)

                        # Offer CSV download
                        try:
                            import io, csv

                            output = io.StringIO()
                            headers = list(resp_data.keys())
                            writer = csv.DictWriter(output, fieldnames=headers)
                            writer.writeheader()
                            writer.writerow({k: resp_data.get(k, "") for k in headers})
                            csv_bytes = output.getvalue().encode("utf-8")
                            st.download_button(
                                "Download CSV (Excel)",
                                data=csv_bytes,
                                file_name="response.csv",
                                mime="text/csv",
                            )
                        except Exception:
                            pass
                    else:
                        st.json(resp_data)

        else:
            st.error("Webhook returned an empty response.")

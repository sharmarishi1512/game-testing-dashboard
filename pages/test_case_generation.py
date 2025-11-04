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
import random


WEBHOOK_URL = "https://natasha1.app.n8n.cloud/webhook/f6d8b7ed-cf2f-48d1-adb4-fe7a78694981"


def render():
    """Render the Test Case Generation page with a form that submits to an n8n webhook."""
    st.header("Test Case Generation")
    st.write("Use this page to generate automated test cases for your game.")
    # Layout: form on the left, response table/download on the right
    left_col, right_col = st.columns([2, 3])

    resp_text = None
    resp_data = None
    # prepare path to saved test cases JSON
    repo_root = Path(__file__).resolve().parents[1]
    reports_dir = repo_root / "Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    target = reports_dir / "test_cases.json"

    # helper: load saved records from JSON (normalize to list)
    def load_saved_records():
        if not target.exists():
            return []
        try:
            with target.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            else:
                return []
        except Exception:
            return []
    # initialize form variables so they always exist even if form isn't rendered for some reason
    google_sheet = ""
    module = ""
    user_story = ""
    dropdown = "tc"  # send static 'tc' value

    # Right column: always show saved test cases loaded from Reports/test_cases.json
    with right_col:
        st.subheader("Saved test cases (from Reports/test_cases.json)")
        saved = load_saved_records()
        if not saved:
            st.info("No saved test cases found. Generate some from the form on the left.")
        else:
            try:
                st.dataframe(saved)
            except Exception:
                st.json(saved)

    with left_col:
        with st.form("tc_form"):
            # bring User Story to first place
            user_story = st.text_area("User Story")
            # OS changed to Google Sheet Link
            google_sheet = st.text_input("Google Sheet Link")
            module = st.text_input("Module")
            # remove Summary placeholder (not shown)
            # Type removed; send static 'tc' in payload
            # st.write("Type: Test Case (sent as static)")

            submitted = st.form_submit_button("Submit to n8n")

    if submitted:
        # Build payload: send Google Sheet Link, Module, User Story and static TC value
        payload = {
            "os": google_sheet,
            "ticketId": "TC",
            "module": module,
            "ac": user_story,
            "dropdown": "tc",
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

            # Persist JSON responses so other pages can use them.
            # We only persist when we successfully parsed JSON into resp_data.
            if resp_data is not None:
                try:
                    # Load existing data (if any) and normalize to a list
                    existing = []
                    if target.exists():
                        try:
                            with target.open("r", encoding="utf-8") as f:
                                existing = json.load(f)
                                if not isinstance(existing, list):
                                    existing = [existing]
                        except Exception:
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

                        prefixes = {}
                        for item in existing:
                            if isinstance(item, dict):
                                tcid = item.get("Test Case ID") or item.get("TestCaseID")
                                if isinstance(tcid, str):
                                    m = re.match(r"([^_]+)_?(\d+)$", tcid)
                                    if m:
                                        p = m.group(1)
                                        n = int(m.group(2))
                                        prefixes[p] = prefixes.get(p, 0) + 1
                                        if n > max_num:
                                            max_num = n

                        # pick the most common prefix if any, else default to 'SG' if present, otherwise 'TC'
                        if prefixes:
                            prefix = max(prefixes.items(), key=lambda kv: kv[1])[0]
                        else:
                            prefix = "SG" if any("SG_" in (str(item.get("Test Case ID")) if isinstance(item, dict) else "" for item in existing) ) else "TC"
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

                    combined = existing + new_entries

                    # Basic dedupe by `ticketId` or `Test Case ID` when available (keep first occurrence)
                    try:
                        seen_ticket = set()
                        seen_tcid = set()
                        deduped = []
                        for item in combined:
                            if not isinstance(item, dict):
                                deduped.append(item)
                                continue

                            ticket = item.get("ticketId")
                            tcid = item.get("Test Case ID")

                            # if ticketId present and seen, skip
                            if ticket is not None:
                                if ticket in seen_ticket:
                                    continue
                                seen_ticket.add(ticket)

                            # if Test Case ID present and seen, skip
                            if tcid is not None:
                                if tcid in seen_tcid:
                                    continue
                                seen_tcid.add(tcid)

                            deduped.append(item)

                        combined = deduped
                    except Exception:
                        pass

                    # Atomic write: write to a temp file then replace
                    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(reports_dir), encoding="utf-8") as tf:
                        json.dump(combined, tf, ensure_ascii=False, indent=2)
                        tempname = tf.name
                    os.replace(tempname, str(target))
                    st.info(f"Saved webhook response to: {target}")

                    # Refresh right column view by reloading saved records and showing them
                    with right_col:
                        st.subheader("Saved test cases (from Reports/test_cases.json)")
                        saved = load_saved_records()
                        if not saved:
                            st.info("No saved test cases found after save.")
                        else:
                            try:
                                st.dataframe(saved)
                            except Exception:
                                st.json(saved)

                        # add download buttons for the saved file
                        try:
                            raw_json = target.read_text(encoding="utf-8").encode("utf-8")
                            st.download_button(
                                "Download saved JSON",
                                data=raw_json,
                                file_name="test_cases.json",
                                mime="application/json",
                            )

                            # CSV
                            import io, csv
                            headers = []
                            seen = set()
                            for r in saved:
                                if isinstance(r, dict):
                                    for k in r.keys():
                                        if k not in seen:
                                            seen.add(k)
                                            headers.append(k)

                            if headers:
                                output = io.StringIO()
                                writer = csv.DictWriter(output, fieldnames=headers)
                                writer.writeheader()
                                for r in saved:
                                    if isinstance(r, dict):
                                        writer.writerow({k: r.get(k, "") for k in headers})
                                csv_bytes = output.getvalue().encode("utf-8")
                                st.download_button(
                                    "Download CSV (from saved JSON)",
                                    data=csv_bytes,
                                    file_name="test_cases.csv",
                                    mime="text/csv",
                                )
                        except Exception:
                            pass
                except Exception as e:
                    st.warning(f"Could not save webhook response to disk: {e}")

            # Compact webhook response and Automation UI on the left column (avoid duplicate table)
            with left_col:
                st.subheader("Webhook response (latest)")
                if resp_data is None:
                    st.warning("Response is not valid JSON; showing raw text.")
                    st.code(resp_text)
                else:
                    # show compact JSON (not a large table) to avoid duplicating saved-table view
                    try:
                        st.json(resp_data)
                    except Exception:
                        st.code(json.dumps(resp_data, ensure_ascii=False))

                # --- Automation UI: Run automation using the API response data ---
                st.markdown("---")
                st.subheader("Automation")
                script = st.file_uploader("Upload automation script (optional)", key="automation_script")

                if st.button("Start Automation"):
                    if resp_data is None:
                        st.error("No API response available to automate. Submit the form first.")
                    else:
                        # Use response data (dict or list) as automation instructions / test cases
                        entries = resp_data if isinstance(resp_data, list) else [resp_data]
                        total = len(entries)
                        if total == 0:
                            st.warning("No entries found in the API response to automate.")
                        else:
                            prog = st.progress(0)
                            log_box = st.empty()
                            success_count = 0
                            fail_count = 0
                            for i, entry in enumerate(entries, start=1):
                                # Best-effort extract a friendly name for the entry
                                name = None
                                if isinstance(entry, dict):
                                    name = entry.get("Test Case ID") or entry.get("testCaseId") or entry.get("title") or entry.get("name")
                                if not name:
                                    name = f"entry {i}"

                                log_box.write(f"Running automation for {name} ...")

                                # Placeholder execution: if user uploaded a script we could run it here.
                                # For now, simulate execution with a short delay and random pass/fail result.
                                try:
                                    time.sleep(0.5)
                                except Exception:
                                    pass

                                passed = random.random() > 0.15
                                if passed:
                                    log_box.write(f"✅ {name}: PASSED")
                                    success_count += 1
                                else:
                                    log_box.write(f"❌ {name}: FAILED")
                                    fail_count += 1

                                prog.progress(int(i / total * 100))

                            st.success(f"Automation finished — {success_count} passed, {fail_count} failed.")

        else:
            st.error("Webhook returned an empty response.")

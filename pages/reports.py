import json
from pathlib import Path
import io
import csv
from datetime import datetime

import streamlit as st


def render():
    """Render the Reports page: read stored test cases and show charts/filters/download."""
    st.header("Reports")
    st.write("Visualize test cases stored in `Reports/test_cases.json`.")

    repo_root = Path(__file__).resolve().parents[1]
    testcases_file = repo_root / "Reports" / "test_cases.json"

    # Allow CSV upload to override reading the JSON file
    uploaded = st.file_uploader("Upload CSV to generate report (optional)", type=["csv"])

    csv_header = None
    date_indices = []  # list of (index, date_iso)
    timeseries_counts = {}  # date_iso -> Counter of outcomes

    if uploaded is not None:
        try:
            raw = uploaded.getvalue().decode("utf-8", errors="replace")
            rdr = csv.reader(io.StringIO(raw))
            rows = list(rdr)
            if not rows:
                st.error("Uploaded CSV is empty")
                return
            csv_header = rows[0]
            data_rows = rows[1:]

            # helper to parse date-like header values
            def _parse_date(h: str):
                h = (h or "").strip()
                if not h:
                    return None
                for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        return datetime.strptime(h, fmt).date()
                    except Exception:
                        continue
                # try numeric month/day without leading zeros like '6/1/2025'
                try:
                    parts = h.split("/")
                    if len(parts) == 3:
                        m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
                        return datetime(year=y, month=m, day=d).date()
                except Exception:
                    pass
                return None

            # detect date-like header columns (preserve duplicates)
            for idx, h in enumerate(csv_header):
                d = _parse_date(h)
                if d is not None:
                    date_iso = d.isoformat()
                    date_indices.append((idx, date_iso))

            # Build normalized records (map key names to values); also compute latest status per row
            records = []
            for row in data_rows:
                # ensure row has same length as header
                if len(row) < len(csv_header):
                    # pad
                    row = row + [""] * (len(csv_header) - len(row))
                rec = {}
                for i, h in enumerate(csv_header):
                    rec[h] = row[i]

                # normalize primary fields expected by charts
                tcid = (rec.get("Test Case ID") or rec.get("TestCaseID") or rec.get("ID") or "").strip()
                module = (rec.get("Module") or rec.get("module") or "").strip() or "<Unknown>"
                tctype = (rec.get("Test Case Type") or rec.get("Test Case Type ") or rec.get("TestCaseType") or "").strip()

                # determine latest status from date columns (right-to-left)
                latest_status = ""
                for idx, _iso in reversed(date_indices):
                    v = (row[idx] or "").strip()
                    if v:
                        latest_status = v
                        break

                # fallback to common status columns
                if not latest_status:
                    for key in ("Status", "Result", "Actual Result", "Outcome"):
                        if key in rec and rec[key].strip():
                            latest_status = rec[key].strip()
                            break

                records.append({
                    "Test Case ID": tcid,
                    "Module": module,
                    "Test Case Type": tctype,
                    "Status": latest_status,
                    "_raw_row": rec,
                })

            # Build timeseries counts grouped by date_iso (sum across duplicate date columns)
            from collections import Counter

            timeseries_counts = {}
            if date_indices:
                for idx, date_iso in date_indices:
                    # for each date column, count pass/fail in that column
                    c = Counter()
                    for row in data_rows:
                        # pad
                        if len(row) <= idx:
                            continue
                        val = (row[idx] or "").strip().lower()
                        if not val:
                            continue
                        if val.startswith("pass"):
                            c["Pass"] += 1
                        elif val.startswith("fail"):
                            c["Fail"] += 1
                        else:
                            c["Other"] += 1
                    # aggregate into date key
                    if date_iso not in timeseries_counts:
                        timeseries_counts[date_iso] = Counter()
                    timeseries_counts[date_iso].update(c)

        except Exception as e:
            st.error(f"Failed to parse uploaded CSV: {e}")
            return
    else:
        # no upload: read saved JSON test cases
        if not testcases_file.exists():
            st.info("No saved test cases found. Generate some from the Test Case Generation page first.")
            return
        try:
            with testcases_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            st.error(f"Failed to read test cases file: {e}")
            return

        # normalize to records for existing JSON
        if isinstance(data, dict):
            records = [data]
        elif isinstance(data, list):
            records = data
        else:
            st.error("Unexpected data format in test_cases.json")
            return

    # At this point `records` should be defined (from CSV upload branch or JSON branch)
    try:
        import pandas as pd
    except Exception:
        pd = None

    # Basic fields extraction (safe)
    def get_field(rec, key):
        return rec.get(key) if isinstance(rec, dict) else None

    modules = [get_field(r, "Module") or "<Unknown>" for r in records]
    statuses = [get_field(r, "Status") or "<Unknown>" for r in records]
    types = [get_field(r, "Test Case Type") or "<Unknown>" for r in records]

    total = len(records)

    st.subheader("Summary")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total test cases", total)
    # top module
    try:
        from collections import Counter

        top_module, top_module_count = Counter(modules).most_common(1)[0]
    except Exception:
        top_module, top_module_count = "-", 0
    col2.metric("Top module", f"{top_module} ({top_module_count})")
    try:
        top_status, top_status_count = Counter(statuses).most_common(1)[0]
    except Exception:
        top_status, top_status_count = "-", 0
    col3.metric("Top status", f"{top_status} ({top_status_count})")

    st.markdown("---")

    # Filters
    st.sidebar.header("Filters")
    unique_modules = sorted({m for m in modules if m is not None})
    selected_modules = st.sidebar.multiselect("Module", unique_modules, default=unique_modules)
    unique_status = sorted({s for s in statuses if s is not None})
    selected_status = st.sidebar.multiselect("Status", unique_status, default=unique_status)
    unique_types = sorted({t for t in types if t is not None})
    selected_types = st.sidebar.multiselect("Test Case Type", unique_types, default=unique_types)

    # Apply filters
    def record_matches(r):
        m = get_field(r, "Module") or "<Unknown>"
        s = get_field(r, "Status") or "<Unknown>"
        t = get_field(r, "Test Case Type") or "<Unknown>"
        return (m in selected_modules) and (s in selected_status) and (t in selected_types)

    filtered = [r for r in records if record_matches(r)]

    st.subheader("Charts")
    # Time-series: Pass/Fail over date columns (only when CSV upload with date columns is used)
    if timeseries_counts:
        # build a flat list for Vega-Lite: [{date: '2025-06-01', outcome: 'Pass', count: 12}, ...]
        ts_rows = []
        for date_iso in sorted(timeseries_counts.keys()):
            ctr = timeseries_counts[date_iso]
            for outcome, cnt in ctr.items():
                ts_rows.append({"date": date_iso, "outcome": outcome, "count": int(cnt)})

        if ts_rows:
            st.markdown("**Pass / Fail over time**")
            spec_ts = {
                "mark": {"type": "line", "point": True},
                "encoding": {
                    "x": {"field": "date", "type": "temporal", "title": "Date"},
                    "y": {"field": "count", "type": "quantitative", "title": "Count"},
                    "color": {"field": "outcome", "type": "nominal"},
                    "tooltip": [
                        {"field": "date", "type": "temporal"},
                        {"field": "outcome", "type": "nominal"},
                        {"field": "count", "type": "quantitative"},
                    ],
                },
            }
            try:
                st.vega_lite_chart(ts_rows, spec_ts, use_container_width=True)
            except Exception:
                # degrade gracefully
                st.write({d: dict(timeseries_counts[d]) for d in sorted(timeseries_counts.keys())})
        # Show two pies side-by-side: Test Case Type distribution and latest-date Pass/Fail
        try:
            from collections import Counter

            # type counts from filtered records
            type_ctr = Counter([get_field(r, "Test Case Type") or "<Unknown>" for r in filtered])
            type_data = [{"type": k, "count": int(v)} for k, v in type_ctr.items()]

            latest_date = None
            latest_counts = None
            if timeseries_counts:
                latest_date = max(timeseries_counts.keys())
                latest_counts = timeseries_counts.get(latest_date, {})
            latest_data = []
            if latest_counts:
                for k in ("Pass", "Fail", "Other"):
                    if latest_counts.get(k):
                        latest_data.append({"outcome": k, "count": int(latest_counts.get(k))})

            col_left, col_right = st.columns(2)
            with col_left:
                st.markdown("**Test Case Type**")
                if type_data:
                    spec_type = {
                        "mark": {"type": "arc", "innerRadius": 20},
                        "encoding": {
                            "theta": {"field": "count", "type": "quantitative"},
                            "color": {"field": "type", "type": "nominal"},
                            "tooltip": [{"field": "type"}, {"field": "count", "type": "quantitative"}],
                        },
                    }
                    st.vega_lite_chart(type_data, spec_type, use_container_width=True)
                else:
                    st.write("No Test Case Type data")

            with col_right:
                if latest_date and latest_data:
                    st.markdown(f"**Pass/Fail (latest date: {latest_date})**")
                    spec_latest = {
                        "mark": {"type": "arc", "innerRadius": 20},
                        "encoding": {
                            "theta": {"field": "count", "type": "quantitative"},
                            "color": {"field": "outcome", "type": "nominal"},
                            "tooltip": [{"field": "outcome"}, {"field": "count", "type": "quantitative"}],
                        },
                    }
                    st.vega_lite_chart(latest_data, spec_latest, use_container_width=True)
                else:
                    st.write("No date-based Pass/Fail data detected")
        except Exception:
            # if anything fails, continue without blocking charts below
            pass
    if pd is not None:
        df = pd.DataFrame(filtered)
        if df.empty:
            st.info("No test cases match the selected filters.")
        else:
            # Counts by Module
            module_counts = df["Module"].fillna("<Unknown>").value_counts()
            st.markdown("**Test cases by Module**")
            st.bar_chart(module_counts)

            # Counts by Status
            status_counts = df["Status"].fillna("<Unknown>").value_counts()
            st.markdown("**Test cases by Status**")
            st.bar_chart(status_counts)

            # Counts by Test Case Type
            type_counts = df["Test Case Type"].fillna("<Unknown>").value_counts()
            st.markdown("**Test cases by Type**")

            # Test Case Type pie is shown above (if available)

            st.markdown("---")
            st.subheader("Filtered test cases")
            st.dataframe(df)
    else:
        # Fallback: simple aggregations without pandas
        if len(filtered) == 0:
            st.info("No test cases match the selected filters.")
        else:
            from collections import Counter

            st.markdown("**Test cases by Module**")
            mc = Counter([get_field(r, "Module") or "<Unknown>" for r in filtered])
            st.write(dict(mc))
            st.markdown("**Test cases by Status**")
            sc = Counter([get_field(r, "Status") or "<Unknown>" for r in filtered])
            st.write(dict(sc))
            # Test Case Type pie is shown above (if available)

            st.markdown("---")
            st.subheader("Filtered test cases")
            st.write(filtered)

    # Download filtered results as CSV
    st.markdown("---")
    st.subheader("Export")
    try:
        if pd is not None and not pd.DataFrame(filtered).empty:
            csv_bytes = pd.DataFrame(filtered).to_csv(index=False).encode("utf-8")
        else:
            # Fallback CSV generation
            if len(filtered) == 0:
                csv_bytes = "".encode("utf-8")
            else:
                # collect headers
                headers = set()
                for r in filtered:
                    if isinstance(r, dict):
                        headers.update(r.keys())
                headers = list(headers)
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=headers)
                writer.writeheader()
                for r in filtered:
                    writer.writerow({k: (r.get(k, "") if isinstance(r, dict) else "") for k in headers})
                csv_bytes = output.getvalue().encode("utf-8")

        st.download_button("Download filtered CSV", data=csv_bytes, file_name="test_cases_filtered.csv", mime="text/csv")
    except Exception as e:
        st.warning(f"Could not prepare CSV export: {e}")

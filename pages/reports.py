import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from collections import Counter
import streamlit as st


def _normalize_status(s: str) -> str:
    if not s:
        return "Not Tested"
    s_low = s.strip().lower()
    if s_low.startswith("pass") or s_low == "passed":
        return "Pass"
    if "fail" in s_low:
        return "Fail"
    if s_low in ("not tested", "not-tested", "nottested"):
        return "Not Tested"
    return s.strip()


def render():
    """Render the Reports page with exactly the requested charts.

    Behavior:
    - Counts are based on unique `Test Case ID` values (duplicates ignored).
    - 1) Pie chart: Positive vs Negative test cases (by Test Case Type).
    - 2) Pie chart: Pass vs Fail (by normalized Status).
    - 3) Bar chart: number of unique test cases per Module.
    """
    st.header("Reports")

    repo_root = Path(__file__).resolve().parents[1]
    tc_file = repo_root / "Reports" / "test_cases.json"

    # Allow the user to upload a CSV. If provided, use it as the source of records
    uploaded = st.file_uploader("Upload CSV to generate report (optional)", type=["csv"], help="Upload a CSV in the same format as 'Final Report - Test Cases format.csv'. If not provided, the page will read Reports/test_cases.json.")
    records = None

    if uploaded is not None:
        try:
            # uploaded is a BytesIO-like object from Streamlit
            raw_text = io.TextIOWrapper(uploaded, encoding="utf-8", errors="replace")
            reader = csv.DictReader(raw_text)
            csv_rows = list(reader)

            def _guess_status_from_row(row: dict) -> str:
                # If there's an explicit Status/Result column, prefer that
                for candidate in ("Status", "Result", "Test Result", "Outcome"):
                    if candidate in row and row[candidate].strip():
                        return row[candidate].strip()
                # Otherwise, try to pick the right-most date-like / extra columns with Pass/Fail values
                # Fall back to the last non-empty cell in the row
                last = ""
                for k in reader.fieldnames or []:
                    val = (row.get(k) or "").strip()
                    if val:
                        last = val
                return last

            def _normalize_csv_row(r: dict) -> dict:
                # map common CSV headers into the same keys the reports code expects
                tcid_keys = [k for k in ("Test Case ID", "TestCaseID", "ID", "Test Case") if k in r]
                tcid = (r[tcid_keys[0]].strip() if tcid_keys else "") if r else ""
                module = (r.get("Module") or r.get("module") or "<Unknown>").strip()
                tctype = (r.get("Test Case Type") or r.get("Test Case Type ") or r.get("TestCaseType") or "").strip()
                summary = (r.get("Summary") or r.get("Test Description") or "").strip()
                status = _guess_status_from_row(r)
                return {
                    "Test Case ID": tcid,
                    "Module": module,
                    "Test Case Type": tctype,
                    "Status": status,
                    "Summary": summary,
                }

            records = [_normalize_csv_row(r) for r in csv_rows]
        except Exception as e:
            st.error(f"Failed to parse uploaded CSV: {e}")
            return
    else:
        if not tc_file.exists():
            st.info("No `Reports/test_cases.json` file found. Upload a CSV or generate test cases first.")
            return

        try:
            with tc_file.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            st.error(f"Failed to read test_cases.json: {e}")
            return

        records = raw if isinstance(raw, list) else [raw]

    # Build unique mapping by Test Case ID + Module.
    # NOTE: Test Case IDs may be reused across modules (e.g. SG_1 for Login and SG_1 for SignUp).
    # To ensure both are counted, use a composite key of (Test Case ID, Module). Records without
    # a Test Case ID are also included using a synthetic key based on their index.
    unique_by_id = {}
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        tcid = (rec.get("Test Case ID") or rec.get("TestCaseID") or "").strip()
        module = (rec.get("Module") or "<Unknown>").strip()
        if tcid:
            key = f"{tcid}||{module}"
        else:
            # include records without Test Case ID using a stable synthetic key
            key = f"__noid__{idx}||{module}"
        if key not in unique_by_id:
            unique_by_id[key] = rec

    # If there are no Test Case IDs, inform the user
    if not unique_by_id:
        st.warning("No records contain a `Test Case ID`. Charts require Test Case IDs to compute unique counts.")
        return

    # Compute counters
    type_counter = Counter()
    status_counter = Counter()
    module_counter = Counter()

    for tcid, rec in unique_by_id.items():
        t = (rec.get("Test Case Type") or "").strip()
        if not t:
            t = "Other"
        type_counter[t] += 1

        raw_status = rec.get("Status") or "Not Tested"
        status = _normalize_status(raw_status)
        status_counter[status] += 1

        mod = (rec.get("Module") or "<Unknown>").strip()
        module_counter[mod] += 1

    total_unique = len(unique_by_id)
    st.subheader("Totals")
    c1, c2 = st.columns([1, 2])
    c1.metric("Unique Test Case IDs", total_unique)
    # show a compact module counts table so totals (Login/SignUp) are unambiguous
    c2.markdown("**Module distribution**")
    mod_rows = [{"Module": m, "Count": cnt} for m, cnt in module_counter.most_common()]
    if mod_rows:
        c2.table(mod_rows)
    else:
        c2.write("No module data")

    st.markdown("\n---\n")

    # Prepare data for charts
    module_items = module_counter.most_common()

    # Positive / Negative breakdown
    pos = sum(v for k, v in type_counter.items() if k.lower().startswith("pos") or k.lower() == "positive")
    neg = sum(v for k, v in type_counter.items() if k.lower().startswith("neg") or k.lower() == "negative")
    other = sum(v for k, v in type_counter.items() if k.lower() not in ("positive", "negative", "pos", "neg"))
    pn_data = []
    if pos:
        pn_data.append({"category": "Positive", "count": pos})
    if neg:
        pn_data.append({"category": "Negative", "count": neg})
    if other:
        pn_data.append({"category": "Other", "count": other})
    if not pn_data:
        for k, v in type_counter.items():
            pn_data.append({"category": k, "count": v})

    # Pass/Fail data
    s_data = [{"status": k, "count": v} for k, v in status_counter.items()]

    # Module bar data (use top N for readability)
    top_n = 12
    top_modules = module_items[:top_n]
    mod_data = [{"module": m, "count": c} for m, c in top_modules]

    # Layout: display 3 charts in a row (pies + module bar)
    st.subheader("Overview")
    col_a, col_b, col_c = st.columns([1, 1, 1], gap="medium")

    with col_a:
        st.markdown("**Positive vs Negative**")
        if pn_data:
            spec = {
                "mark": {"type": "arc", "innerRadius": 20},
                "encoding": {
                    "theta": {"field": "count", "type": "quantitative"},
                    "color": {"field": "category", "type": "nominal"},
                    "tooltip": [{"field": "category"}, {"field": "count", "type": "quantitative"}],
                },
            }
            st.vega_lite_chart(pn_data, spec, use_container_width=True)
        else:
            st.info("No Positive/Negative data available")

    with col_b:
        st.markdown("**Pass vs Fail**")
        if s_data:
            spec2 = {
                "mark": {"type": "arc", "innerRadius": 20},
                "encoding": {
                    "theta": {"field": "count", "type": "quantitative"},
                    "color": {"field": "status", "type": "nominal"},
                    "tooltip": [{"field": "status"}, {"field": "count", "type": "quantitative"}],
                },
            }
            st.vega_lite_chart(s_data, spec2, use_container_width=True)
        else:
            st.info("No pass/fail data available")

    with col_c:
        st.markdown("**Test cases per Module (top {})**".format(top_n))
        if mod_data:
            # horizontal bar for readability of long module names
            spec3 = {
                "mark": "bar",
                "encoding": {
                    "y": {"field": "module", "type": "nominal", "sort": "-x"},
                    "x": {"field": "count", "type": "quantitative"},
                    "tooltip": [{"field": "module"}, {"field": "count", "type": "quantitative"}],
                },
            }
            st.vega_lite_chart(mod_data, spec3, use_container_width=True)
        else:
            st.info("No module data available")

    st.markdown("\n---\n")

    # Heatmap (bigger and full-width)
    st.subheader("Heatmap: Module vs Status")
    heat = []
    statuses_list = list(status_counter.keys())
    for m, _cnt in module_items:
        for s in statuses_list:
            cnt = 0
            for rec in unique_by_id.values():
                if (rec.get("Module") or "").strip() == m and _normalize_status(rec.get("Status") or "Not Tested") == s:
                    cnt += 1
            if cnt:
                heat.append({"module": m, "status": s, "count": cnt})

    if heat:
        spec_heat = {
            "height": 480,
            "mark": "rect",
            "encoding": {
                "x": {"field": "module", "type": "nominal", "axis": {"labelAngle": -45}},
                "y": {"field": "status", "type": "nominal"},
                "color": {"field": "count", "type": "quantitative"},
                "tooltip": [{"field": "module"}, {"field": "status"}, {"field": "count", "type": "quantitative"}],
            },
        }
        st.vega_lite_chart(heat, spec_heat, use_container_width=True)
    else:
        st.info("No heatmap data available")

    # Pass/Fail over time
    # Detect date-like columns in uploaded CSV (reader.fieldnames) or JSON records keys.
    def _looks_like_date(s: str) -> bool:
        if not s or not isinstance(s, str):
            return False
        s = s.strip()
        # quick regex for common numeric date formats like 6/1/2025 or 2025-06-01
        if re.match(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$", s):
            # attempt to parse to be more confident
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%y"):
                try:
                    datetime.strptime(s, fmt)
                    return True
                except Exception:
                    continue
        return False

    def _parse_date(s: str) -> datetime:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
        # fallback: try dateutil parser if available, else raise
        raise ValueError(f"Unrecognized date format: {s}")

    date_fields = []
    csv_rows_local = None
    # If uploaded was used earlier, csv_rows variable exists in scope and reader.fieldnames too
    try:
        if uploaded is not None:
            # reader was used to parse CSV earlier; attempt to re-read uploaded for fieldnames if needed
            # but we preserved csv_rows in that branch; try to access it
            csv_rows_local = csv_rows  # noqa: F821
            fieldnames = (reader.fieldnames if 'reader' in locals() else None) or []
            date_fields = [f for f in (fieldnames or []) if _looks_like_date(f)]
        else:
            # check JSON records keys
            keys = set()
            for r in records:
                if isinstance(r, dict):
                    keys.update(r.keys())
            date_fields = [k for k in keys if _looks_like_date(k)]
    except Exception:
        date_fields = []

    if date_fields:
        # Build time series counts for Pass/Fail per date field
        ts_counts = []
        # choose data source: csv_rows_local preferred (gives per-date columns), else records
        source_rows = csv_rows_local if csv_rows_local is not None else records
        for df in date_fields:
            pass_cnt = 0
            fail_cnt = 0
            for r in source_rows:
                try:
                    # when source is csv rows, r is dict with that column; for JSON, r[df] may exist
                    val = (r.get(df) if isinstance(r, dict) else None) or ""
                except Exception:
                    val = ""
                norm = _normalize_status(val)
                if norm == "Pass":
                    pass_cnt += 1
                elif norm == "Fail":
                    fail_cnt += 1
            # parse df into ISO string for x-axis ordering
            try:
                parsed = _parse_date(df)
                date_iso = parsed.strftime("%Y-%m-%d")
            except Exception:
                date_iso = df
            ts_counts.append({"date": date_iso, "Pass": pass_cnt, "Fail": fail_cnt})

        # Sort by date when possible
        try:
            ts_counts.sort(key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d"))
        except Exception:
            pass

        # Convert to long form for Vega-Lite
        ts_long = []
        for row in ts_counts:
            ts_long.append({"date": row["date"], "result": "Pass", "count": row["Pass"]})
            ts_long.append({"date": row["date"], "result": "Fail", "count": row["Fail"]})

        st.markdown("\n---\n")
        st.subheader("Pass/Fail over time")
        if any(r["count"] for r in ts_long):
            spec_time = {
                "mark": {"type": "line", "point": True},
                "encoding": {
                    "x": {"field": "date", "type": "temporal"},
                    "y": {"field": "count", "type": "quantitative"},
                    "color": {"field": "result", "type": "nominal"},
                    "tooltip": [{"field": "date"}, {"field": "result"}, {"field": "count", "type": "quantitative"}],
                },
            }
            st.vega_lite_chart(ts_long, spec_time, use_container_width=True)
        else:
            st.info("Date columns detected but no Pass/Fail values found for those dates.")
    else:
        # No date columns detected; do nothing (user requested to remove graph if not present)
        pass

    # End: removed raw counts display per user request

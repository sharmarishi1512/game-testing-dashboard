import json
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
    if not tc_file.exists():
        st.info("No `Reports/test_cases.json` file found. Generate test cases first.")
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

    # End: removed raw counts display per user request

import json
from pathlib import Path
import streamlit as st


def render():
    """Render the Reports page using only Reports/test_cases.json as the source."""
    st.header("Reports")
    st.write("Visualize test cases stored in `Reports/test_cases.json`.")

    repo_root = Path(__file__).resolve().parents[1]
    testcases_file = repo_root / "Reports" / "test_cases.json"

    if not testcases_file.exists():
        st.info("No saved test cases found. Generate some from the Test Case Generation page first.")
        return

    try:
        with testcases_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        st.error(f"Failed to read test cases file: {e}")
        return

    # normalize to records list
    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        st.error("Unexpected data format in test_cases.json")
        return

    # optional pandas for nicer table display
    try:
        import pandas as pd
    except Exception:
        pd = None

    # small helper
    def get_field(rec, key):
        return rec.get(key) if isinstance(rec, dict) else None

    # Summary at top
    modules = [get_field(r, "Module") or "<Unknown>" for r in records]
    statuses = [get_field(r, "Status") or "<Unknown>" for r in records]
    types = [get_field(r, "Test Case Type") or "<Unknown>" for r in records]
    total = len(records)

    st.subheader("Summary")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total test cases", total)
    try:
        from collections import Counter

        top_module, top_module_count = Counter(modules).most_common(1)[0]
    except Exception:
        top_module, top_module_count = "-", 0
    try:
        top_status, top_status_count = Counter(statuses).most_common(1)[0]
    except Exception:
        top_status, top_status_count = "-", 0

    col2.metric("Top module", f"{top_module} ({top_module_count})")
    col3.metric("Top status", f"{top_status} ({top_status_count})")

    # # Single download button for the saved JSON
    # try:
    #     with testcases_file.open("rb") as _f:
    #         raw_json_bytes = _f.read()
    #     st.download_button(
    #         "Download saved JSON",
    #         data=raw_json_bytes,
    #         file_name="test_cases.json",
    #         mime="application/json",
    #     )
    # except Exception:
    #     # If read fails, don't block the UI
    #     pass

    st.markdown("---")

    # Sidebar filters
    st.sidebar.header("Filters")
    unique_modules = sorted({m for m in modules if m is not None})
    selected_modules = st.sidebar.multiselect("Module", unique_modules, default=unique_modules)
    unique_status = sorted({s for s in statuses if s is not None})
    selected_status = st.sidebar.multiselect("Status", unique_status, default=unique_status)
    unique_types = sorted({t for t in types if t is not None})
    selected_types = st.sidebar.multiselect("Test Case Type", unique_types, default=unique_types)

    def record_matches(r):
        m = get_field(r, "Module") or "<Unknown>"
        s = get_field(r, "Status") or "<Unknown>"
        t = get_field(r, "Test Case Type") or "<Unknown>"
        return (m in selected_modules) and (s in selected_status) and (t in selected_types)

    filtered = [r for r in records if record_matches(r)]

    st.subheader("Charts")

    # Compute Positive/Negative counts and Module counts, then show side-by-side
    from collections import Counter

    # Positive/Negative counts from filtered records
    pn_ctr = Counter()
    for r in filtered:
        if not isinstance(r, dict):
            continue
        t = (r.get("Test Case Type") or "").strip().lower()
        if t.startswith("positive"):
            pn_ctr["Positive"] += 1
        elif t.startswith("negative"):
            pn_ctr["Negative"] += 1
        else:
            pn_ctr["Other"] += 1

    # Module counts (use pandas if available for accurate counts)
    module_counts = None
    mc_fallback = None
    if pd is not None:
        try:
            df_tmp = pd.DataFrame(filtered)
            if not df_tmp.empty and "Module" in df_tmp.columns:
                module_counts = df_tmp["Module"].fillna("<Unknown>").value_counts()
        except Exception:
            module_counts = None
    if module_counts is None:
        mc_fallback = Counter([get_field(r, "Module") or "<Unknown>" for r in filtered])

    left, right = st.columns(2)

    with left:
        pie_rows = []
        for k in ("Positive", "Negative", "Other"):
            if pn_ctr.get(k):
                pie_rows.append({"label": k, "count": int(pn_ctr[k])})

        if pie_rows:
            st.markdown("**Positive vs Negative test cases**")
            spec = {
                "mark": {"type": "arc", "innerRadius": 20},
                "encoding": {
                    "theta": {"field": "count", "type": "quantitative"},
                    "color": {
                        "field": "label",
                        "type": "nominal",
                        "scale": {"domain": ["Positive", "Negative", "Other"], "range": ["#2ecc71", "#ff4d4f", "#d0d0d0"]},
                    },
                    "tooltip": [{"field": "label"}, {"field": "count", "type": "quantitative"}],
                },
            }
            try:
                st.vega_lite_chart(pie_rows, spec, use_container_width=True)
            except Exception:
                st.write(dict(pn_ctr))
        else:
            st.write("No Positive/Negative data to display")

    with right:
        st.markdown("**Test cases by Module**")
        if module_counts is not None:
            st.bar_chart(module_counts)
        else:
            if not mc_fallback:
                st.info("No test cases match the selected filters.")
            else:
                st.write(dict(mc_fallback))

    st.markdown("---")
    st.subheader("Test cases")
    try:
        if pd is not None:
            df_all = pd.DataFrame(filtered)
            st.dataframe(df_all)
        else:
            st.table(filtered)
    except Exception:
        st.write(filtered)
    

   

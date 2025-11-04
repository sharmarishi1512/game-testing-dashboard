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

    # Positive / Negative pie chart
    try:
        from collections import Counter

        ctr = Counter()
        for r in filtered:
            if not isinstance(r, dict):
                continue
            t = (r.get("Test Case Type") or "").strip().lower()
            if t.startswith("positive"):
                ctr["Positive"] += 1
            elif t.startswith("negative"):
                ctr["Negative"] += 1
            else:
                ctr["Other"] += 1

        pie_rows = []
        for k in ("Positive", "Negative", "Other"):
            if ctr.get(k):
                pie_rows.append({"label": k, "count": int(ctr[k])})

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
                st.write(dict(ctr))
    except Exception:
        pass

    # Module breakdown (bar chart) and table
    if pd is not None:
        df = pd.DataFrame(filtered)
        if df.empty:
            st.info("No test cases match the selected filters.")
        else:
            module_counts = df["Module"].fillna("<Unknown>").value_counts()
            st.markdown("**Test cases by Module**")
            st.bar_chart(module_counts)
    else:
        from collections import Counter

        if len(filtered) == 0:
            st.info("No test cases match the selected filters.")
        else:
            mc = Counter([get_field(r, "Module") or "<Unknown>" for r in filtered])
            st.markdown("**Test cases by Module**")
            st.write(dict(mc))

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
    

   

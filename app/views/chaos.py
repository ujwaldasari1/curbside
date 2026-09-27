import psycopg
import streamlit as st
from data import DAGSTER_UI

from evals.chaos import dagster_runs
from evals.chaos.faults import ETL_DSN, FAULTS, inject, is_injected, restore

st.title("Chaos lab")
st.caption("Inject a realistic upstream fault into the raw layer, run the transforms, and watch "
           "the data tests catch it and the incident agent trace it back to the source. "
           "Faults swap in a corrupted copy of a raw table; the real data is never modified.")

with psycopg.connect(ETL_DSN) as conn:
    active = [f for f in FAULTS.values() if is_injected(conn, f.table)]

if active:
    st.warning("Active faults: " + ", ".join(f.name for f in active))
    for fault in active:
        if st.button(f"Restore {fault.name}", type="primary"):
            with st.spinner("Restoring the raw table and rebuilding the warehouse..."):
                restore(fault)
            st.success("Restored. Run `transform_only` (or wait for the daily job) to clear the checks.")
            st.rerun()

name = st.selectbox("Fault", list(FAULTS), format_func=lambda n: f"{n} · {FAULTS[n].story}")
fault = FAULTS[name]
st.markdown(f"**Ground truth:** `{fault.root_cause_asset}`"
            f"{' · column `' + fault.root_cause_column + '`' if fault.root_cause_column else ''} · "
            f"category `{fault.category}`")

if st.button("Inject and run transforms", disabled=any(f.table == fault.table for f in active)):
    inject(fault)
    run_id = dagster_runs.launch("transform_only")
    st.success(f"Injected. Dagster run [{run_id[:8]}]({DAGSTER_UI}/runs/{run_id}) started; when its "
               "checks fail, the failure sensor launches the incident agent. Its report appears "
               "under Incidents.")

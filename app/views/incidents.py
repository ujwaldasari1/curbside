import json

import streamlit as st
from data import DAGSTER_UI, app_query

st.title("Incidents")
st.caption("Root-cause reports filed by the incident agent when a pipeline run or data check fails.")

incidents = app_query("select * from ops.incidents order by created_at desc limit 50")
if incidents.empty:
    st.info("No incidents yet. Break something in the Chaos lab to see the agent at work.")
    st.stop()

severity_icon = {"critical": ":red_circle:", "high": ":orange_circle:", "medium": ":yellow_circle:",
                 "low": ":white_circle:"}
for _, incident in incidents.iterrows():
    header = (f"{severity_icon.get(incident.severity, '')} #{incident.id} {incident.title} "
              f"({incident.created_at:%Y-%m-%d %H:%M})")
    with st.expander(header, expanded=bool(incident.id == incidents.id.max())):
        left, right = st.columns(2)
        left.markdown(f"**Failed asset:** `{incident.failed_asset}`")
        left.markdown(f"**Root cause:** `{incident.root_cause_asset}` · {incident.fault_category}")
        right.markdown(f"**Severity:** {incident.severity} · **Status:** {incident.status}")
        if incident.dagster_run_id:
            right.markdown(f"[Dagster run]({DAGSTER_UI}/runs/{incident.dagster_run_id})")
        st.markdown(incident.root_cause)
        if incident.suggested_fix:
            st.markdown(f"**Suggested fix:** {incident.suggested_fix}")
        if incident.evidence:
            st.code(json.dumps(incident.evidence, indent=2), language="json")

import streamlit as st
from data import ROOT, app_query

st.title("Agent evals")
st.caption("Analyst: golden questions scored against live reference SQL. Steward: PII tagging "
           "vs labels and vs OpenMetadata's auto-classifier. Incident: root-cause accuracy on "
           "injected faults.")

reports = sorted((ROOT / "evals" / "reports").glob("*.md"), reverse=True)
latest: dict[str, object] = {}
for report in reports:
    latest.setdefault(report.name.split("-")[0], report)

if not latest:
    st.info("No eval reports yet. Run `make eval-analyst`, `make eval-steward` or `make eval-chaos`.")
for _suite, report in sorted(latest.items()):
    with st.container(border=True):
        st.markdown(report.read_text())
        st.caption(report.name)

st.subheader("Agent runs")
st.dataframe(
    app_query("""select agent, trigger, count(*) as runs, round(avg(num_turns), 1) as avg_turns,
                        round(avg(duration_ms) / 1000.0, 1) as avg_seconds,
                        round(avg(total_cost_usd), 3) as avg_cost_usd,
                        round(sum(total_cost_usd), 2) as total_cost_usd,
                        sum(case when is_error then 1 else 0 end) as errors
                 from ops.agent_runs group by 1, 2 order by 1, 2"""),
    hide_index=True, width="stretch",
)

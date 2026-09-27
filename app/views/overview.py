import datetime as dt

import streamlit as st
from data import DAGSTER_UI, OM_UI, app_query, latest_runs, query, service_up

st.title("Curbside")
st.caption("An AI-native, metadata-driven data platform for NYC sanitation data: "
           "dlt, Postgres, dbt, Dagster, OpenMetadata, MCP and Claude agents.")

services = {
    "OpenMetadata": service_up(f"{OM_UI}/api/v1/system/version"),
    "Dagster": service_up(f"{DAGSTER_UI}/server_info"),
}
cols = st.columns(len(services) + 3)
for col, (name, up) in zip(cols, services.items(), strict=False):
    col.metric(name, "up" if up else "down")

counts = app_query("""
    select
      (select count(*) from ops.incidents where status = 'open') as open_incidents,
      (select count(*) from ops.metadata_proposals where status = 'pending') as pending_proposals,
      (select coalesce(sum(total_cost_usd), 0) from ops.agent_runs
        where started_at > now() - interval '30 days') as agent_cost_30d
""").iloc[0]
cols[2].metric("Open incidents", int(counts.open_incidents))
cols[3].metric("Pending approvals", int(counts.pending_proposals))
cols[4].metric("Agent spend (30d)", f"${float(counts.agent_cost_30d):.2f}")

st.subheader("The data")
stats = query("""
    select
      (select count(*) from marts.fct_service_requests) as requests,
      (select min(created_date) from marts.fct_service_requests) as requests_from,
      (select max(created_date) from marts.fct_service_requests) as requests_to,
      (select count(distinct month_start) from marts.fct_monthly_tonnage) as tonnage_months,
      (select min(month_start) from marts.fct_monthly_tonnage) as tonnage_from,
      (select max(month_start) from marts.fct_monthly_tonnage) as tonnage_to,
      (select sum(total_collected_tons) from marts.fct_monthly_tonnage
        where month_start > (select max(month_start) from marts.fct_monthly_tonnage) - interval '12 months')
        as tons_12m,
      (select count(*) from marts.dim_community_district) as districts
""").iloc[0]
cols = st.columns(4)
cols[0].metric("311 sanitation requests", f"{int(stats.requests):,}",
               help=f"{stats.requests_from:%b %d, %Y} to {stats.requests_to:%b %d, %Y}")
cols[1].metric("DSNY tonnage history", f"{int(stats.tonnage_months):,} months",
               help=f"{stats.tonnage_from:%b %Y} to {stats.tonnage_to:%b %Y}")
cols[2].metric("Tons collected, last 12 months", f"{stats.tons_12m:,.0f}")
cols[3].metric("Community districts", int(stats.districts))

st.subheader("311 sanitation requests per week")
weekly = query("""
    select date_trunc('week', activity_date)::date as week, sum(requests_total) as requests
    from marts.fct_district_daily_sanitation
    where activity_date < date_trunc('week', (select max(activity_date) from marts.fct_district_daily_sanitation))
    group by 1 order by 1
""")
if not weekly.empty:
    st.line_chart(weekly, x="week", y="requests")

st.subheader("Latest pipeline runs")
runs = latest_runs()
if runs:
    st.dataframe(
        [{"job": r["jobName"], "status": r["status"],
          "started": dt.datetime.fromtimestamp(r["startTime"]).strftime("%Y-%m-%d %H:%M") if r["startTime"] else "",
          "run": r["runId"][:8]} for r in runs],
        hide_index=True, width="stretch",
    )
else:
    st.info("Dagster is not reachable. Start it with `make dagster`.")

st.subheader("Diversion rate by borough, last 12 reported months")
diversion = query("""
    select t.month_start, d.borough,
           sum(t.curbside_recycling_tons + t.organics_tons) / sum(t.total_collected_tons) as diversion_rate
    from marts.fct_monthly_tonnage t join marts.dim_community_district d using (boro_cd)
    where t.month_start > (select max(month_start) from marts.fct_monthly_tonnage) - interval '12 months'
    group by 1, 2 order by 1
""")
if not diversion.empty:
    st.line_chart(diversion, x="month_start", y="diversion_rate", color="borough")

st.markdown(f"Catalog: [OpenMetadata]({OM_UI}) · Orchestration: [Dagster]({DAGSTER_UI})")

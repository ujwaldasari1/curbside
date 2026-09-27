"""Dagster code location for Curbside: `dagster dev -m orchestration.definitions`."""

from dagster import (
    AssetSelection,
    DefaultScheduleStatus,
    Definitions,
    ScheduleDefinition,
    define_asset_job,
    in_process_executor,
)
from dagster_dbt import DbtCliResource
from dagster_dlt import DagsterDltResource

from orchestration.agent_jobs import (
    build_failure_sensor,
    incident_triage,
    metadata_stewardship,
    steward_schedule,
)
from orchestration.dbt_assets import curbside_dbt_assets, dbt_project
from orchestration.ingestion_assets import ingestion_assets
from orchestration.openmetadata_assets import openmetadata_catalog

daily_refresh_job = define_asset_job(
    name="daily_refresh",
    selection=AssetSelection.all(),
    description="Ingest all sources from NYC Open Data / Open-Meteo, dbt build, sync OpenMetadata.",
)

# dbt + catalog sync without re-ingesting: used by the chaos harness, whose faults live in
# the raw layer and would be overwritten by a fresh load.
transform_only_job = define_asset_job(
    name="transform_only",
    selection=AssetSelection.assets(curbside_dbt_assets, openmetadata_catalog),
    description="dbt build + OpenMetadata sync on the current raw layer (no ingestion).",
)

daily_refresh_schedule = ScheduleDefinition(
    job=daily_refresh_job,
    cron_schedule="0 6 * * *",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.RUNNING,
)

defs = Definitions(
    assets=[*ingestion_assets, curbside_dbt_assets, openmetadata_catalog],
    jobs=[daily_refresh_job, transform_only_job, incident_triage, metadata_stewardship],
    schedules=[daily_refresh_schedule, steward_schedule],
    sensors=[build_failure_sensor([daily_refresh_job, transform_only_job])],
    # One process per run: dlt pipelines initialise their working dirs on import, which
    # races across multiprocess steps, and a single process keeps memory low on a laptop.
    executor=in_process_executor,
    resources={
        "dlt": DagsterDltResource(),
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)

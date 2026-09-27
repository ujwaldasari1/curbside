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

from orchestration.dbt_assets import curbside_dbt_assets, dbt_project
from orchestration.ingestion_assets import ingestion_assets

daily_refresh_job = define_asset_job(
    name="daily_refresh",
    selection=AssetSelection.all(),
    description="Ingest all sources from NYC Open Data / Open-Meteo, then dbt build.",
)

daily_refresh_schedule = ScheduleDefinition(
    job=daily_refresh_job,
    cron_schedule="0 6 * * *",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.RUNNING,
)

defs = Definitions(
    assets=[*ingestion_assets, curbside_dbt_assets],
    jobs=[daily_refresh_job],
    schedules=[daily_refresh_schedule],
    # One process per run: dlt pipelines initialise their working dirs on import, which
    # races across multiprocess steps, and a single process keeps memory low on a laptop.
    executor=in_process_executor,
    resources={
        "dlt": DagsterDltResource(),
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)

"""Agents wired into Dagster.

- incident_triage: launched by a run-failure sensor. Pushes the failing dbt test results
  into OpenMetadata, then runs the incident agent on the failed run.
- metadata_stewardship: nightly steward review (schedule starts STOPPED; each run costs
  API credits, so turning it on is a deliberate choice).
"""

import os

import anyio
from dagster import (
    Config,
    DefaultScheduleStatus,
    DefaultSensorStatus,
    MetadataValue,
    OpExecutionContext,
    RunFailureSensorContext,
    RunRequest,
    ScheduleDefinition,
    SkipReason,
    job,
    op,
    run_failure_sensor,
)

from governance.catalog_sync import sync_dbt

CHAOS_EVAL_TAG = "curbside/chaos_eval"  # evals call the agent themselves; the sensor skips these runs


class TriageConfig(Config):
    failed_run_id: str


@op
def triage_failed_run(context: OpExecutionContext, config: TriageConfig) -> None:
    from agents import incident

    sync_dbt()  # failing test results -> OpenMetadata, so the agent sees them in the catalog
    result = anyio.run(incident.triage, config.failed_run_id, "dagster_sensor")
    output = result.output or {}
    context.add_output_metadata({
        "root_cause_asset": output.get("root_cause_asset"),
        "fault_category": output.get("fault_category"),
        "severity": output.get("severity"),
        "incident_id": output.get("incident_id"),
        "root_cause": MetadataValue.md(output.get("root_cause") or result.text or ""),
        "cost_usd": result.cost_usd,
        "turns": result.num_turns,
    })


@job(description="Root-cause analysis of a failed run by the incident agent.")
def incident_triage():
    triage_failed_run()


@op
def run_steward_review(context: OpExecutionContext) -> None:
    from agents import steward

    result = anyio.run(steward.review, None, "dagster_schedule")
    output = result.output or {}
    context.add_output_metadata({
        "proposals": len(output.get("proposals", [])),
        "summary": MetadataValue.md(output.get("summary") or result.text or ""),
        "cost_usd": result.cost_usd,
    })


@job(description="Steward agent reviews the catalog and queues proposals for approval.")
def metadata_stewardship():
    run_steward_review()


steward_schedule = ScheduleDefinition(
    job=metadata_stewardship,
    cron_schedule="30 7 * * *",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.STOPPED,
)


def build_failure_sensor(monitored_jobs):
    @run_failure_sensor(
        monitored_jobs=monitored_jobs,
        request_job=incident_triage,
        default_status=DefaultSensorStatus.RUNNING,
        minimum_interval_seconds=30,
    )
    def triage_on_failure(context: RunFailureSensorContext):
        run = context.dagster_run
        if run.tags.get(CHAOS_EVAL_TAG) == "true":
            return SkipReason(f"run {run.run_id} belongs to a chaos eval; the eval triages it")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return SkipReason("ANTHROPIC_API_KEY not set; incident agent disabled")
        return RunRequest(
            run_key=run.run_id,
            run_config={"ops": {"triage_failed_run": {"config": {"failed_run_id": run.run_id}}}},
            tags={"curbside/triaged_run": run.run_id},
        )

    return triage_on_failure

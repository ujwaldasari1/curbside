"""Read-only Dagster GraphQL queries used by diagnose_asset and get_run_failure."""

import datetime as dt
import os

import requests

DAGSTER_URL = os.environ.get("DAGSTER_URL", "http://127.0.0.1:3000")

ASSET_STATUS = """
query($key: AssetKeyInput!) {
  assetOrError(assetKey: $key) {
    __typename
    ... on Asset {
      assetMaterializations(limit: 1) { timestamp runId }
      definition {
        assetChecksOrError {
          ... on AssetChecks {
            checks {
              name
              executionForLatestMaterialization {
                status
                evaluation { success description }
              }
            }
          }
        }
      }
    }
  }
}
"""

RUN_FAILURE = """
query($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run {
      runId jobName status startTime endTime
      stepStats { stepKey status }
      eventConnection {
        events {
          __typename
          ... on ExecutionStepFailureEvent { stepKey error { message } }
          ... on RunFailureEvent { message }
          ... on AssetCheckEvaluationEvent {
            evaluation { checkName success assetKey { path } }
          }
        }
      }
    }
  }
}
"""

RECENT_FAILED_RUNS = """
{ runsOrError(filter: {statuses: [FAILURE]}, limit: 5) {
    ... on Runs { results { runId jobName status startTime } } } }
"""


class DagsterUnavailable(RuntimeError):
    pass


def _query(query: str, variables: dict | None = None) -> dict:
    try:
        response = requests.post(
            f"{DAGSTER_URL}/graphql", json={"query": query, "variables": variables or {}}, timeout=20
        )
    except requests.RequestException as err:
        raise DagsterUnavailable(f"Dagster not reachable at {DAGSTER_URL}: {err}") from err
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise DagsterUnavailable(str(body["errors"])[:500])
    return body["data"]


def _iso(ts: float | str | None) -> str | None:
    if ts is None:
        return None
    seconds = float(ts)
    if seconds > 1e11:  # materialization timestamps are in milliseconds
        seconds /= 1000
    return dt.datetime.fromtimestamp(seconds, dt.UTC).isoformat(timespec="seconds")


def asset_status(schema: str, table: str) -> dict:
    data = _query(ASSET_STATUS, {"key": {"path": [schema, table]}})["assetOrError"]
    if data["__typename"] != "Asset":
        return {"known_to_dagster": False}
    materializations = data["assetMaterializations"]
    checks = ((data.get("definition") or {}).get("assetChecksOrError") or {}).get("checks") or []
    failed = [
        {"check": c["name"], "status": c["executionForLatestMaterialization"]["status"],
         "description": (c["executionForLatestMaterialization"].get("evaluation") or {}).get("description")}
        for c in checks
        if c.get("executionForLatestMaterialization")
        and c["executionForLatestMaterialization"]["status"] not in ("SUCCEEDED", "IN_PROGRESS")
    ]
    return {
        "known_to_dagster": True,
        "last_materialized_at": _iso(materializations[0]["timestamp"]) if materializations else None,
        "last_run_id": materializations[0]["runId"] if materializations else None,
        "checks_total": len(checks),
        "failed_checks": failed,
    }


def run_failure(run_id: str) -> dict:
    run = _query(RUN_FAILURE, {"runId": run_id})["runOrError"]
    if run["__typename"] != "Run":
        return {"found": False, "run_id": run_id}
    events = run["eventConnection"]["events"]
    return {
        "found": True,
        "run_id": run["runId"],
        "job": run["jobName"],
        "status": run["status"],
        "started_at": _iso(run["startTime"]),
        "ended_at": _iso(run["endTime"]),
        "failed_steps": [s["stepKey"] for s in run["stepStats"] if s["status"] == "FAILURE"],
        "skipped_steps": [s["stepKey"] for s in run["stepStats"] if s["status"] == "SKIPPED"],
        "step_errors": [
            {"step": e["stepKey"], "error": (e.get("error") or {}).get("message", "")[:2000]}
            for e in events if e["__typename"] == "ExecutionStepFailureEvent"
        ],
        "failed_checks": [
            {"asset": "/".join(e["evaluation"]["assetKey"]["path"]), "check": e["evaluation"]["checkName"]}
            for e in events
            if e["__typename"] == "AssetCheckEvaluationEvent" and not e["evaluation"]["success"]
        ],
    }


def recent_failed_runs() -> list[dict]:
    runs = _query(RECENT_FAILED_RUNS)["runsOrError"]["results"]
    return [{**r, "startTime": _iso(r["startTime"])} for r in runs]

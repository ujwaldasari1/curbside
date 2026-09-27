"""Launch Dagster jobs through the webserver's GraphQL API (so runs show in the UI and
the run-failure sensor sees them) and wait for them to finish."""

import os
import time

import requests

DAGSTER_URL = os.environ.get("DAGSTER_URL", "http://127.0.0.1:3000")

LAUNCH = """
mutation($selector: JobOrPipelineSelector!, $tags: [ExecutionTag!]) {
  launchRun(executionParams: {selector: $selector, executionMetadata: {tags: $tags}}) {
    __typename
    ... on LaunchRunSuccess { run { runId } }
    ... on PythonError { message }
    ... on InvalidSubsetError { message }
    ... on RunConfigValidationInvalid { errors { message } }
  }
}
"""

LOCATION = """
{ repositoriesOrError { ... on RepositoryConnection { nodes { name location { name } } } } }
"""

STATUS = """
query($runId: ID!) { runOrError(runId: $runId) { ... on Run { status } } }
"""

TERMINAL = {"SUCCESS", "FAILURE", "CANCELED"}


def _gql(query: str, variables: dict | None = None) -> dict:
    response = requests.post(f"{DAGSTER_URL}/graphql", json={"query": query, "variables": variables or {}},
                             timeout=30)
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def launch(job: str, tags: dict[str, str] | None = None) -> str:
    repo = _gql(LOCATION)["repositoriesOrError"]["nodes"][0]
    selector = {"repositoryLocationName": repo["location"]["name"], "repositoryName": repo["name"],
                "jobName": job}
    result = _gql(LAUNCH, {"selector": selector,
                           "tags": [{"key": k, "value": v} for k, v in (tags or {}).items()]})["launchRun"]
    if result["__typename"] != "LaunchRunSuccess":
        raise RuntimeError(f"could not launch {job}: {result}")
    return result["run"]["runId"]


def wait(run_id: str, timeout_s: int = 900) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = _gql(STATUS, {"runId": run_id})["runOrError"]["status"]
        if status in TERMINAL:
            return status
        time.sleep(3)
    raise TimeoutError(f"run {run_id} did not finish in {timeout_s}s")

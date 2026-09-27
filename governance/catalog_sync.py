"""Sync the warehouse, dbt project and Dagster into OpenMetadata, in dependency order.

  python -m governance.catalog_sync            # full sync
  python -m governance.catalog_sync dbt        # only re-push dbt artifacts (fast; used
                                               # after a failed build so failing tests
                                               # show up in the catalog)

Used by `make om-ingest`, the Dagster `openmetadata/catalog` asset and the run-failure
sensor. The `metadata` CLI runs from its own virtualenv (see infra/openmetadata/ingestion).
"""

import os
import subprocess
import sys
from pathlib import Path

import requests

from governance import seed_governance
from shared.openmetadata import OpenMetadataClient

ROOT = Path(__file__).resolve().parent.parent
METADATA_CLI = ROOT / "infra/openmetadata/ingestion/.venv/bin/metadata"
WORKFLOWS = ROOT / "infra/openmetadata/ingestion/workflows"
DAGSTER_URL = os.environ.get("DAGSTER_URL", "http://127.0.0.1:3000")


class CatalogSyncError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path = ROOT) -> str:
    env = {**os.environ, "CURBSIDE_ROOT": str(ROOT), "DAGSTER_URL": DAGSTER_URL}
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-25:])
        raise CatalogSyncError(f"{' '.join(args)} failed:\n{tail}")
    return result.stdout


def _ingest(workflow: str) -> None:
    _run([str(METADATA_CLI), "ingest", "-c", str(WORKFLOWS / workflow)])


def dagster_is_up() -> bool:
    try:
        return requests.get(f"{DAGSTER_URL}/server_info", timeout=3).ok
    except requests.RequestException:
        return False


def sync_dbt() -> None:
    """Re-push dbt artifacts (descriptions, lineage, test definitions + latest results)."""
    _run(["dbt", "docs", "generate", "--target-path", "target/docs", "--quiet"], cwd=ROOT / "transform")
    _ingest("dbt.yaml")


def sync_all(log=print) -> list[str]:
    steps = []
    om = OpenMetadataClient()
    seed_governance.seed_pre(om)
    steps.append("governance (team, domain, glossary)")
    _ingest("postgres_metadata.yaml")
    steps.append("warehouse metadata")
    sync_dbt()
    steps.append("dbt metadata, lineage and test results")
    if dagster_is_up():
        _ingest("dagster.yaml")
        steps.append("dagster pipelines and pipeline lineage")
    else:
        log(f"Dagster webserver not reachable at {DAGSTER_URL}; skipping pipeline ingestion")
    seed_governance.seed_post(om)
    steps.append("domain assets, data product, source API lineage")
    for step in steps:
        log(f"synced: {step}")
    return steps


if __name__ == "__main__":
    if sys.argv[1:] == ["dbt"]:
        sync_dbt()
        print("synced: dbt metadata, lineage and test results")
    else:
        sync_all()

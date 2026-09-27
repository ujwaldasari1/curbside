"""Dagster assets for the dbt project. dbt tests surface as Dagster asset checks."""

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, AssetKey
from dagster_dbt import (
    DagsterDbtTranslator,
    DagsterDbtTranslatorSettings,
    DbtCliResource,
    DbtProject,
    dbt_assets,
)

DBT_PROJECT_DIR = Path(__file__).resolve().parent.parent / "transform"

dbt_project = DbtProject(project_dir=DBT_PROJECT_DIR, profiles_dir=DBT_PROJECT_DIR)
dbt_project.prepare_if_dev()


class CurbsideDbtTranslator(DagsterDbtTranslator):
    """Keys dbt sources as `[schema, table]` (matching the dlt assets that load them) and
    groups dbt assets by layer (staging / intermediate / marts)."""

    def get_asset_spec(self, manifest: Mapping[str, Any], unique_id: str, project):
        spec = super().get_asset_spec(manifest, unique_id, project)
        source = manifest["sources"].get(unique_id)
        if source is not None:
            return spec.replace_attributes(key=AssetKey([source["schema"], source["name"]]))
        node = manifest["nodes"].get(unique_id)
        if node is None:
            return spec
        if node["resource_type"] == "seed":
            return spec.replace_attributes(group_name="staging")
        if node["resource_type"] == "model":
            return spec.replace_attributes(group_name=node["fqn"][1])
        return spec


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    dagster_dbt_translator=CurbsideDbtTranslator(
        settings=DagsterDbtTranslatorSettings(enable_asset_checks=True)
    ),
)
def curbside_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    invocation = dbt.cli(["build"], context=context)
    try:
        yield from invocation.stream()
    finally:
        # Publish artifacts where OpenMetadata's dbt ingestion reads them, including after
        # a failed build, so failing tests reach the catalog and the incident agent.
        for artifact in ("manifest.json", "run_results.json"):
            source = invocation.target_path / artifact
            if source.exists():
                shutil.copy(source, DBT_PROJECT_DIR / "target" / artifact)

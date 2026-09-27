"""Dagster assets for the dbt project. dbt tests surface as Dagster asset checks."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext
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
    """Groups dbt assets by layer (staging / intermediate / marts)."""

    def get_asset_spec(self, manifest: Mapping[str, Any], unique_id: str, project):
        spec = super().get_asset_spec(manifest, unique_id, project)
        node = manifest["nodes"].get(unique_id)
        if node is None:  # dbt sources keep their default spec
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
    yield from dbt.cli(["build"], context=context).stream()

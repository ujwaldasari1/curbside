"""Keeps OpenMetadata in step with the platform: runs after every dbt build."""

from dagster import AssetExecutionContext, AssetKey, MaterializeResult, MetadataValue, asset

from governance.catalog_sync import sync_all
from orchestration.dbt_assets import curbside_dbt_assets


@asset(
    key=AssetKey(["openmetadata", "catalog"]),
    deps=[curbside_dbt_assets],
    group_name="governance",
    kinds={"openmetadata"},
    description="Governance seed, warehouse + dbt + Dagster metadata, lineage and test "
    "results synced into OpenMetadata.",
)
def openmetadata_catalog(context: AssetExecutionContext) -> MaterializeResult:
    steps = sync_all(log=context.log.info)
    return MaterializeResult(
        metadata={
            "steps": MetadataValue.md("\n".join(f"- {s}" for s in steps)),
            "catalog": MetadataValue.url("http://localhost:8585/explore/tables"),
        }
    )

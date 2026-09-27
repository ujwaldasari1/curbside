"""Dagster assets for the dlt ingestion pipelines (one multi-asset per source).

Every Dagster asset key in Curbside is `[schema, table]` (here e.g.
`raw_nyc311/service_requests`). The dbt translator keys dbt sources the same way, so
Dagster wires raw tables to the models that read them, and OpenMetadata's Dagster
connector can resolve each asset to its warehouse table for pipeline lineage.
"""

from dagster import AssetExecutionContext, AssetKey
from dagster_dlt import DagsterDltResource, DagsterDltTranslator, dlt_assets
from dagster_dlt.translator import DltResourceTranslatorData

from ingestion.run import PIPELINES, make_pipeline


class CurbsideDltTranslator(DagsterDltTranslator):
    def get_asset_spec(self, data: DltResourceTranslatorData):
        spec = super().get_asset_spec(data)
        return spec.replace_attributes(
            key=AssetKey([data.pipeline.dataset_name, data.resource.name]),
            deps=[],
            group_name="ingestion",
        )


def build_ingestion_assets(name: str):
    source_factory, _ = PIPELINES[name]

    @dlt_assets(
        dlt_source=source_factory(),
        dlt_pipeline=make_pipeline(name),
        name=f"ingest_{name}",
        dagster_dlt_translator=CurbsideDltTranslator(),
    )
    def _ingestion_assets(context: AssetExecutionContext, dlt: DagsterDltResource):
        yield from dlt.run(context=context)

    return _ingestion_assets


ingestion_assets = [build_ingestion_assets(name) for name in PIPELINES]

"""Dagster assets for the dlt ingestion pipelines (one multi-asset per source).

Asset keys are `[source, table]` (e.g. `nyc311/service_requests`), which is exactly how
dagster-dbt names dbt sources, so Dagster wires raw tables to the dbt models that read
them with no extra configuration.
"""

from dagster import AssetExecutionContext, AssetKey
from dagster_dlt import DagsterDltResource, DagsterDltTranslator, dlt_assets
from dagster_dlt.translator import DltResourceTranslatorData

from ingestion.run import PIPELINES, make_pipeline


class CurbsideDltTranslator(DagsterDltTranslator):
    def get_asset_spec(self, data: DltResourceTranslatorData):
        spec = super().get_asset_spec(data)
        return spec.replace_attributes(
            key=AssetKey([data.resource.source_name, data.resource.name]),
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

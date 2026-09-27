"""dlt sources for NYC Open Data (Socrata SODA API).

Datasets
  erm2-nwe9  311 Service Requests from 2020 to Present   -> raw_nyc311.service_requests
  ebb7-mvp5  DSNY Monthly Tonnage Data                   -> raw_dsny.monthly_tonnage
  xi7c-iiu2  NYC Population by Community Districts       -> raw_reference.community_district_population

Raw tables keep values exactly as delivered (mostly text); typing and cleaning happen in dbt.
"""

from collections.abc import Iterator

import dlt
from dlt.sources.helpers import requests

from ingestion.config import SOCRATA_APP_TOKEN, SR_START_DATE

SOCRATA_BASE = "https://data.cityofnewyork.us/resource"
PAGE_SIZE = 50_000

# Subset of the 311 schema relevant to sanitation analytics. incident_address and
# latitude/longitude are kept on purpose: they are the quasi-identifiers the Steward
# agent must discover and tag as PII in OpenMetadata.
SR_COLUMNS = [
    "unique_key",
    "created_date",
    "closed_date",
    "agency",
    "complaint_type",
    "descriptor",
    "location_type",
    "incident_zip",
    "incident_address",
    "street_name",
    "address_type",
    "city",
    "status",
    "resolution_description",
    "resolution_action_updated_date",
    "community_board",
    "council_district",
    "bbl",
    "borough",
    "latitude",
    "longitude",
    "open_data_channel_type",
]


def socrata_pages(
    dataset_id: str,
    select: str = "*",
    where: str | None = None,
    order: str | None = None,
    page_size: int = PAGE_SIZE,
) -> Iterator[list[dict]]:
    """Yield pages of rows from a Socrata dataset using stable-ordered offset paging."""
    headers = {"X-App-Token": SOCRATA_APP_TOKEN} if SOCRATA_APP_TOKEN else {}
    offset = 0
    while True:
        params = {"$select": select, "$limit": page_size, "$offset": offset}
        if where:
            params["$where"] = where
        if order:
            params["$order"] = order
        response = requests.get(
            f"{SOCRATA_BASE}/{dataset_id}.json", params=params, headers=headers, timeout=180
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return
        yield rows
        if len(rows) < page_size:
            return
        offset += page_size


def _soql_timestamp(value: str) -> str:
    """Socrata returns `:updated_at` as '2026-09-25T01:33:51.563Z'; SoQL literals take no 'Z'."""
    return value.rstrip("Z")


@dlt.resource(
    name="service_requests",
    primary_key="unique_key",
    write_disposition="merge",
)
def service_requests(
    source_updated_at=dlt.sources.incremental(
        "source_updated_at", initial_value="1970-01-01T00:00:00.000Z"
    ),
    start_date: str = SR_START_DATE,
) -> Iterator[list[dict]]:
    """DSNY 311 requests, loaded incrementally on Socrata's system `:updated_at`.

    Merging on unique_key means status changes (Open -> Closed) overwrite the earlier row.
    """
    where = (
        f"agency = 'DSNY' AND created_date >= '{start_date}T00:00:00' "
        f"AND :updated_at > '{_soql_timestamp(source_updated_at.last_value)}'"
    )
    select = ":updated_at, " + ", ".join(SR_COLUMNS)
    for page in socrata_pages("erm2-nwe9", select=select, where=where, order=":updated_at, unique_key"):
        for row in page:
            row["source_updated_at"] = row.pop(":updated_at")
        yield page


@dlt.resource(name="monthly_tonnage", write_disposition="replace")
def monthly_tonnage() -> Iterator[list[dict]]:
    """Full refresh: ~25k rows, one per community district per month since 1990."""
    yield from socrata_pages("ebb7-mvp5", order="month, borough_id, communitydistrict")


@dlt.resource(name="community_district_population", write_disposition="replace")
def community_district_population() -> Iterator[list[dict]]:
    yield from socrata_pages("xi7c-iiu2", order="borough, cd_number")


@dlt.source(name="nyc311")
def nyc311_source():
    return service_requests


@dlt.source(name="dsny")
def dsny_source():
    return monthly_tonnage


@dlt.source(name="reference")
def reference_source():
    return community_district_population

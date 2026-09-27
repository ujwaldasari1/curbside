"""Governance as code for OpenMetadata. Idempotent (PUT = create-or-update).

  python -m governance.seed_governance pre    # before ingestion: team, domain, glossary
  python -m governance.seed_governance post   # after ingestion: domain + data product assets

`pre` must run before dbt metadata ingestion, because dbt `meta.openmetadata` blocks
reference the owner team, the domain and glossary terms by name.
"""

import sys

from shared.openmetadata import OpenMetadataClient

SERVICE = "curbside_warehouse"
DATABASE = f"{SERVICE}.curbside"
TEAM = "curbside-data-team"
DOMAIN = "Sanitation"
GLOSSARY = "Sanitation"
DATA_PRODUCT = "DistrictSanitationScorecard"

GLOSSARY_TERMS: list[dict] = [
    {
        "name": "Refuse",
        "description": "Trash collected by DSNY for disposal (landfill or waste-to-energy). "
        "Excludes recycling and organics.",
        "synonyms": ["trash", "garbage"],
    },
    {
        "name": "Paper Recycling",
        "description": "The mixed paper and cardboard curbside recycling stream.",
        "synonyms": ["paper"],
    },
    {
        "name": "MGP",
        "displayName": "MGP (Metal, Glass, Plastic)",
        "description": "Metal, glass, plastic and beverage cartons: NYC's commingled curbside "
        "recycling stream.",
        "synonyms": ["commingled recycling"],
    },
    {
        "name": "Organics",
        "description": "Food scraps, yard waste, leaves and Christmas trees collected separately "
        "for composting.",
        "synonyms": ["compost", "food waste"],
    },
    {
        "name": "Tonnage",
        "description": "Weight of collected material in short tons (1 ton = 2,000 lbs), as "
        "reported monthly by DSNY per community district.",
    },
    {
        "name": "Diversion Rate",
        "description": "Share of collected tons kept out of disposal: (paper + MGP + organics) / "
        "total collected tons. Computed in `fct_monthly_tonnage`; ranges 0-1.",
        "synonyms": ["recycling rate"],
        "relatedTerms": ["Refuse", "Paper Recycling", "MGP", "Organics"],
    },
    {
        "name": "Community District",
        "description": "One of NYC's 59 community districts, the unit DSNY plans collection "
        "around. Identified by `boro_cd` = borough code x 100 + district number "
        "(e.g. 201 = Bronx CD 1).",
        "synonyms": ["CD", "boro_cd"],
    },
    {
        "name": "Joint Interest Area",
        "description": "Areas such as large parks and airports that carry a community board "
        "code (e.g. '55 BROOKLYN', '81 QUEENS') but have no residential population. "
        "Excluded from per-capita metrics.",
        "synonyms": ["JIA"],
        "relatedTerms": ["Community District"],
    },
    {
        "name": "Service Request",
        "description": "A 311 request routed to DSNY, identified by the 311 `unique_key`.",
        "synonyms": ["311 request", "complaint"],
    },
    {
        "name": "Missed Collection",
        "description": "A 311 complaint that scheduled curbside collection did not happen. "
        "Normalised per 1,000 tons of refuse as a service-reliability rate.",
        "relatedTerms": ["Service Request", "Refuse"],
    },
]

# Upstream source APIs, modelled as OpenMetadata API endpoints so lineage starts at the
# system of record: (service, collection, endpoint, url, description, raw table).
SOURCE_ENDPOINTS = [
    ("nyc_open_data", "socrata", "erm2-nwe9",
     "https://data.cityofnewyork.us/resource/erm2-nwe9.json",
     "311 Service Requests from 2020 to Present, filtered to agency = 'DSNY'. "
     "Loaded incrementally on the Socrata system field :updated_at.",
     "raw_nyc311.service_requests"),
    ("nyc_open_data", "socrata", "ebb7-mvp5",
     "https://data.cityofnewyork.us/resource/ebb7-mvp5.json",
     "DSNY Monthly Tonnage Data by community district. Full refresh.",
     "raw_dsny.monthly_tonnage"),
    ("nyc_open_data", "socrata", "xi7c-iiu2",
     "https://data.cityofnewyork.us/resource/xi7c-iiu2.json",
     "New York City Population By Community Districts (census). Full refresh.",
     "raw_reference.community_district_population"),
    ("open_meteo", "archive", "daily_weather_nyc",
     "https://archive-api.open-meteo.com/v1/archive",
     "Open-Meteo historical weather archive, daily aggregates for lat 40.7128, "
     "lon -74.0060. Full refresh.",
     "raw_weather.weather_daily"),
]
DAGSTER_SERVICE = "curbside_dagster"
DAGSTER_JOB = "daily_refresh"

# Certified tables that make up the data product.
DATA_PRODUCT_TABLES = [
    "marts.dim_community_district",
    "marts.fct_monthly_tonnage",
    "marts.fct_service_requests",
    "marts.fct_district_daily_sanitation",
    "marts.mart_district_monthly_scorecard",
]


def team_ref(om: OpenMetadataClient) -> dict:
    team = om.get_by_name("teams", TEAM)
    return {"id": team["id"], "type": "team"}


def seed_pre(om: OpenMetadataClient) -> None:
    om.put(
        "/v1/teams",
        {
            "name": TEAM,
            "displayName": "Curbside Data Team",
            "teamType": "Group",
            "description": "Owns the Curbside sanitation data platform.",
        },
    )
    owners = [team_ref(om)]
    om.put(
        "/v1/domains",
        {
            "name": DOMAIN,
            "displayName": "Sanitation",
            "domainType": "Source-aligned",
            "description": "NYC Department of Sanitation (DSNY) collection tonnage, 311 "
            "sanitation service requests and supporting reference data.",
            "owners": owners,
        },
    )
    om.put(
        "/v1/glossaries",
        {
            "name": GLOSSARY,
            "displayName": "Sanitation",
            "description": "Business vocabulary for NYC curbside collection and 311 sanitation "
            "service. Linked to tables and columns so humans and agents share definitions.",
            "owners": owners,
            "domains": [DOMAIN],
        },
    )
    # Two passes: related terms must exist before they can be referenced.
    for with_relations in (False, True):
        for term in GLOSSARY_TERMS:
            body = {k: v for k, v in term.items() if k != "relatedTerms"}
            body.update(glossary=GLOSSARY, owners=owners)
            if with_relations and term.get("relatedTerms"):
                body["relatedTerms"] = [f"{GLOSSARY}.{t}" for t in term["relatedTerms"]]
            om.put("/v1/glossaryTerms", body)
    print(f"seeded team '{TEAM}', domain '{DOMAIN}', glossary '{GLOSSARY}' "
          f"({len(GLOSSARY_TERMS)} terms)")


def seed_post(om: OpenMetadataClient) -> None:
    # Every schema in the warehouse belongs to the Sanitation domain.
    schemas = om.get("/v1/databaseSchemas", database=DATABASE, limit=50)["data"]
    om.put(
        f"/v1/domains/{DOMAIN}/assets/add",
        {"assets": [{"id": s["id"], "type": "databaseSchema"} for s in schemas]},
    )
    tables = []
    for name in DATA_PRODUCT_TABLES:
        table = om.get_by_name("tables", f"{DATABASE}.{name}")
        if table is None:
            raise SystemExit(f"table {name} not found in OpenMetadata; run metadata ingestion first")
        tables.append({"id": table["id"], "type": "table"})
    om.put(
        "/v1/dataProducts",
        {
            "name": DATA_PRODUCT,
            "displayName": "District Sanitation Scorecard",
            "description": "Certified, analysis-ready tables for comparing NYC community "
            "districts on collection tonnage, diversion and 311 service reliability.",
            "domains": [DOMAIN],
            "owners": [team_ref(om)],
        },
    )
    om.put(f"/v1/dataProducts/{DATA_PRODUCT}/assets/add", {"assets": tables})
    print(f"assigned {len(schemas)} schemas to domain '{DOMAIN}'; "
          f"data product '{DATA_PRODUCT}' has {len(tables)} tables")
    seed_source_lineage(om)


def find_dagster_pipeline(om: OpenMetadataClient, job_name: str) -> dict | None:
    """The Dagster connector names pipelines by a hash; the job name is the displayName."""
    listing = om.get("/v1/pipelines", service=DAGSTER_SERVICE, limit=100) or {"data": []}
    return next((p for p in listing["data"] if p.get("displayName") == job_name), None)


def seed_source_lineage(om: OpenMetadataClient) -> None:
    """API endpoint -> raw table lineage, stamped with the Dagster job when it is cataloged."""
    pipeline = find_dagster_pipeline(om, DAGSTER_JOB)
    owners = [team_ref(om)]
    for service, collection, endpoint, url, description, raw_table in SOURCE_ENDPOINTS:
        om.put("/v1/services/apiServices", {"name": service, "serviceType": "Rest"})
        om.put(
            "/v1/apiCollections",
            {"name": collection, "service": service, "endpointURL": url.rsplit("/", 1)[0]},
        )
        api = om.put(
            "/v1/apiEndpoints",
            {
                "name": endpoint,
                "apiCollection": f"{service}.{collection}",
                "endpointURL": url,
                "requestMethod": "GET",
                "description": description,
                "owners": owners,
                "domains": [DOMAIN],
            },
        )
        table = om.get_by_name("tables", f"{DATABASE}.{raw_table}")
        details = {
            "source": "PipelineLineage",
            "description": "Loaded by dlt, orchestrated by Dagster.",
        }
        if pipeline:
            details["pipeline"] = {"id": pipeline["id"], "type": "pipeline"}
        om.put(
            "/v1/lineage",
            {
                "edge": {
                    "fromEntity": {"id": api["id"], "type": "apiEndpoint"},
                    "toEntity": {"id": table["id"], "type": "table"},
                    "lineageDetails": details,
                }
            },
        )
    print(f"source lineage: {len(SOURCE_ENDPOINTS)} API endpoints -> raw tables"
          f"{' (via Dagster job ' + DAGSTER_JOB + ')' if pipeline else ''}")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "pre"
    client = OpenMetadataClient()
    {"pre": seed_pre, "post": seed_post}[stage](client)

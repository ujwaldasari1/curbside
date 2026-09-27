# Curbside warehouse overview

Postgres database `curbside`, cataloged in OpenMetadata as service `curbside_warehouse`
(table FQN = `curbside_warehouse.curbside.<schema>.<table>`).

## Layers
| Schema | Built by | Contents |
|---|---|---|
| `raw_nyc311` | dlt, incremental merge on `:updated_at` | DSNY 311 service requests as delivered (text + timestamptz) |
| `raw_dsny` | dlt, full refresh | Monthly tonnage by community district (all text) |
| `raw_reference` | dlt, full refresh | Community district population (census) |
| `raw_weather` | dlt, full refresh | Daily NYC weather (Open-Meteo) |
| `staging` | dbt views | Typed, renamed 1:1 models (`stg_<source>__<entity>`) + seed `complaint_type_categories` |
| `intermediate` | dbt views | Enrichment and daily aggregation of 311 requests |
| `marts` | dbt tables | Certified facts/dims (Tier 1) and the district scorecard |
| `ops` | agents / app | `metadata_proposals`, `incidents`, `agent_runs` |

Every table is also a Dagster asset keyed `[schema, table]`; the daily job is `daily_refresh`.

## Domain notes
- `boro_cd` = borough code x 100 + community district number (Manhattan 1, Bronx 2,
  Brooklyn 3, Queens 4, Staten Island 5). 59 residential districts.
- 311 `community_board` values like '55 BROOKLYN' or '81 QUEENS' are Joint Interest
  Areas (parks, airports); 'Unspecified …' has no district. Both get a null `boro_cd`.
- Tonnage is in short tons. Diversion rate = (paper + MGP + organics) / total collected.
- 311 raw timestamps are New York wall-clock times stored as timestamptz-assumed-UTC;
  staging converts them back with `at time zone 'UTC'`.
- Monthly tonnage lags roughly one month; 311 data is refreshed daily.

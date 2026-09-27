-- Month x community district scorecard: how much each district throws away, how much
-- it diverts, and how well collection service performs relative to its size.
-- Only months covered by both tonnage and 311 data are included.

with tonnage as (

    select * from {{ ref('fct_monthly_tonnage') }}

),

requests as (

    select
        date_trunc('month', activity_date)::date    as month_start,
        boro_cd,
        sum(requests_total)                         as requests_total,
        sum(missed_collection_requests)             as missed_collection_requests,
        sum(collection_service_requests)            as collection_service_requests,
        sum(illegal_dumping_requests)               as illegal_dumping_requests
    from {{ ref('fct_district_daily_sanitation') }}
    group by 1, 2

),

districts as (

    select * from {{ ref('dim_community_district') }}

)

select
    tonnage.month_start,
    tonnage.boro_cd,
    districts.borough,
    districts.cd_name,
    districts.population_2010,
    tonnage.refuse_tons,
    tonnage.curbside_recycling_tons,
    tonnage.organics_tons,
    tonnage.total_collected_tons,
    tonnage.diversion_rate,
    requests.requests_total,
    requests.missed_collection_requests,
    requests.illegal_dumping_requests,
    round(requests.requests_total * 10000.0 / nullif(districts.population_2010, 0), 2)
                                                        as requests_per_10k_residents,
    round(requests.missed_collection_requests * 1000.0 / nullif(tonnage.refuse_tons, 0), 3)
                                                        as missed_collections_per_1k_refuse_tons,
    round(tonnage.total_collected_tons * 2000.0 / nullif(districts.population_2010, 0), 1)
                                                        as lbs_collected_per_resident

from tonnage
inner join requests
    on tonnage.month_start = requests.month_start
    and tonnage.boro_cd = requests.boro_cd
inner join districts
    on tonnage.boro_cd = districts.boro_cd

-- Daily request counts per residential community district, pivoted by category.

with requests as (

    select * from {{ ref('int_311__requests_enriched') }}
    where boro_cd is not null

)

select
    created_date,
    boro_cd,
    count(*)                                                                as requests_total,
    count(*) filter (where complaint_type = 'Missed Collection')            as missed_collection_requests,
    count(*) filter (where is_collection_service)                           as collection_service_requests,
    count(*) filter (where complaint_category = 'snow_and_ice')             as snow_and_ice_requests,
    count(*) filter (where complaint_category = 'illegal_dumping')          as illegal_dumping_requests,
    count(*) filter (where complaint_category = 'cleanliness')              as cleanliness_requests,
    count(*) filter (where complaint_category = 'derelict_vehicles')        as derelict_vehicle_requests,
    avg(resolution_hours)                                                   as avg_resolution_hours

from requests
group by created_date, boro_cd

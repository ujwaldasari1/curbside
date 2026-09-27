-- Day x community district grain: 311 sanitation demand alongside that day's weather.
-- Every district appears on every day (zero-filled), so averages are not biased by
-- quiet days.

with calendar as (

    select generate_series(
        (select min(created_date) from {{ ref('int_311__district_daily_counts') }}),
        (select max(created_date) from {{ ref('int_311__district_daily_counts') }}),
        interval '1 day'
    )::date as activity_date

),

spine as (

    select calendar.activity_date, districts.boro_cd
    from calendar
    cross join {{ ref('dim_community_district') }} as districts

),

counts as (

    select * from {{ ref('int_311__district_daily_counts') }}

),

weather as (

    select * from {{ ref('stg_weather__daily') }}

)

select
    spine.activity_date,
    spine.boro_cd,
    coalesce(counts.requests_total, 0)                  as requests_total,
    coalesce(counts.missed_collection_requests, 0)      as missed_collection_requests,
    coalesce(counts.collection_service_requests, 0)     as collection_service_requests,
    coalesce(counts.snow_and_ice_requests, 0)           as snow_and_ice_requests,
    coalesce(counts.illegal_dumping_requests, 0)        as illegal_dumping_requests,
    coalesce(counts.cleanliness_requests, 0)            as cleanliness_requests,
    coalesce(counts.derelict_vehicle_requests, 0)       as derelict_vehicle_requests,
    counts.avg_resolution_hours,
    weather.temp_max_c,
    weather.temp_min_c,
    weather.precipitation_mm,
    weather.snowfall_cm,
    weather.is_snow_day,
    weather.is_heavy_rain_day

from spine
left join counts
    on spine.activity_date = counts.created_date
    and spine.boro_cd = counts.boro_cd
left join weather
    on spine.activity_date = weather.weather_date

with source as (

    select * from {{ source('weather', 'weather_daily') }}

)

select
    date::date                                  as weather_date,
    temperature_2m_max::numeric                 as temp_max_c,
    temperature_2m_min::numeric                 as temp_min_c,
    precipitation_sum::numeric                  as precipitation_mm,
    snowfall_sum::numeric                       as snowfall_cm,
    wind_speed_10m_max::numeric                 as wind_max_kmh,
    coalesce(snowfall_sum::numeric, 0) >= 1     as is_snow_day,
    coalesce(precipitation_sum::numeric, 0) >= 20 as is_heavy_rain_day

from source

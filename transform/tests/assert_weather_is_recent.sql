-- The Open-Meteo archive lags about two days; a week without new weather means the
-- source or its load is stale, and weather columns in the daily mart go null.

select max(weather_date) as latest_weather_date
from {{ ref('stg_weather__daily') }}
having max(weather_date) < current_date - 7

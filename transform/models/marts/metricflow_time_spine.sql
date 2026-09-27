-- Daily time spine required by the dbt Semantic Layer (MetricFlow).
{{ config(materialized='table') }}

select day::date as date_day
from generate_series('2020-01-01'::date, '2030-12-31'::date, interval '1 day') as day

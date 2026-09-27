-- Each of the last 12 reported months should have tonnage for all 59 community
-- districts. A gap usually means the upstream dataset published a partial month.
-- Severity error: a partial month silently skews every per-district comparison.

with recent_months as (

    select month_start, count(distinct boro_cd) as districts_reported
    from {{ ref('fct_monthly_tonnage') }}
    where month_start > (select max(month_start) from {{ ref('fct_monthly_tonnage') }}) - interval '12 months'
    group by month_start

)

select *
from recent_months
where districts_reported <> 59

-- A district's refuse tonnage in the latest month should stay within 5x of its median
-- over the previous 6 months. A jump of ~2000x usually means the source switched from
-- tons to pounds; a collapse usually means a partial or mis-keyed load.

with ranked as (

    select
        boro_cd,
        month_start,
        refuse_tons,
        dense_rank() over (order by month_start desc) as months_back
    from {{ ref('fct_monthly_tonnage') }}

),

baseline as (

    select boro_cd, percentile_cont(0.5) within group (order by refuse_tons) as median_refuse_tons
    from ranked
    where months_back between 2 and 7
    group by boro_cd

)

select
    latest.boro_cd,
    latest.month_start,
    latest.refuse_tons,
    baseline.median_refuse_tons,
    round((latest.refuse_tons / nullif(baseline.median_refuse_tons, 0))::numeric, 2) as ratio
from ranked as latest
join baseline using (boro_cd)
where latest.months_back = 1
  and (latest.refuse_tons > 5 * baseline.median_refuse_tons
       or latest.refuse_tons < 0.2 * baseline.median_refuse_tons)

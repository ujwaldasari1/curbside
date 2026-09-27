-- NYC logs hundreds of missed-collection complaints every week. Zero in the last 7 days
-- of loaded data means the complaint type was renamed or dropped upstream, not that
-- service became perfect.

with recent as (

    select max(created_date) as latest_day
    from {{ ref('int_311__requests_enriched') }}

)

select recent.latest_day, count(requests.service_request_id) as missed_collections_last_7_days
from recent
left join {{ ref('int_311__requests_enriched') }} as requests
    on requests.created_date > recent.latest_day - 7
    and requests.complaint_type = 'Missed Collection'
group by recent.latest_day
having count(requests.service_request_id) = 0

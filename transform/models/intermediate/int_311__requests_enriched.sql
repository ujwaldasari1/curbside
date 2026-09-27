-- One row per DSNY 311 request, with complaint category, district validity and
-- resolution time. Requests outside the 59 residential community districts
-- (joint-interest areas such as parks/airports, or 'Unspecified') keep a null boro_cd.

with requests as (

    select * from {{ ref('stg_nyc311__service_requests') }}

),

categories as (

    select * from {{ ref('complaint_type_categories') }}

),

districts as (

    select boro_cd from {{ ref('stg_reference__community_districts') }}

)

select
    requests.service_request_id,
    requests.created_at,
    requests.created_at::date                                       as created_date,
    requests.closed_at,
    requests.resolution_updated_at,
    requests.source_updated_at,
    requests.status,
    requests.complaint_type,
    requests.descriptor,
    coalesce(categories.complaint_category, 'uncategorized')        as complaint_category,
    coalesce(categories.is_collection_service, false)               as is_collection_service,
    requests.intake_channel,
    requests.location_type,
    requests.borough,
    requests.community_board_raw,
    districts.boro_cd,
    case
        when districts.boro_cd is not null then 'residential_district'
        when requests.parsed_boro_cd is not null then 'joint_interest_area'
        else 'unspecified'
    end                                                             as district_type,
    requests.incident_zip,
    requests.incident_address,
    requests.street_name,
    requests.latitude,
    requests.longitude,
    requests.resolution_description,
    case
        when requests.closed_at >= requests.created_at
            then round(extract(epoch from requests.closed_at - requests.created_at) / 3600.0, 2)
    end                                                             as resolution_hours

from requests
left join categories
    on requests.complaint_type = categories.complaint_type
left join districts
    on requests.parsed_boro_cd = districts.boro_cd

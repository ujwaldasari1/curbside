-- Typed, renamed DSNY 311 requests.
--
-- Timestamps: Socrata publishes created/closed dates as New York wall-clock time with no
-- offset. dlt's ISO-timestamp detection stores them as timestamptz assuming UTC, so
-- `at time zone 'UTC'` recovers the original local wall-clock value exactly.
-- source_updated_at is a true UTC instant and stays timestamptz.

with source as (

    select * from {{ source('nyc311', 'service_requests') }}

)

select
    unique_key::bigint                                      as service_request_id,
    created_date at time zone 'UTC'                         as created_at,
    closed_date at time zone 'UTC'                          as closed_at,
    resolution_action_updated_date at time zone 'UTC'       as resolution_updated_at,
    source_updated_at,

    agency,
    complaint_type,
    descriptor,
    location_type,
    status,
    resolution_description,
    open_data_channel_type                                  as intake_channel,

    borough,
    community_board                                         as community_board_raw,
    -- '01 BRONX' -> 201. Placeholders like 'Unspecified QUEENS' / '0 Unspecified' -> null.
    case
        when community_board ~ '^[0-9]{2} '
            then {{ borough_code("substring(community_board from 4)") }} * 100
                 + left(community_board, 2)::int
    end                                                     as parsed_boro_cd,
    council_district,

    nullif(incident_zip, '')                                as incident_zip,
    incident_address,
    street_name,
    address_type,
    city,
    bbl,
    latitude::numeric(9, 6)                                 as latitude,
    longitude::numeric(9, 6)                                as longitude,

    _dlt_load_id                                            as dlt_load_id

from source

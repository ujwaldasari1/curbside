{{
    config(
        materialized='incremental',
        unique_key='service_request_id',
        incremental_strategy='merge',
        on_schema_change='append_new_columns',
    )
}}

-- One row per DSNY 311 service request. Incremental on the source system's update
-- timestamp so status changes (Open -> Closed) are merged into existing rows.

select *
from {{ ref('int_311__requests_enriched') }}

{% if is_incremental() %}
where source_updated_at > (select coalesce(max(source_updated_at), '1970-01-01') from {{ this }})
{% endif %}

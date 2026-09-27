with source as (

    select * from {{ source('dsny', 'monthly_tonnage') }}

)

select
    borough_id::int * 100 + communitydistrict::int              as boro_cd,
    to_date(replace(month, ' / ', '-') || '-01', 'YYYY-MM-DD')  as month_start,
    borough_id::int                                             as borough_code,
    borough,
    communitydistrict::int                                      as cd_number,

    refusetonscollected::numeric                                as refuse_tons,
    papertonscollected::numeric                                 as paper_tons,
    mgptonscollected::numeric                                   as mgp_tons,
    resorganicstons::numeric                                    as residential_organics_tons,
    schoolorganictons::numeric                                  as school_organics_tons,
    leavesorganictons::numeric                                  as leaf_organics_tons,
    xmastreetons::numeric                                       as christmas_tree_tons,
    otherorganicstons::numeric                                  as other_organics_tons,

    _dlt_load_id                                                as dlt_load_id

from source

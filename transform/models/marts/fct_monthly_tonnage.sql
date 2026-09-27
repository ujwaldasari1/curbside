-- Monthly DSNY curbside collection by community district and waste stream.
-- Organics columns are null when a program did not report that month; they are treated
-- as zero for totals so the diversion rate stays defined.

with tonnage as (

    select * from {{ ref('stg_dsny__monthly_tonnage') }}

),

streams as (

    select
        boro_cd,
        month_start,
        refuse_tons,
        paper_tons,
        mgp_tons,
        coalesce(residential_organics_tons, 0)
            + coalesce(school_organics_tons, 0)
            + coalesce(leaf_organics_tons, 0)
            + coalesce(christmas_tree_tons, 0)
            + coalesce(other_organics_tons, 0)          as organics_tons
    from tonnage

)

select
    boro_cd,
    month_start,
    refuse_tons,
    paper_tons,
    mgp_tons,
    organics_tons,
    paper_tons + mgp_tons                                   as curbside_recycling_tons,
    refuse_tons + paper_tons + mgp_tons + organics_tons     as total_collected_tons,
    round(
        (paper_tons + mgp_tons + organics_tons)
        / nullif(refuse_tons + paper_tons + mgp_tons + organics_tons, 0),
        4
    )                                                       as diversion_rate

from streams

with source as (

    select * from {{ source('reference', 'community_district_population') }}

)

select
    {{ borough_code('borough') }} * 100 + cd_number::int    as boro_cd,
    {{ borough_code('borough') }}                           as borough_code,
    borough,
    cd_number::int                                          as cd_number,
    cd_name,
    _2000_population::int                                   as population_2000,
    _2010_population::int                                   as population_2010

from source

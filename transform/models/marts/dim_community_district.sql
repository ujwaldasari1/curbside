select
    boro_cd,
    borough_code,
    borough,
    cd_number,
    cd_name,
    population_2000,
    population_2010

from {{ ref('stg_reference__community_districts') }}

-- One row per zip prefix.
--
-- the source holds 1,000,163 GPS points across only
-- 19,015 zip prefixes — roughly 53 rows per zip, because a postcode covers an
-- area. Joining the source directly on zip multiplies every joined row ~53x and
-- corrupts all downstream counts and sums.
--
-- This model collapses to one representative point per zip: averaged
-- coordinates, modal city and state. Points outside Brazil's bounding box are
-- excluded as clearly erroneous.

with source as (

    select
        geolocation_zip_code_prefix         as zip_prefix,
        try_to_double(geolocation_lat)      as latitude,
        try_to_double(geolocation_lng)      as longitude,
        lower(trim(geolocation_city))       as city,
        upper(trim(geolocation_state))      as state
    from {{ source('raw', 'raw_geolocation') }}

),

within_brazil as (

    select *
    from source
    where latitude  between -33.75 and  5.27
      and longitude between -73.99 and -34.79
      and zip_prefix is not null

),

final as (

    select
        zip_prefix,
        round(avg(latitude), 6)     as latitude,
        round(avg(longitude), 6)    as longitude,
        mode(city)                  as city,
        mode(state)                 as state,
        count(*)                    as source_point_count
    from within_brazil
    group by zip_prefix

)

select * from final

-- Seller dimension, enriched with coordinates for the geography analysis.
--
-- stg_geolocation is already one row per zip , so this join cannot
-- fan out.

with sellers as (

    select * from {{ ref('stg_sellers') }}

),

geo as (

    select * from {{ ref('stg_geolocation') }}

),

final as (

    select
        s.seller_id,
        s.seller_city,
        s.seller_state,
        s.zip_prefix,
        g.latitude,
        g.longitude
    from sellers s
    left join geo g on s.zip_prefix = g.zip_prefix

)

select * from final

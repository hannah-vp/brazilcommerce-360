-- One row per seller. Clean source: 3,095 rows, unique key, no missing values.
--
-- Note for the geography analysis: sellers span 23 states while customers span
-- 27, so four states have demand but no local supply.

with source as (

    select * from {{ source('raw', 'raw_sellers') }}

),

final as (

    select
        seller_id,
        seller_zip_code_prefix      as zip_prefix,
        lower(trim(seller_city))    as seller_city,
        upper(trim(seller_state))   as seller_state

    from source

)

select * from final

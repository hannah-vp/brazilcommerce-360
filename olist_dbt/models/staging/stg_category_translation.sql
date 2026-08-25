-- Portuguese to English product category lookup.
-- 71 rows covering 71 of the 73 categories present in raw_products.

with source as (

    select * from {{ source('raw', 'raw_product_category_translation') }}

),

final as (

    select
        lower(trim(product_category_name))          as category_name_pt,
        lower(trim(product_category_name_english))  as category_name_en

    from source

)

select * from final

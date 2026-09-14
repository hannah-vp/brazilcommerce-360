-- One row per product, with the English category name resolved.
--
-- two categories (pc_gamer,
-- portateis_cozinha_e_preparadores_de_alimentos) have no English translation,
-- and 610 products have no category at all. The coalesce below falls back to
-- the Portuguese name, then to 'unknown', so no product is dropped from
-- category analysis.
--
-- the source misspells "length" as "lenght" in two column
-- names. Corrected here; RAW keeps the original spelling.

with products as (

    select * from {{ source('raw', 'raw_products') }}

),

translation as (

    select * from {{ ref('stg_category_translation') }}

),

final as (

    select
        p.product_id,

        lower(trim(p.product_category_name))            as category_name_pt,
        coalesce(
            t.category_name_en,
            lower(trim(p.product_category_name)),
            'unknown'
        )                                               as category_name_en,

        try_to_number(p.product_name_lenght)            as product_name_length,
        try_to_number(p.product_description_lenght)     as product_description_length,
        try_to_number(p.product_photos_qty)             as product_photos_qty,

        try_to_number(p.product_weight_g)               as weight_g,
        try_to_number(p.product_length_cm)              as length_cm,
        try_to_number(p.product_height_cm)              as height_cm,
        try_to_number(p.product_width_cm)               as width_cm

    from products p
    left join translation t
        on lower(trim(p.product_category_name)) = t.category_name_pt

)

select * from final

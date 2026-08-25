-- Product dimension.

with products as (

    select * from {{ ref('stg_products') }}

),

final as (

    select
        product_id,
        category_name_en,
        category_name_pt,
        weight_g,
        length_cm,
        height_cm,
        width_cm,
        product_photos_qty,

        -- volumetric size: useful context for the freight-burden analysis
        length_cm * height_cm * width_cm as volume_cm3

    from products

)

select * from final

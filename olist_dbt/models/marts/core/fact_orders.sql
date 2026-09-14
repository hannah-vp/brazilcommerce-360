{{
    config(
        materialized = 'incremental',
        unique_key   = ['order_id', 'order_item_seq'],
        cluster_by   = ["date_trunc('month', purchased_at)"]
    )
}}

-- Core fact table.
--
-- GRAIN: one row per order item — (order_id, order_item_seq). This is the most
-- granular level available and preserves every relationship; aggregate up, never
-- disaggregate down. Because order_id repeats, order counts must use
-- count(distinct order_id) and order-level averages must aggregate to order
-- level first.
--
-- Incremental so that re-runs process only new orders rather than rebuilding
-- all 112,650 rows.

with items as (

    select * from {{ ref('stg_order_items') }}

),

orders as (

    select * from {{ ref('stg_orders') }}

),

products as (

    select * from {{ ref('stg_products') }}

),

final as (

    select
        -- keys
        i.order_id,
        i.order_item_seq,
        i.product_id,
        i.seller_id,
        o.customer_id,

        -- attributes
        p.category_name_en,
        o.order_status,

        -- dates
        o.purchased_at,
        o.delivered_at,
        o.estimated_delivery_at,

        -- delivery metrics
        o.delivery_days,
        o.days_vs_promise,
        o.is_late_vs_promise,

        -- money
        i.item_price,
        i.freight_value,
        i.item_total,

        -- freight as a share of item price: the margin lens
        case
            when i.item_price > 0
            then round(i.freight_value / i.item_price, 4)
        end as freight_ratio

    from items i
    inner join orders   o on i.order_id   = o.order_id
    inner join products p on i.product_id = p.product_id

    {% if is_incremental() %}
    where o.purchased_at > (select max(purchased_at) from {{ this }})
    {% endif %}

)

select * from final

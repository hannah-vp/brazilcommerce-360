-- One row per ITEM within an order.
--
-- GRAIN WARNING: this table holds 112,650 rows across
-- only 98,666 orders. order_id is NOT unique here. Anything counting orders
-- must use count(distinct order_id), and order-level averages must aggregate
-- to order level first. The composite key is (order_id, order_item_id).

with source as (

    select * from {{ source('raw', 'raw_order_items') }}

),

final as (

    select
        order_id,
        try_to_number(order_item_id)                                as order_item_seq,
        product_id,
        seller_id,

        try_to_timestamp(shipping_limit_date, 'YYYY-MM-DD HH24:MI:SS') as shipping_limit_at,

        try_to_decimal(price, 10, 2)                                as item_price,
        try_to_decimal(freight_value, 10, 2)                        as freight_value,
        try_to_decimal(price, 10, 2)
            + try_to_decimal(freight_value, 10, 2)                  as item_total

    from source

)

select * from final

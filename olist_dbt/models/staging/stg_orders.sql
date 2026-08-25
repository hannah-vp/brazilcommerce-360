-- One row per order. Casts the VARCHAR source columns and derives the
-- delivery metrics used throughout the marts.
--
-- Data quality note 2: delivery timestamps are NULL for orders that were never
-- delivered. Those NULLs are preserved rather than imputed; downstream models
-- filter on order_status instead.

with source as (

    select * from {{ source('raw', 'raw_orders') }}

),

renamed as (

    select
        order_id,
        customer_id,
        order_status,

        try_to_timestamp(order_purchase_timestamp,      'YYYY-MM-DD HH24:MI:SS') as purchased_at,
        try_to_timestamp(order_approved_at,             'YYYY-MM-DD HH24:MI:SS') as approved_at,
        try_to_timestamp(order_delivered_carrier_date,  'YYYY-MM-DD HH24:MI:SS') as shipped_at,
        try_to_timestamp(order_delivered_customer_date, 'YYYY-MM-DD HH24:MI:SS') as delivered_at,
        try_to_timestamp(order_estimated_delivery_date, 'YYYY-MM-DD HH24:MI:SS') as estimated_delivery_at

    from source

),

final as (

    select
        *,

        -- days from purchase to arrival; NULL when never delivered
        datediff('day', purchased_at, delivered_at) as delivery_days,

        -- positive = arrived early, negative = arrived late
        datediff('day', delivered_at, estimated_delivery_at) as days_vs_promise,

        case
            when delivered_at is null then null
            when delivered_at > estimated_delivery_at then true
            else false
        end as is_late_vs_promise

    from renamed

)

select * from final

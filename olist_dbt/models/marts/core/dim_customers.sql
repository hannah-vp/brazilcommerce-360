-- Customer dimension at PERSON grain.
--
-- Keyed on customer_unique_id, not customer_id (data quality note 4). Olist
-- issues a new customer_id per order, so keying on it would make every customer
-- look like a one-time buyer and report a repeat rate of zero.
--
-- Location is taken from the customer's most recent order, since a person may
-- appear with different addresses across orders.
--
-- Two different counts are deliberately kept:
--   lifetime_orders  — every order the person placed, from stg_orders.
--                      Used for retention: a cancelled order is still an order
--                      attempt, and excluding it would overstate the
--                      single-purchase rate.
--   lifetime_spend   — money actually spent, from fact_orders. Orders with no
--                      line items contribute nothing, which is correct.
--
-- Counting orders from fact_orders instead would drop 676 customers whose only
-- order had no items, so the two sources are not interchangeable.

with customers as (

    select * from {{ ref('stg_customers') }}

),

orders as (

    select * from {{ ref('stg_orders') }}

),

order_history as (

    select
        c.customer_unique_id,
        o.order_id,
        o.purchased_at,
        c.customer_city,
        c.customer_state,
        c.zip_prefix,
        row_number() over (
            partition by c.customer_unique_id
            order by o.purchased_at desc
        ) as recency_rank
    from customers c
    inner join orders o on c.customer_id = o.customer_id

),

-- every order placed, regardless of whether it had line items
order_counts as (

    select
        customer_unique_id,
        count(distinct order_id) as lifetime_orders
    from order_history
    group by customer_unique_id

),

-- money spent, which requires line items to exist
spend as (

    select
        c.customer_unique_id,
        sum(f.item_price) as lifetime_spend
    from {{ ref('fact_orders') }} f
    inner join customers c on f.customer_id = c.customer_id
    group by c.customer_unique_id

),

final as (

    select
        h.customer_unique_id,
        h.customer_city,
        h.customer_state,
        h.zip_prefix,

        coalesce(oc.lifetime_orders, 0)         as lifetime_orders,
        coalesce(s.lifetime_spend, 0)           as lifetime_spend,
        h.purchased_at                          as most_recent_order_at,

        case
            when coalesce(oc.lifetime_orders, 0) >= 2 then true
            else false
        end                                     as is_repeat_customer

    from order_history h
    left join order_counts oc on h.customer_unique_id = oc.customer_unique_id
    left join spend s         on h.customer_unique_id = s.customer_unique_id
    where h.recency_rank = 1

)

select * from final

-- FINDING 1: this is an acquisition business, not a retention one.
--
-- Grouped on customer_unique_id (the person), not customer_id (the order).
-- Using customer_id here would return a repeat rate of zero.

with customers as (

    select * from {{ ref('dim_customers') }}

),

bucketed as (

    select
        case
            when lifetime_orders = 1 then '1 order'
            when lifetime_orders = 2 then '2 orders'
            else '3+ orders'
        end                 as order_frequency,
        count(*)            as customers
    from customers
    where lifetime_orders > 0
    group by 1

)

select
    order_frequency,
    customers,
    round(customers * 100.0 / sum(customers) over (), 2) as pct_of_customers
from bucketed
order by order_frequency

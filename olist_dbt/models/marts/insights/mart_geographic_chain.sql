-- FINDING 5: geographic seller imbalance is the root cause.
--
-- Sellers cluster in Sao Paulo while customers are spread nationally, so
-- distant states wait longer and rate lower. This model puts supply, demand,
-- delivery time and satisfaction in one row per state so the chain is visible.
--
-- Deduplicated to order grain before joining reviews (note 3).

with delivered_orders as (

    select distinct
        f.order_id,
        f.customer_id,
        f.delivery_days,
        f.is_late_vs_promise
    from {{ ref('fact_orders') }} f
    where f.order_status = 'delivered'
      and f.delivery_days is not null

),

orders_by_state as (

    select
        c.customer_state            as state,
        o.order_id,
        o.delivery_days,
        o.is_late_vs_promise,
        r.review_score
    from delivered_orders o
    inner join {{ ref('stg_customers') }} c
        on o.customer_id = c.customer_id
    inner join {{ ref('stg_order_reviews') }} r
        on o.order_id = r.order_id

),

demand as (

    select customer_state as state, count(*) as customers
    from {{ ref('dim_customers') }}
    group by customer_state

),

supply as (

    select seller_state as state, count(*) as sellers
    from {{ ref('dim_sellers') }}
    group by seller_state

)

select
    o.state,
    count(distinct o.order_id)                          as orders,
    round(avg(o.delivery_days), 1)                      as avg_delivery_days,
    round(avg(o.review_score), 2)                       as avg_review_score,
    round(sum(case when o.is_late_vs_promise then 1 else 0 end)
          * 100.0 / count(*), 1)                        as pct_late_vs_promise,
    coalesce(d.customers, 0)                            as customers,
    coalesce(s.sellers, 0)                              as sellers
from orders_by_state o
left join demand d on o.state = d.state
left join supply s on o.state = s.state
group by o.state, d.customers, s.sellers
having count(distinct o.order_id) >= 50
order by avg_delivery_days desc

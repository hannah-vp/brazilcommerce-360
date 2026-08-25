-- Bad-review risk scoring, per order.
--
-- The Python model in analysis/risk_model.py learns the weights; this model
-- exposes the same features plus a transparent additive score that runs
-- entirely in the warehouse. Serving the score as SQL means the dashboard needs
-- no model artefact at query time.
--
-- Weights mirror the fitted model's ranking: lateness dominates, with slow
-- delivery and high freight burden as secondary signals.
--
-- Deduplicated to order grain first (note 3).

with order_level as (

    select
        order_id,
        max(delivery_days)                                  as delivery_days,
        max(case when is_late_vs_promise then 1 else 0 end) as is_late,
        greatest(-min(days_vs_promise), 0)                  as days_late,
        sum(item_price)                                     as order_price,
        sum(freight_value)                                  as order_freight
    from {{ ref('fact_orders') }}
    where order_status = 'delivered'
      and delivery_days is not null
    group by order_id

),

scored as (

    select
        *,
        case
            when order_price > 0
            then round(order_freight / order_price, 3)
        end as freight_ratio,

        -- additive risk score; lateness weighted heaviest
        (case when is_late = 1 then 3 else 0 end)
        + (case when delivery_days > 20 then 1 else 0 end)
        + (case when order_price > 0
                 and order_freight / order_price > 0.30 then 1 else 0 end)
        as risk_score

    from order_level

)

select
    order_id,
    delivery_days,
    is_late,
    days_late,
    freight_ratio,
    risk_score,
    case
        when risk_score >= 3 then 'Very High'
        when risk_score  = 2 then 'High'
        when risk_score  = 1 then 'Medium'
        else 'Low'
    end as risk_bucket
from scored

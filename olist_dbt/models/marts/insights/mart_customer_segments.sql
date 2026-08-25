-- Customer value segmentation (Pareto tiers).
--
-- Even though 97% of customers order only once, spend is highly concentrated:
-- the top decile drives a disproportionate share of revenue. That reframes
-- "no retention" into "concentrated value worth protecting".
--
-- Ranked on lifetime spend at PERSON grain (customer_unique_id).

with customers as (

    select *
    from {{ ref('dim_customers') }}
    where lifetime_spend > 0

),

ranked as (

    select
        customer_unique_id,
        lifetime_orders,
        lifetime_spend,
        percent_rank() over (order by lifetime_spend desc) as spend_rank_pct
    from customers

),

tiered as (

    select
        *,
        case
            when spend_rank_pct <= 0.01 then 'Top 1%'
            when spend_rank_pct <= 0.10 then 'Top 10%'
            when spend_rank_pct <= 0.50 then 'Next 40%'
            else 'Bottom 50%'
        end as value_tier
    from ranked

)

select
    value_tier,
    count(*)                                                    as customers,
    round(avg(lifetime_spend), 2)                               as avg_spend,
    round(sum(lifetime_spend), 0)                               as tier_revenue,
    round(sum(lifetime_spend) * 100.0
          / sum(sum(lifetime_spend)) over (), 1)                as pct_of_revenue,
    round(avg(lifetime_orders), 2)                              as avg_orders
from tiered
group by value_tier
order by
    case value_tier
        when 'Top 1%'     then 1
        when 'Top 10%'    then 2
        when 'Next 40%'   then 3
        else 4
    end

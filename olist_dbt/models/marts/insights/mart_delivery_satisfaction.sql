-- FINDING 2: delivery speed drives satisfaction, and missing the PROMISED date
-- matters more than raw speed.
--
-- Two lenses in one table so the dashboard can filter rather than query twice:
--   'speed'   — review score by actual delivery duration
--   'promise' — review score by whether the estimate was met
--
-- Restricted to delivered orders with a review. Deduplicated to order grain
-- first: fact_orders is order-item grain, so joining reviews directly would
-- count a multi-item order's review several times .

with delivered_orders as (

    select distinct
        f.order_id,
        f.delivery_days,
        f.is_late_vs_promise,
        f.days_vs_promise
    from {{ ref('fact_orders') }} f
    where f.order_status = 'delivered'
      and f.delivery_days is not null

),

with_reviews as (

    select
        o.order_id,
        o.delivery_days,
        o.is_late_vs_promise,
        o.days_vs_promise,
        r.review_score
    from delivered_orders o
    inner join {{ ref('stg_order_reviews') }} r
        on o.order_id = r.order_id

),

by_speed as (

    select
        'speed'                                 as lens,
        case
            when delivery_days <= 7  then '1-7 days'
            when delivery_days <= 14 then '8-14 days'
            when delivery_days <= 21 then '15-21 days'
            else '22+ days'
        end                                     as bucket,
        case
            when delivery_days <= 7  then 1
            when delivery_days <= 14 then 2
            when delivery_days <= 21 then 3
            else 4
        end                                     as bucket_order,
        count(*)                                as orders,
        round(avg(review_score), 2)             as avg_review_score,
        round(avg(delivery_days), 1)            as avg_delivery_days,
        round(sum(case when review_score <= 2 then 1 else 0 end)
              * 100.0 / count(*), 1)            as pct_bad_review
    from with_reviews
    group by 1, 2, 3

),

by_promise as (

    select
        'promise'                               as lens,
        case
            when is_late_vs_promise then 'Late vs promise'
            else 'On time or early'
        end                                     as bucket,
        case when is_late_vs_promise then 2 else 1 end as bucket_order,
        count(*)                                as orders,
        round(avg(review_score), 2)             as avg_review_score,
        round(avg(days_vs_promise), 1)          as avg_delivery_days,
        round(sum(case when review_score <= 2 then 1 else 0 end)
              * 100.0 / count(*), 1)            as pct_bad_review
    from with_reviews
    group by 1, 2, 3

)

select * from by_speed
union all
select * from by_promise

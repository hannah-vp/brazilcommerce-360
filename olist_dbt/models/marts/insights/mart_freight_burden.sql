-- FINDING 3: revenue rankings hide the margin picture.
--
-- Freight as a share of item price varies enormously by category, so two
-- categories with similar revenue can have very different economics.
--
-- Categories with fewer than 100 items are excluded — their averages are too
-- noisy to act on.

with items as (

    select * from {{ ref('fact_orders') }}
    where item_price > 0

)

select
    category_name_en,
    count(*)                                            as items_sold,
    count(distinct order_id)                            as orders,
    round(sum(item_price), 0)                           as total_revenue,
    round(avg(item_price), 2)                           as avg_item_price,
    round(avg(freight_value), 2)                        as avg_freight,
    round(avg(freight_value) / avg(item_price) * 100, 1) as freight_pct_of_price
from items
group by category_name_en
having count(*) >= 100
order by freight_pct_of_price desc

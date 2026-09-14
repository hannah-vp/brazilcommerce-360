-- Singular test: no order item may reference an order that does not exist.
--
-- Referential integrity between the two largest tables. Encoded as a test so
-- the check runs on every build rather than once.
--
-- dbt expects zero rows returned. Any row is a failure.

select
    i.order_id,
    i.order_item_seq
from {{ ref('stg_order_items') }} i
left join {{ ref('stg_orders') }} o
    on i.order_id = o.order_id
where o.order_id is null

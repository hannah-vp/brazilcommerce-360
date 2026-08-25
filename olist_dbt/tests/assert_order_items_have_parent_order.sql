-- Singular test: no order item may reference an order that does not exist.
--
-- This is the automated form of the orphan check run manually in Phase 2
-- (which returned 0). Encoding it here means the check runs on every build
-- rather than once.
--
-- dbt expects zero rows returned. Any row is a failure.

select
    i.order_id,
    i.order_item_seq
from {{ ref('stg_order_items') }} i
left join {{ ref('stg_orders') }} o
    on i.order_id = o.order_id
where o.order_id is null

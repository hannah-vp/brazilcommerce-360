-- Singular test: an order cannot be delivered before it was purchased.
--
-- Catches timestamp corruption that column-level tests would miss, because the
-- rule spans two columns.

select
    order_id,
    purchased_at,
    delivered_at
from {{ ref('stg_orders') }}
where delivered_at is not null
  and delivered_at < purchased_at

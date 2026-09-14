-- ============================================================
-- Targeted data quality checks.
--
-- Cross-table and value-level checks that single-table profiling cannot
-- answer: which specific values are invalid, which lookups are incomplete,
-- and whether foreign keys resolve.
--
-- Each finding below is enforced by a dbt test in the transformation layer,
-- so the check runs on every build rather than once.
-- ============================================================

USE WAREHOUSE ECOMMERCE_WH;
USE DATABASE ECOMMERCE_DEV;
USE SCHEMA RAW;


-- ------------------------------------------------------------
-- Q1. Payment type distribution.
--     Profiling reported 5 distinct values without naming them. One,
--     'not_defined' (3 rows), is a placeholder rather than a method.
--     Enforced downstream by an accepted_values test on stg_order_payments.
-- ------------------------------------------------------------
SELECT payment_type, COUNT(*) AS n
FROM raw_order_payments
GROUP BY payment_type
ORDER BY n DESC;


-- ------------------------------------------------------------
-- Q2. Order status distribution.
--     All 8 values are legitimate fulfilment stages. 96,478 of 99,441
--     orders are 'delivered', which reconciles with the 2,965 missing
--     delivery timestamps found during profiling.
--     Enforced downstream by an accepted_values test on stg_orders.
-- ------------------------------------------------------------
SELECT order_status, COUNT(*) AS n
FROM raw_orders
GROUP BY order_status
ORDER BY n DESC;


-- ------------------------------------------------------------
-- Q3. Product categories with no English translation.
--     Two: pc_gamer and portateis_cozinha_e_preparadores_de_alimentos.
--     stg_products falls back to the Portuguese name, then 'unknown',
--     so no product is dropped from category analysis.
-- ------------------------------------------------------------
SELECT DISTINCT p.product_category_name
FROM raw_products p
LEFT JOIN raw_product_category_translation t
       ON p.product_category_name = t.product_category_name
WHERE t.product_category_name IS NULL
  AND p.product_category_name IS NOT NULL;


-- ------------------------------------------------------------
-- Q4. Referential integrity: order_items to orders.
--     Returns 0 — every item resolves to a parent order.
--     Enforced downstream by a relationships test on stg_order_items.
-- ------------------------------------------------------------
SELECT COUNT(*) AS orphan_items
FROM raw_order_items i
LEFT JOIN raw_orders o ON i.order_id = o.order_id
WHERE o.order_id IS NULL;
-- Result: 0 orphans.


-- ------------------------------------------------------------
-- Q5. Type validity.
--     RAW is all VARCHAR, so nothing enforced format at load time. All
--     prices, freight values and timestamps parse cleanly.
--     Enforced downstream by dbt_expectations range tests in staging.
-- ------------------------------------------------------------
SELECT
  SUM(CASE WHEN price IS NOT NULL
            AND TRY_TO_DECIMAL(price, 10, 2) IS NULL
           THEN 1 ELSE 0 END)                       AS bad_price,
  SUM(CASE WHEN freight_value IS NOT NULL
            AND TRY_TO_DECIMAL(freight_value, 10, 2) IS NULL
           THEN 1 ELSE 0 END)                       AS bad_freight
FROM raw_order_items;

SELECT
  SUM(CASE WHEN order_purchase_timestamp IS NOT NULL
            AND TRY_TO_TIMESTAMP(order_purchase_timestamp,
                                 'YYYY-MM-DD HH24:MI:SS') IS NULL
           THEN 1 ELSE 0 END)                       AS bad_purchase_ts,
  SUM(CASE WHEN order_delivered_customer_date IS NOT NULL
            AND TRY_TO_TIMESTAMP(order_delivered_customer_date,
                                 'YYYY-MM-DD HH24:MI:SS') IS NULL
           THEN 1 ELSE 0 END)                       AS bad_delivered_ts
FROM raw_orders;
-- Result: 0 unparseable values across all four columns.


-- ------------------------------------------------------------
-- Q6. Reviews created before delivery.
--     8,320 of 99,224. Not a defect: Olist requests the review at
--     dispatch rather than on arrival, so a customer can respond before
--     the parcel lands. Documented rather than filtered — the rows are
--     valid and reflect real behaviour.
-- ------------------------------------------------------------
SELECT COUNT(*) AS reviews_before_delivery
FROM raw_order_reviews r
JOIN raw_orders o ON r.order_id = o.order_id
WHERE TRY_TO_TIMESTAMP(r.review_creation_date, 'YYYY-MM-DD HH24:MI:SS')
    < TRY_TO_TIMESTAMP(o.order_delivered_customer_date, 'YYYY-MM-DD HH24:MI:SS');


-- ------------------------------------------------------------
-- Q7. Duplicate review keys.
--     814 review_id values appear more than once, some three times,
--     despite review_id being the intended primary key. stg_order_reviews
--     keeps the most recent row per key via ROW_NUMBER.
-- ------------------------------------------------------------
SELECT review_id, COUNT(*) AS n
FROM raw_order_reviews
GROUP BY review_id
HAVING COUNT(*) > 1
ORDER BY n DESC
LIMIT 10;

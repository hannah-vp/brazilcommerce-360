-- ============================================================
-- Source column profiling.
--
-- One counting query per source table, recording row counts, key
-- cardinality and completeness. The automated profiler in
-- docs/profiling/ covers the same ground; these queries make the
-- comparisons explicit, which is where the findings came from — the
-- profiler reports each column in isolation and never compares them.
--
-- RAW column names are uppercase and blanks load as SQL NULL, so
-- COUNT(col) behaves as expected and no quoted identifiers are needed.
--
-- Three patterns treated as findings:
--   1. primary key distinct count < row count      -> duplicates
--   2. same missing count across several columns   -> one systemic cause
--   3. low distinct count on a join key            -> fan-out risk
-- ============================================================

USE WAREHOUSE ECOMMERCE_WH;
USE DATABASE ECOMMERCE_DEV;
USE SCHEMA RAW;


-- ------------------------------------------------------------
-- 1. raw_orders
-- ------------------------------------------------------------
SELECT
  COUNT(*)                                            AS n_rows,
  COUNT(DISTINCT order_id)                            AS d_order_id,
  COUNT(DISTINCT customer_id)                         AS d_customer_id,
  COUNT(DISTINCT order_status)                        AS d_status,
  COUNT(*) - COUNT(order_approved_at)                 AS miss_approved,
  COUNT(*) - COUNT(order_delivered_carrier_date)      AS miss_carrier,
  COUNT(*) - COUNT(order_delivered_customer_date)     AS miss_delivered,
  COUNT(*) - COUNT(order_estimated_delivery_date)     AS miss_estimated
FROM raw_orders;
-- 99,441 rows | order_id 100% distinct -> clean PK
-- missing rises 160 -> 1,783 -> 2,965 along the fulfilment chain.
-- Pattern 2, but legitimate: an undelivered order has no delivery date.


-- ------------------------------------------------------------
-- 2. raw_order_items
-- ------------------------------------------------------------
SELECT
  COUNT(*)                        AS n_rows,
  COUNT(DISTINCT order_id)        AS d_order_id,
  COUNT(DISTINCT order_item_id)   AS d_item_seq,
  COUNT(DISTINCT product_id)      AS d_product_id,
  COUNT(DISTINCT seller_id)       AS d_seller_id,
  COUNT(*) - COUNT(price)         AS miss_price,
  COUNT(*) - COUNT(freight_value) AS miss_freight
FROM raw_order_items;
-- 112,650 rows but only 98,666 distinct order_id.
-- The grain is one row per ORDER ITEM, not per order.
-- Consequence: COUNT(*) overstates orders by ~14%.


-- ------------------------------------------------------------
-- 3. raw_customers
-- ------------------------------------------------------------
SELECT
  COUNT(*)                                  AS n_rows,
  COUNT(DISTINCT customer_id)               AS d_customer_id,
  COUNT(DISTINCT customer_unique_id)        AS d_person,
  COUNT(DISTINCT customer_zip_code_prefix)  AS d_zip,
  COUNT(DISTINCT customer_city)             AS d_city,
  COUNT(DISTINCT customer_state)            AS d_state
FROM raw_customers;
-- 99,441 customer_id vs 96,096 customer_unique_id.
-- customer_id is issued per order; customer_unique_id identifies the person.
-- 3,345 orders came from someone who had ordered before.


-- ------------------------------------------------------------
-- 4. raw_products
-- ------------------------------------------------------------
SELECT
  COUNT(*)                                  AS n_rows,
  COUNT(DISTINCT product_id)                AS d_product_id,
  COUNT(DISTINCT product_category_name)     AS d_category,
  COUNT(*) - COUNT(product_category_name)   AS miss_category,
  COUNT(*) - COUNT(product_name_lenght)     AS miss_name_len,
  COUNT(*) - COUNT(product_photos_qty)      AS miss_photos,
  COUNT(*) - COUNT(product_weight_g)        AS miss_weight
FROM raw_products;
-- 610 missing repeated across three columns -> one block of incomplete
-- product records, not random loss. Pattern 2.
-- Note the source misspelling: product_name_lenght.


-- ------------------------------------------------------------
-- 5. raw_sellers
-- ------------------------------------------------------------
SELECT
  COUNT(*)                                  AS n_rows,
  COUNT(DISTINCT seller_id)                 AS d_seller_id,
  COUNT(DISTINCT seller_zip_code_prefix)    AS d_zip,
  COUNT(DISTINCT seller_city)               AS d_city,
  COUNT(DISTINCT seller_state)              AS d_state
FROM raw_sellers;
-- 3,095 rows, clean PK, no missing values. No follow-up.
-- Note: 23 seller states vs 27 customer states -> four states have
-- customers but no local sellers. Business finding, not a defect.


-- ------------------------------------------------------------
-- 6. raw_order_payments
-- ------------------------------------------------------------
SELECT
  COUNT(*)                                AS n_rows,
  COUNT(DISTINCT order_id)                AS d_order_id,
  COUNT(DISTINCT payment_type)            AS d_payment_type,
  COUNT(DISTINCT payment_installments)    AS d_installments,
  COUNT(*) - COUNT(payment_value)         AS miss_value
FROM raw_order_payments;
-- 103,886 rows vs 99,440 orders -> split payments produce multiple rows.
-- payment_type has only 5 values, so enumerate them in 02_final_checks.
-- 99,440 here vs 99,441 in raw_orders -> one order has no payment record.


-- ------------------------------------------------------------
-- 7. raw_order_reviews
-- ------------------------------------------------------------
SELECT
  COUNT(*)                                    AS n_rows,
  COUNT(DISTINCT review_id)                   AS d_review_id,
  COUNT(*) - COUNT(DISTINCT review_id)        AS duplicate_review_ids,
  COUNT(DISTINCT order_id)                    AS d_order_id,
  COUNT(DISTINCT review_score)                AS d_score,
  COUNT(*) - COUNT(review_comment_title)      AS miss_title,
  COUNT(*) - COUNT(review_comment_message)    AS miss_message
FROM raw_order_reviews;
-- review_id should be unique but 814 duplicates exist. Pattern 1.
-- Comment columns are ~88% / ~59% missing: optional free text, expected.


-- ------------------------------------------------------------
-- 8. raw_geolocation
-- ------------------------------------------------------------
SELECT
  COUNT(*)                                          AS n_rows,
  COUNT(DISTINCT geolocation_zip_code_prefix)       AS d_zip,
  ROUND(COUNT(*) / COUNT(DISTINCT geolocation_zip_code_prefix), 1)
                                                    AS rows_per_zip,
  COUNT(DISTINCT geolocation_city)                  AS d_city,
  COUNT(DISTINCT geolocation_state)                 AS d_state
FROM raw_geolocation;
-- 1,000,163 rows across 19,015 zips = ~53 rows per zip. Pattern 3.
-- Joining this on zip without de-duplicating multiplies every joined row.
-- 8,011 city spellings vs 4,119 in raw_customers -> spelling variants.


-- ------------------------------------------------------------
-- 9. raw_product_category_translation
-- ------------------------------------------------------------
SELECT
  COUNT(*)                                        AS n_rows,
  COUNT(DISTINCT product_category_name)           AS d_pt,
  COUNT(DISTINCT product_category_name_english)   AS d_en
FROM raw_product_category_translation;
-- 71 rows, clean one-to-one mapping.
-- But raw_products holds 73 distinct categories -> 2 have no translation.
-- Identify them in 02_final_checks.

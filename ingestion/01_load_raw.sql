-- ============================================================
-- BrazilCommerce 360 — Phase 1 ingestion (pure-SQL alternative)
-- Use this if you'd rather not run the Python script.
-- Upload the CSVs via the Snowsight UI first (see walkthrough step 3),
-- then run this file.
-- ============================================================

USE WAREHOUSE ECOMMERCE_WH;
USE DATABASE ECOMMERCE;
USE SCHEMA RAW;

-- 1. File format: how to read the CSVs ------------------------
CREATE OR REPLACE FILE FORMAT olist_csv_format
  TYPE = 'CSV'
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'   -- handle quoted fields like "São Paulo"
  SKIP_HEADER = 1                       -- skip the column-name row
  NULL_IF = ('', 'NULL')
  EMPTY_FIELD_AS_NULL = TRUE;

-- 2. Internal stage: the upload area --------------------------
CREATE OR REPLACE STAGE olist_stage
  FILE_FORMAT = olist_csv_format;

-- >>> Now upload all 9 CSVs into OLIST_STAGE via the Snowsight UI:
--     Data > Databases > ECOMMERCE > RAW > Stages > OLIST_STAGE > + Files
--     Then confirm:
LIST @olist_stage;

-- 3. Create tables (all VARCHAR to stay source-faithful) ------
CREATE OR REPLACE TABLE raw_orders (
  order_id VARCHAR, customer_id VARCHAR, order_status VARCHAR,
  order_purchase_timestamp VARCHAR, order_approved_at VARCHAR,
  order_delivered_carrier_date VARCHAR, order_delivered_customer_date VARCHAR,
  order_estimated_delivery_date VARCHAR);

CREATE OR REPLACE TABLE raw_order_items (
  order_id VARCHAR, order_item_id VARCHAR, product_id VARCHAR, seller_id VARCHAR,
  shipping_limit_date VARCHAR, price VARCHAR, freight_value VARCHAR);

CREATE OR REPLACE TABLE raw_customers (
  customer_id VARCHAR, customer_unique_id VARCHAR, customer_zip_code_prefix VARCHAR,
  customer_city VARCHAR, customer_state VARCHAR);

CREATE OR REPLACE TABLE raw_products (
  product_id VARCHAR, product_category_name VARCHAR, product_name_lenght VARCHAR,
  product_description_lenght VARCHAR, product_photos_qty VARCHAR, product_weight_g VARCHAR,
  product_length_cm VARCHAR, product_height_cm VARCHAR, product_width_cm VARCHAR);

CREATE OR REPLACE TABLE raw_sellers (
  seller_id VARCHAR, seller_zip_code_prefix VARCHAR, seller_city VARCHAR, seller_state VARCHAR);

CREATE OR REPLACE TABLE raw_order_payments (
  order_id VARCHAR, payment_sequential VARCHAR, payment_type VARCHAR,
  payment_installments VARCHAR, payment_value VARCHAR);

CREATE OR REPLACE TABLE raw_order_reviews (
  review_id VARCHAR, order_id VARCHAR, review_score VARCHAR, review_comment_title VARCHAR,
  review_comment_message VARCHAR, review_creation_date VARCHAR, review_answer_timestamp VARCHAR);

CREATE OR REPLACE TABLE raw_geolocation (
  geolocation_zip_code_prefix VARCHAR, geolocation_lat VARCHAR, geolocation_lng VARCHAR,
  geolocation_city VARCHAR, geolocation_state VARCHAR);

CREATE OR REPLACE TABLE raw_product_category_translation (
  product_category_name VARCHAR, product_category_name_english VARCHAR);

-- 4. Load each table with COPY INTO ---------------------------
COPY INTO raw_orders FROM @olist_stage/olist_orders_dataset.csv ON_ERROR='CONTINUE';
COPY INTO raw_order_items FROM @olist_stage/olist_order_items_dataset.csv ON_ERROR='CONTINUE';
COPY INTO raw_customers FROM @olist_stage/olist_customers_dataset.csv ON_ERROR='CONTINUE';
COPY INTO raw_products FROM @olist_stage/olist_products_dataset.csv ON_ERROR='CONTINUE';
COPY INTO raw_sellers FROM @olist_stage/olist_sellers_dataset.csv ON_ERROR='CONTINUE';
COPY INTO raw_order_payments FROM @olist_stage/olist_order_payments_dataset.csv ON_ERROR='CONTINUE';
COPY INTO raw_order_reviews FROM @olist_stage/olist_order_reviews_dataset.csv ON_ERROR='CONTINUE';
COPY INTO raw_geolocation FROM @olist_stage/olist_geolocation_dataset.csv ON_ERROR='CONTINUE';
COPY INTO raw_product_category_translation FROM @olist_stage/product_category_name_translation.csv ON_ERROR='CONTINUE';

-- 5. Verify row counts ----------------------------------------
SELECT 'raw_orders' t, COUNT(*) n FROM raw_orders
UNION ALL SELECT 'raw_order_items', COUNT(*) FROM raw_order_items
UNION ALL SELECT 'raw_customers', COUNT(*) FROM raw_customers
UNION ALL SELECT 'raw_products', COUNT(*) FROM raw_products
UNION ALL SELECT 'raw_sellers', COUNT(*) FROM raw_sellers
UNION ALL SELECT 'raw_order_payments', COUNT(*) FROM raw_order_payments
UNION ALL SELECT 'raw_order_reviews', COUNT(*) FROM raw_order_reviews
UNION ALL SELECT 'raw_geolocation', COUNT(*) FROM raw_geolocation
UNION ALL SELECT 'raw_product_category_translation', COUNT(*) FROM raw_product_category_translation
ORDER BY n DESC;

-- Expected (largest to smallest):
--   raw_geolocation                    1,000,163
--   raw_order_items                      112,650
--   raw_order_payments                   103,886
--   raw_orders                            99,441
--   raw_customers                         99,441
--   raw_order_reviews                     99,224
--   raw_products                          32,951
--   raw_sellers                            3,095
--   raw_product_category_translation          71

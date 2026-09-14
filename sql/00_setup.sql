-- ============================================================
-- BrazilCommerce 360 — environment setup
--
-- Creates the compute, storage and cost-control objects the pipeline
-- depends on. Idempotent: safe to re-run.
-- ============================================================

-- 1. Compute engine (warehouse) --------------------------------
--    X-Small sized, auto-suspending after 60s idle so compute is only
--    billed while queries run. Created suspended.
CREATE WAREHOUSE IF NOT EXISTS ECOMMERCE_WH
  WAREHOUSE_SIZE = 'X-SMALL'
  AUTO_SUSPEND   = 60
  AUTO_RESUME    = TRUE
  INITIALLY_SUSPENDED = TRUE;

-- 2. Database + the three medallion layers ---------------------
CREATE DATABASE IF NOT EXISTS ECOMMERCE;
USE DATABASE ECOMMERCE;

CREATE SCHEMA IF NOT EXISTS RAW;      -- untouched source data (audit trail)
CREATE SCHEMA IF NOT EXISTS STAGING;  -- cleaned + typed
CREATE SCHEMA IF NOT EXISTS MART;     -- business-ready facts, dims, insights

-- 3. Time Travel -----------------------------------------------
--    7 days of history, allowing any table to be queried or restored
--    as it stood at an earlier point.
ALTER DATABASE ECOMMERCE
  SET DATA_RETENTION_TIME_IN_DAYS = 7;

-- 4. Cost guardrail --------------------------------------------
--    Caps usage at 5 credits/day, notifying at 80% and suspending the
--    warehouse at 100%. Requires ACCOUNTADMIN.
USE ROLE ACCOUNTADMIN;

CREATE RESOURCE MONITOR IF NOT EXISTS ecommerce_monitor
  WITH
    CREDIT_QUOTA = 5
    FREQUENCY = 'DAILY'
    START_TIMESTAMP = 'IMMEDIATELY'
    TRIGGERS
      ON 80 PERCENT DO NOTIFY
      ON 100 PERCENT DO SUSPEND;

ALTER WAREHOUSE ECOMMERCE_WH
  SET RESOURCE_MONITOR = ecommerce_monitor;

USE ROLE SYSADMIN;

-- 5. Verification ----------------------------------------------
SHOW WAREHOUSES LIKE 'ECOMMERCE_WH';
SHOW SCHEMAS IN DATABASE ECOMMERCE;
SHOW RESOURCE MONITORS;

-- Returns 1 warehouse, 3 schemas (RAW, STAGING, MART) alongside the
-- Snowflake defaults, and 1 resource monitor.

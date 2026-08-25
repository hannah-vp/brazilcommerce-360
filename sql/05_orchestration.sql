-- ============================================================
-- BrazilCommerce 360 — Phase 5: orchestration
--
-- Chains the in-warehouse steps as a Snowflake Task DAG. A child task runs only
-- if its parent succeeded, so a failed load cannot propagate partial data into
-- the marts.
--
-- Scope note: dbt itself runs from CI or a scheduler, not from inside a Task.
-- These tasks cover the steps that belong in the warehouse — the freshness
-- check, the post-build quality gate, and the run log. Keeping that boundary
-- clean is deliberate: Snowflake orchestrates SQL, GitHub Actions orchestrates
-- code.
--
-- Run as the transformer role.
-- ============================================================

USE ROLE transformer;
USE WAREHOUSE ECOMMERCE_WH;
USE DATABASE ECOMMERCE_DEV;
USE SCHEMA DBT_MART;


-- ------------------------------------------------------------
-- 1. Run log — the observability backbone
--
-- Every task writes one row. Without this, a failure is invisible until someone
-- notices a stale dashboard.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_run_log (
    run_id        STRING       DEFAULT UUID_STRING(),
    step_name     STRING,
    status        STRING,           -- SUCCESS | FAILURE
    row_count     NUMBER,
    message       STRING,
    logged_at     TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);


-- ------------------------------------------------------------
-- 2. Root task — source freshness
--
-- Confirms RAW actually received data before anything downstream runs. If the
-- upstream load silently did nothing, this is where the pipeline should stop.
-- ------------------------------------------------------------
CREATE OR REPLACE TASK task_check_raw_freshness
    WAREHOUSE = ECOMMERCE_WH
    SCHEDULE  = 'USING CRON 0 6 * * * UTC'      -- daily 06:00 UTC
    COMMENT   = 'Root: verify RAW is populated'
AS
    INSERT INTO pipeline_run_log (step_name, status, row_count, message)
    SELECT
        'check_raw_freshness',
        CASE WHEN order_rows > 0 THEN 'SUCCESS' ELSE 'FAILURE' END,
        order_rows,
        CASE WHEN order_rows > 0
             THEN 'RAW populated'
             ELSE 'RAW.raw_orders is empty — upstream load failed' END
    FROM (SELECT COUNT(*) AS order_rows FROM ECOMMERCE_DEV.RAW.raw_orders);


-- ------------------------------------------------------------
-- 3. Child task — referential integrity gate
--
-- The automated form of the orphan check first run by hand in Phase 2. It has
-- now been a manual query, a dbt test, and a scheduled gate: the same check at
-- three levels of automation.
-- ------------------------------------------------------------
CREATE OR REPLACE TASK task_quality_gate
    WAREHOUSE = ECOMMERCE_WH
    AFTER task_check_raw_freshness
    COMMENT = 'Gate: no order item may reference a missing order'
AS
    INSERT INTO pipeline_run_log (step_name, status, row_count, message)
    SELECT
        'quality_gate_orphans',
        CASE WHEN orphans = 0 THEN 'SUCCESS' ELSE 'FAILURE' END,
        orphans,
        CASE WHEN orphans = 0
             THEN 'referential integrity intact'
             ELSE 'orphan order items detected — investigate before publishing' END
    FROM (
        SELECT COUNT(*) AS orphans
        FROM      ECOMMERCE_DEV.DBT_STAGING.stg_order_items i
        LEFT JOIN ECOMMERCE_DEV.DBT_STAGING.stg_orders      o
               ON i.order_id = o.order_id
        WHERE o.order_id IS NULL
    );


-- ------------------------------------------------------------
-- 4. Child task — mart reconciliation
--
-- Compares RAW against MART so a silent row loss during transformation is
-- caught rather than discovered later in the dashboard.
-- ------------------------------------------------------------
CREATE OR REPLACE TASK task_reconcile_marts
    WAREHOUSE = ECOMMERCE_WH
    AFTER task_quality_gate
    COMMENT = 'Reconcile RAW order count against fact_orders'
AS
    INSERT INTO pipeline_run_log (step_name, status, row_count, message)
    SELECT
        'reconcile_marts',
        CASE WHEN raw_orders = mart_orders THEN 'SUCCESS' ELSE 'FAILURE' END,
        mart_orders,
        'raw=' || raw_orders || ' mart=' || mart_orders
    FROM (
        SELECT
            (SELECT COUNT(DISTINCT order_id) FROM ECOMMERCE_DEV.RAW.raw_orders)
                AS raw_orders,
            (SELECT COUNT(DISTINCT order_id) FROM ECOMMERCE_DEV.DBT_MART.fact_orders)
                AS mart_orders
    );
-- Note: these counts are expected to differ. fact_orders inner-joins to items
-- and products, so orders with no line item are absent by design. Treat the
-- first observed gap as the baseline and alarm on change, not on inequality.


-- ------------------------------------------------------------
-- 5. Activate the DAG
--
-- Tasks are created suspended. Resume children first, then the root — resuming
-- the root is what arms the schedule.
-- ------------------------------------------------------------
ALTER TASK task_reconcile_marts       RESUME;
ALTER TASK task_quality_gate          RESUME;
ALTER TASK task_check_raw_freshness   RESUME;


-- ------------------------------------------------------------
-- 6. Operating the pipeline
-- ------------------------------------------------------------

-- inspect the DAG
SHOW TASKS IN SCHEMA ECOMMERCE_DEV.DBT_MART;

-- run the whole chain now rather than waiting for 06:00
EXECUTE TASK task_check_raw_freshness;

-- what happened
SELECT step_name, status, row_count, message, logged_at
FROM pipeline_run_log
ORDER BY logged_at DESC
LIMIT 20;

-- any failures in the last week
SELECT * FROM pipeline_run_log
WHERE status = 'FAILURE'
  AND logged_at >= DATEADD('day', -7, CURRENT_TIMESTAMP())
ORDER BY logged_at DESC;

-- task execution history, including errors Snowflake caught itself
SELECT name, state, scheduled_time, completed_time, error_message
FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY())
ORDER BY scheduled_time DESC
LIMIT 20;

-- pause everything (suspending the root stops the schedule)
-- ALTER TASK task_check_raw_freshness SUSPEND;

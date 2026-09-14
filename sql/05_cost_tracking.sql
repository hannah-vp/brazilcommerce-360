-- ============================================================
-- Warehouse cost observability.
--
-- A pipeline's own cost should be a monitored metric, not a surprise at the end
-- of the month. These queries expose credit consumption and the queries driving
-- it.
--
-- ACCOUNT_USAGE views require ACCOUNTADMIN and lag by up to ~45 minutes, but
-- retain a year of history. For real-time figures use INFORMATION_SCHEMA
-- instead — the final query below shows that variant.
-- ============================================================

USE ROLE ACCOUNTADMIN;


-- ------------------------------------------------------------
-- 1. Daily credit consumption, last 30 days
--    Credit price varies by edition and region; 3.00 is the Standard-edition
--    list rate used here as an approximation.
-- ------------------------------------------------------------
SELECT
    DATE_TRUNC('day', start_time)           AS usage_day,
    warehouse_name,
    ROUND(SUM(credits_used), 4)             AS credits,
    ROUND(SUM(credits_used) * 3.00, 2)      AS approx_usd
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'ECOMMERCE_WH'
  AND start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2
ORDER BY usage_day DESC;


-- ------------------------------------------------------------
-- 2. Project total to date
--    The number to quote when asked what the project cost to build.
-- ------------------------------------------------------------
SELECT
    ROUND(SUM(credits_used), 3)             AS total_credits,
    ROUND(SUM(credits_used) * 3.00, 2)      AS approx_total_usd,
    MIN(start_time)::DATE                   AS first_activity,
    MAX(start_time)::DATE                   AS last_activity
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'ECOMMERCE_WH';


-- ------------------------------------------------------------
-- 3. Most expensive queries, last 7 days
--    Where to look first when a bill moves. Elapsed time is the practical
--    proxy for cost on a single-warehouse setup.
-- ------------------------------------------------------------
SELECT
    LEFT(query_text, 90)                        AS query_preview,
    ROUND(total_elapsed_time / 1000, 1)         AS seconds,
    ROUND(bytes_scanned / POWER(1024, 3), 3)    AS gb_scanned,
    rows_produced,
    user_name,
    start_time
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE warehouse_name = 'ECOMMERCE_WH'
  AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
  AND total_elapsed_time > 1000                 -- ignore sub-second queries
ORDER BY total_elapsed_time DESC
LIMIT 20;


-- ------------------------------------------------------------
-- 4. Storage by table
--    Storage is a small share of cost here, but worth confirming that
--    raw_geolocation — the largest table — is not growing unexpectedly.
-- ------------------------------------------------------------
SELECT
    table_schema,
    table_name,
    ROUND(active_bytes  / POWER(1024, 2), 1)    AS active_mb,
    ROUND(time_travel_bytes / POWER(1024, 2), 1) AS time_travel_mb,
    ROUND(failsafe_bytes / POWER(1024, 2), 1)   AS failsafe_mb
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
WHERE table_catalog = 'ECOMMERCE_DEV'
  AND deleted = FALSE
ORDER BY active_bytes DESC
LIMIT 20;


-- ------------------------------------------------------------
-- 5. Real-time variant — no ACCOUNTADMIN, no lag
--    Useful mid-session to see what the current warehouse is doing.
-- ------------------------------------------------------------
USE ROLE transformer;

SELECT
    query_id,
    LEFT(query_text, 80)                    AS query_preview,
    ROUND(total_elapsed_time / 1000, 1)     AS seconds,
    execution_status
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(
    WAREHOUSE_NAME => 'ECOMMERCE_WH',
    END_TIME_RANGE_START => DATEADD('hour', -24, CURRENT_TIMESTAMP())
))
ORDER BY total_elapsed_time DESC
LIMIT 20;

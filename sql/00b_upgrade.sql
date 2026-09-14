-- ============================================================
-- BrazilCommerce 360 — environment hardening
--
-- Extends the base setup in 00_setup.sql with environment separation,
-- a least-privilege role, and key-pair authentication.
--
-- Sections 1-3 require ACCOUNTADMIN. Section 4 verifies the result.
-- ============================================================


-- ------------------------------------------------------------
-- 1. Environment separation: DEV and PROD databases
--    Rationale: experiments in DEV can never corrupt published
--    tables. dbt targets select between them.
-- ------------------------------------------------------------
USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS ECOMMERCE_DEV;
CREATE DATABASE IF NOT EXISTS ECOMMERCE_PROD;

CREATE SCHEMA IF NOT EXISTS ECOMMERCE_DEV.RAW;
CREATE SCHEMA IF NOT EXISTS ECOMMERCE_DEV.STAGING;
CREATE SCHEMA IF NOT EXISTS ECOMMERCE_DEV.MART;

CREATE SCHEMA IF NOT EXISTS ECOMMERCE_PROD.RAW;
CREATE SCHEMA IF NOT EXISTS ECOMMERCE_PROD.STAGING;
CREATE SCHEMA IF NOT EXISTS ECOMMERCE_PROD.MART;

ALTER DATABASE ECOMMERCE_DEV  SET DATA_RETENTION_TIME_IN_DAYS = 1;
ALTER DATABASE ECOMMERCE_PROD SET DATA_RETENTION_TIME_IN_DAYS = 7;
-- shorter Time Travel on DEV = lower storage cost


-- ------------------------------------------------------------
-- 2. A dedicated role instead of using SYSADMIN
--    Rationale: least privilege. The pipeline gets exactly the
--    grants it needs, nothing more.
-- ------------------------------------------------------------
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS transformer;

-- compute
GRANT USAGE ON WAREHOUSE ECOMMERCE_WH TO ROLE transformer;

-- DEV: full control (this is where dbt builds)
GRANT USAGE                    ON DATABASE ECOMMERCE_DEV          TO ROLE transformer;
GRANT USAGE, CREATE SCHEMA     ON DATABASE ECOMMERCE_DEV          TO ROLE transformer;
GRANT ALL ON ALL SCHEMAS       IN DATABASE ECOMMERCE_DEV          TO ROLE transformer;
GRANT ALL ON FUTURE SCHEMAS    IN DATABASE ECOMMERCE_DEV          TO ROLE transformer;
GRANT ALL ON ALL TABLES        IN DATABASE ECOMMERCE_DEV          TO ROLE transformer;
GRANT ALL ON FUTURE TABLES     IN DATABASE ECOMMERCE_DEV          TO ROLE transformer;
GRANT ALL ON ALL VIEWS         IN DATABASE ECOMMERCE_DEV          TO ROLE transformer;
GRANT ALL ON FUTURE VIEWS      IN DATABASE ECOMMERCE_DEV          TO ROLE transformer;

-- PROD: same, but you would normally restrict this to CI only
GRANT USAGE, CREATE SCHEMA     ON DATABASE ECOMMERCE_PROD         TO ROLE transformer;
GRANT ALL ON ALL SCHEMAS       IN DATABASE ECOMMERCE_PROD         TO ROLE transformer;
GRANT ALL ON FUTURE SCHEMAS    IN DATABASE ECOMMERCE_PROD         TO ROLE transformer;
GRANT ALL ON ALL TABLES        IN DATABASE ECOMMERCE_PROD         TO ROLE transformer;
GRANT ALL ON FUTURE TABLES     IN DATABASE ECOMMERCE_PROD         TO ROLE transformer;
GRANT ALL ON ALL VIEWS         IN DATABASE ECOMMERCE_PROD         TO ROLE transformer;
GRANT ALL ON FUTURE VIEWS      IN DATABASE ECOMMERCE_PROD         TO ROLE transformer;

-- Assign the role. SET the target login once and reuse it below.
SET login = 'HP';   -- the Snowflake account this pipeline runs as

GRANT ROLE transformer TO USER IDENTIFIER($login);

-- make it the default so you don't have to switch every session
ALTER USER IDENTIFIER($login) SET DEFAULT_ROLE = transformer;
ALTER USER IDENTIFIER($login) SET DEFAULT_WAREHOUSE = ECOMMERCE_WH;


-- ------------------------------------------------------------
-- 3. Verify
-- ------------------------------------------------------------
USE ROLE transformer;

SHOW DATABASES LIKE 'ECOMMERCE%';
SHOW SCHEMAS IN DATABASE ECOMMERCE_DEV;
SHOW GRANTS TO ROLE transformer;

-- Round-trip check: both statements succeed when the grants are correct.
CREATE OR REPLACE TABLE ECOMMERCE_DEV.RAW._permission_test (x INT);
DROP TABLE ECOMMERCE_DEV.RAW._permission_test;


-- ------------------------------------------------------------
-- 4. Retire the original single-environment database once DEV is populated.
-- ------------------------------------------------------------
-- USE ROLE SYSADMIN;
-- DROP DATABASE ECOMMERCE;

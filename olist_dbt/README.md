# olist — dbt project

Transforms the Olist RAW tables into tested, documented marts.

## Layers

| Layer | Materialisation | Purpose |
|---|---|---|
| `staging/` | view | one model per source table; cleans, casts, deduplicates |
| `marts/core/` | table | star schema — `fact_orders` plus three dimensions |
| `marts/insights/` | table | one model per business finding |

## Setup

```bash
pip install dbt-snowflake
dbt deps          # installs dbt_utils and dbt_expectations
dbt debug         # confirms the Snowflake connection
```

Credentials come from environment variables (see `.env.example` at the repo
root). Two targets are defined: `dev` builds into `ECOMMERCE_DEV`, `prod` into
`ECOMMERCE_PROD`.

## Running

```bash
dbt build                      # build every model and run every test
dbt build --select staging     # staging only
dbt build --select +fact_orders # fact_orders and everything it depends on
dbt test                       # tests without rebuilding
dbt docs generate && dbt docs serve
```

## Testing strategy

Three layers, all running as part of `dbt build`:

1. **Generic tests** — `unique`, `not_null`, `relationships`, `accepted_values`
   on every key and categorical column.
2. **Package tests** — `dbt_utils.unique_combination_of_columns` for composite
   grains, `dbt_expectations` for ranges and value distributions.
3. **Unit tests** — assert that transformation *logic* is correct for known
   input, independent of warehouse contents. Covers the late-delivery flag,
   freight ratio, and delivery-speed bucketing at its boundaries.

Plus two singular tests in `tests/` for rules that span columns or models.

`fact_orders` additionally enforces a **model contract**, so a change to a
column name or type fails the build rather than silently breaking downstream
models.

## Grain

`fact_orders` is **one row per order item**, keyed on
`(order_id, order_item_seq)`. `order_id` repeats for multi-item orders — 112,650
rows cover 98,666 orders. Count orders with `count(distinct order_id)` and
aggregate to order level before computing order-level averages.

Every data quality decision implemented here is documented in
`docs/data_quality_notes.md`.

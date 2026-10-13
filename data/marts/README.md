# Mart snapshot — regenerated, not exported

These CSVs are **recomputed from the raw Olist files**, not dumped out of
Snowflake. `analysis/build_snapshot.py` is a pandas re-implementation of the
dbt models in `olist_dbt/models/`: same sources, same joins, same filters, same
grain, same column names.

They exist so the public Streamlit deployment has something to read. The
warehouse is the real target — `streamlit/app.py` queries it directly whenever
`[snowflake]` credentials are present, and falls back to these files when they
are not.

## Why a regeneration and not an export

The Snowflake trial behind this project expired. Rather than present a
dashboard with no data, or pay to keep a finished portfolio project alive, the
marts were rebuilt from the raw CSVs by the same logic the dbt models apply.

The honest framing: **this is a second implementation of the same
transformations, not a copy of their output.** Two implementations agreeing is
weaker evidence than an export, and stronger than nothing. Where they could
disagree is listed below.

## What is in here

| File | Rows | Mirrors |
|---|---|---|
| `mart_retention.csv` | 3 | `DBT_MART.mart_retention` |
| `mart_review_distribution.csv` | 5 | `DBT_MART.mart_review_distribution` |
| `mart_delivery_satisfaction.csv` | 6 | `DBT_MART.mart_delivery_satisfaction` |
| `mart_geographic_chain.csv` | 26 | `DBT_MART.mart_geographic_chain` |
| `mart_customer_segments.csv` | 4 | `DBT_MART.mart_customer_segments` |
| `mart_freight_burden.csv` | 54 | `DBT_MART.mart_freight_burden` |
| `review_risk_buckets.csv` | 3 | aggregate of `DBT_MART.review_risk_scores` |
| `kpis.csv` | 1 | the header's cross-table subqueries |
| `meta.csv` | 1 | the footer's reconciliation counts |
| `model_metrics.json` | — | metrics from refitting the risk model here |

Column names and row order match what the app's SQL asks for, so the loader
does no renaming and no sorting. A drifted column fails loudly in a chart
rather than being patched over.

`review_risk_buckets.csv` is an aggregate because the dashboard only ever draws
three bars from it; committing 95,595 per-order scores would add megabytes for
nothing.

## Known differences from the warehouse run

**The risk model is refit here, so its metrics differ.** The warehouse run
recorded ROC AUC 0.684 and a 3.49× odds ratio on lateness
(`models/metrics.json`). Refitting on the regenerated feature table gives
**0.697** and **3.49×** — same features, same 75/25 split, same seed, slightly
different row count. The odds ratio agrees; the AUC does not. The app shows
whichever belongs to the source it is reading, and neither is presented as
covering both cases.

**The warehouse was last built before the review dedup was fixed.** The
figures here include the 550 orders whose reviews the old dedup discarded, so
review-dependent counts run slightly higher than the Snowflake screenshots
from August. Percentages are unaffected. See the section below.

**Date arithmetic.** Snowflake's `datediff('day', …)` counts calendar
boundaries crossed, not whole 24-hour periods. The regeneration normalises both
timestamps to dates before subtracting so it matches; a naive timedelta would
not.

## A number that moved, and why

Earlier project notes quote the retention split as **93,099 / 2,745 / 252**
customers. The marts give **92,507 / 2,673 / 240**.

Both are right about different populations. The first is the raw-data split
across all 96,096 people. The second is what `mart_retention` returns, because
it reads `dim_customers` and filters `lifetime_orders > 0` — and **775 orders
carry no line items**, so they never reach `fact_orders`, so the **676 people
whose every order is one of those** have a lifetime order count of zero and
drop out.

That 676-customer gap is a real property of the pipeline, documented during
build. The dashboard reports the mart's figure, which is why it reads 96.95%
rather than 96.88%.

## The review dedup, fixed

`stg_order_reviews` used to deduplicate on `review_id` alone. 814 rows share a
`review_id` with another row — but every one of those pairs sits on a
*different* `order_id`, and `(review_id, order_id)` is unique across all 99,224
source rows. The dedup was therefore deleting legitimate rows and leaving **550
orders with no review at all**.

Every test passed throughout, because the `unique` test on `review_id` was
checking the output of the bug rather than the input to it.

Both the model and this regeneration now partition on the pair, which keeps
every row and leaves `row_number()` as a guard against a future duplicate pair
rather than an active filter. The `unique` test moved to
`dbt_utils.unique_combination_of_columns` on both columns — one test replaced
by one test, so the suite is still 123.

Nothing headline moved: mean score 4.09 either way, 1-star share 11.5% either
way. 550 orders got their reviews back.

**Two numbers now reconcile that did not before.** The promise split comes out
at exactly **88,653 / 7,700**, which is what the Phase 2 profiling computed
straight from the raw CSVs before dbt existed. The fitted lateness odds ratio
lands on **3.49×**, the figure recorded against the warehouse run.

## Regenerating

```bash
python analysis/build_snapshot.py
```

Expects the nine raw Olist CSVs. Writes this folder, plus full-size
intermediates to `data/marts_full/` which are deliberately not committed.

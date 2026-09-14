# Data Quality Notes

Output of Phase 2. Every finding below was measured against the loaded RAW
tables in `ECOMMERCE_DEV.RAW`, not assumed.

Each finding carries a decision — **keep**, **flag**, or **fix** — and, where it
is a fix, the dbt test that will enforce it from Phase 3 onward. Nothing here
remains as ad-hoc SQL: findings become permanent tests.

## Method

Two complementary passes:

1. **Automated profiling** (`profiling/profile_raw.py`, reports in
   `docs/profiling/`) — computes completeness, cardinality and distributions for
   every column of all 9 tables.
2. **Targeted SQL** (`sql/01_profile.sql`, `sql/02_final_checks.sql`) — answers
   the questions a single-table profiler structurally cannot.

The split matters. Automated profiling reported that `ORDER_ID` in
`raw_order_items` has 98,666 distinct values and that the table has 112,650 rows
— but never compared the two, because it has no way to know `order_id` was
*intended* to be one per row. The same blind spot hid the duplicate review keys
and the geolocation fan-out. Every finding that required comparing two numbers,
or comparing across tables, came from the SQL.

---

## Findings

### 1. Missing values are true NULLs · **keep**

Ingestion loads blank source cells as SQL `NULL` rather than empty strings, so
`COUNT(col)` and `IS NULL` behave as expected for anyone querying RAW.

**Verified:** `raw_orders` returns 99,441 rows with 2,965 NULL
`order_delivered_customer_date` and 0 empty strings.

---

### 2. Delivery timestamps missing on undelivered orders · **keep**

| Column | Missing | % |
|---|---|---|
| `order_approved_at` | 160 | 0.2% |
| `order_delivered_carrier_date` | 1,783 | 1.8% |
| `order_delivered_customer_date` | 2,965 | 3.0% |

Missing counts rise along the fulfilment chain. This is legitimate: an order that
was cancelled or is still in transit genuinely has no delivery date. Confirmed by
the status distribution — 96,478 of 99,441 orders are `delivered`, leaving 2,963
at other stages, which matches the 2,965 missing delivery dates.

**Handling:** no imputation. Delivery and satisfaction analysis filters
`WHERE order_status = 'delivered'`.

---

### 3. Fact grain is order-item, not order · **fix**

`raw_order_items` holds **112,650 rows across 98,666 distinct orders**. One row is
one item within an order, not one order.

**Why it matters:** `COUNT(*)` overstates order volume by roughly 14%, and any
average computed per row returns average *item* value rather than average order
value.

**Handling:**
- Count orders with `COUNT(DISTINCT order_id)`, never `COUNT(*)`
- Aggregate to order level before computing order-level averages
- `fact_orders` is documented as order-item grain

**dbt test:** `dbt_utils.unique_combination_of_columns` on
`(order_id, order_item_id)`.

---

### 4. `customer_id` identifies an order, not a person · **fix**

`raw_customers` has 99,441 distinct `customer_id` but only **96,096 distinct
`customer_unique_id`**. Olist issues a fresh `customer_id` per order;
`customer_unique_id` links orders belonging to the same person. The 3,345
difference is repeat purchases.

**Why it matters:** counting customers by `customer_id` returns 99,441 and makes
the repeat rate appear to be zero.

**Handling:** `dim_customers` is keyed on `customer_unique_id`. All retention,
lifetime-value and segmentation logic uses it.

**dbt test:** `unique` and `not_null` on `customer_id`; `not_null` on
`customer_unique_id`.

---

### 5. Junk value in `payment_type` · **fix**

| Value | Rows |
|---|---|
| credit_card | 76,795 |
| boleto | 19,784 |
| voucher | 5,775 |
| debit_card | 1,529 |
| **not_defined** | **3** |

`not_defined` is a placeholder, not a payment method.

**Handling:** map `not_defined` → `unknown` in `stg_order_payments`.

**dbt test:** `accepted_values` on
`['credit_card','boleto','voucher','debit_card','unknown']`.

---

### 6. Order statuses are all legitimate · **keep**

delivered 96,478 · shipped 1,107 · canceled 625 · unavailable 609 ·
invoiced 314 · processing 301 · created 5 · approved 2.

No junk values. Recorded so an unexpected ninth status in future data fails the
build rather than passing silently.

**dbt test:** `accepted_values` listing all eight.

---

### 7. Two product categories have no English translation · **fix**

`raw_products` holds 73 real category values; the translation lookup holds 71.
The two without a match are:

- `pc_gamer`
- `portateis_cozinha_e_preparadores_de_alimentos`

Separately, **610 products have no category at all**, and the same 610 rows are
also missing `product_name_lenght`, `product_description_lenght` and
`product_photos_qty` — one block of incomplete product records rather than
random loss.

**Handling:** `COALESCE(english_name, portuguese_name, 'unknown')` in
`stg_products`, so no product is dropped from category analysis.

**dbt test:** `not_null` on the resulting `category_name_en`.

---

### 8. Source column names are misspelled · **fix**

`raw_products` contains `product_name_lenght` and `product_description_lenght`.
The misspelling is in the source data.

**Handling:** renamed to `product_name_length` / `product_description_length` in
`stg_products`. RAW keeps the original spelling so it stays a faithful mirror of
the source.

---

### 9. Duplicate review keys · **fix**

`raw_order_reviews` has 99,224 rows but only 98,410 distinct `review_id` —
**814 duplicates**, with some IDs appearing three times. `review_id` is intended
as the primary key.

**Handling:** deduplicate in `stg_order_reviews` with
`ROW_NUMBER() OVER (PARTITION BY review_id ORDER BY review_answer_timestamp DESC)`,
keeping the most recent.

**dbt test:** `unique` and `not_null` on `review_id`.

---

### 10. Geolocation fan-out on the join key · **fix**

`raw_geolocation` holds 1,000,163 rows across only **19,015 distinct zip
prefixes — about 53 rows per zip**. Each zip has many GPS points because a
postcode covers an area.

**Why it matters:** joining this table on zip without collapsing it first
multiplies every joined row roughly 53×, corrupting every downstream count and
sum.

**Handling:** `stg_geolocation` reduces to one row per zip — averaged
coordinates, modal city and state — and filters points outside Brazil's bounding
box.

**dbt test:** `unique` on `zip_prefix` in the staging model.

---

### 11. Reviews created before delivery · **flag**

**8,320 reviews** (about 8%) were created before the order's delivery timestamp.

This is not corruption. Olist requests the review when the order ships rather
than when it arrives, so a customer can respond before the package lands.

**Handling:** documented, not filtered. It affects interpretation — a review is
not always a verdict on a received product — but the rows are valid.

---

### 12. One order has no payment record · **flag**

`raw_order_payments` covers 99,440 distinct orders; `raw_orders` holds 99,441.

Immaterial at this scale, but recorded rather than ignored.

---

## Checks that passed

| Check | Result |
|---|---|
| Orphan order items (FK to orders) | 0 |
| Unparseable `price` / `freight_value` | 0 |
| Unparseable purchase / delivery timestamps | 0 |
| `review_score` outside 1–5 | none — exactly 5 distinct values |
| `raw_sellers` primary key | 3,095 rows, 100% distinct, no missing values |
| Category translation lookup | 71 rows, clean one-to-one mapping |

Referential integrity and type validity are intact. These become
`relationships` and `dbt_expectations` tests so they stay true on every build.

---

## Not a defect, but worth recording

**Four states have customers but no sellers.** `raw_customers` covers 27 states,
`raw_sellers` only 23. Combined with 8,011 city spellings in geolocation against
4,119 in customers, this points to the geographic concentration that drives the
delivery-time analysis in Phase 4. A business finding, not a data quality issue.

---

## Summary

| # | Finding | Scale | Decision |
|---|---|---|---|
| 1 | Missing values load as NULL | — | keep |
| 2 | Delivery timestamps missing on undelivered orders | 2,965 | keep |
| 3 | Fact grain is order-item | 112,650 vs 98,666 | fix |
| 4 | `customer_id` is per-order, not per-person | 99,441 vs 96,096 | fix |
| 5 | `not_defined` payment type | 3 | fix |
| 6 | Eight legitimate order statuses | — | keep |
| 7 | Missing translations and categories | 2 + 610 | fix |
| 8 | Misspelled source columns | 2 | fix |
| 9 | Duplicate review keys | 814 | fix |
| 10 | Geolocation fan-out | ~53× | fix |
| 11 | Reviews created before delivery | 8,320 | flag |
| 12 | Order with no payment record | 1 | flag |

Seven fixes, three keeps, two flags. Each fix is implemented in a staging model
in Phase 3 and enforced by the test named above, so the check runs on every build
rather than once.

"""
Regenerate the offline mart snapshot from the raw Olist CSVs.

This is a faithful pandas re-implementation of the dbt models in
olist_dbt/models/, written so the output CSVs carry the SAME COLUMN NAMES as
the Snowflake tables the dashboard queries. The point is that app.py can read
either source without knowing which one it got.

It is a re-computation, not an export. Where it differs from Snowflake it is
noted in the generated README.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split

RAW = Path("/mnt/user-data/uploads")
OUT = Path(__file__).parent / "marts"
OUT.mkdir(exist_ok=True)

TS = "%Y-%m-%d %H:%M:%S"


def ts(s):
    """try_to_timestamp(col, 'YYYY-MM-DD HH24:MI:SS')"""
    return pd.to_datetime(s, format=TS, errors="coerce")


def datediff_day(start, end):
    """Snowflake datediff('day', ...) counts DATE boundaries crossed, not
    whole 24h periods. Normalising first is what makes this match."""
    return (end.dt.normalize() - start.dt.normalize()).dt.days


def rnd(x, n=0):
    """Snowflake ROUND is half-away-from-zero; numpy is half-to-even."""
    a = np.asarray(x, dtype="float64")
    f = 10.0**n
    out = np.where(a < 0, -(np.floor(np.abs(a) * f + 0.5) / f),
                   np.floor(np.abs(a) * f + 0.5) / f)
    return float(out) if np.ndim(x) == 0 else out


# ---------------------------------------------------------------------------
# staging
# ---------------------------------------------------------------------------

print("staging ...")

raw_orders = pd.read_csv(RAW / "olist_orders_dataset.csv", dtype=str, keep_default_na=True)
stg_orders = pd.DataFrame({
    "order_id": raw_orders.order_id,
    "customer_id": raw_orders.customer_id,
    "order_status": raw_orders.order_status,
    "purchased_at": ts(raw_orders.order_purchase_timestamp),
    "delivered_at": ts(raw_orders.order_delivered_customer_date),
    "estimated_delivery_at": ts(raw_orders.order_estimated_delivery_date),
})
stg_orders["delivery_days"] = datediff_day(stg_orders.purchased_at, stg_orders.delivered_at)
stg_orders["days_vs_promise"] = datediff_day(stg_orders.delivered_at,
                                             stg_orders.estimated_delivery_at)
stg_orders["is_late_vs_promise"] = np.where(
    stg_orders.delivered_at.isna(), None,
    stg_orders.delivered_at > stg_orders.estimated_delivery_at)

raw_items = pd.read_csv(RAW / "olist_order_items_dataset.csv", dtype=str)
stg_order_items = pd.DataFrame({
    "order_id": raw_items.order_id,
    "order_item_seq": pd.to_numeric(raw_items.order_item_id, errors="coerce"),
    "product_id": raw_items.product_id,
    "seller_id": raw_items.seller_id,
    "item_price": pd.to_numeric(raw_items.price, errors="coerce").round(2),
    "freight_value": pd.to_numeric(raw_items.freight_value, errors="coerce").round(2),
})

raw_rev = pd.read_csv(RAW / "olist_order_reviews_dataset.csv", dtype=str)
raw_rev["_ans"] = ts(raw_rev.review_answer_timestamp)
# Grain is the PAIR. Deduplicating on review_id alone deleted 814 legitimate
# rows and left 550 orders with no review; (review_id, order_id) is already
# unique across all 99,224 source rows, so this keeps every row and acts as a
# guard rather than a filter. Matches stg_order_reviews.sql.
raw_rev = raw_rev.sort_values("_ans", ascending=False, na_position="last")
stg_order_reviews = (
    raw_rev.drop_duplicates(subset=["review_id", "order_id"], keep="first")
    .assign(review_score=lambda d: pd.to_numeric(d.review_score, errors="coerce"))
    [["review_id", "order_id", "review_score"]]
    .reset_index(drop=True)
)

raw_cust = pd.read_csv(RAW / "olist_customers_dataset.csv", dtype=str)
stg_customers = pd.DataFrame({
    "customer_id": raw_cust.customer_id,
    "customer_unique_id": raw_cust.customer_unique_id,
    "customer_city": raw_cust.customer_city.str.strip().str.lower(),
    "customer_state": raw_cust.customer_state.str.strip().str.upper(),
})

raw_sell = pd.read_csv(RAW / "olist_sellers_dataset.csv", dtype=str)
dim_sellers = pd.DataFrame({
    "seller_id": raw_sell.seller_id,
    "seller_state": raw_sell.seller_state.str.strip().str.upper(),
})

raw_prod = pd.read_csv(RAW / "olist_products_dataset.csv", dtype=str)
raw_tr = pd.read_csv(RAW / "product_category_name_translation.csv", dtype=str)
raw_tr.columns = [c.strip() for c in raw_tr.columns]
tr = pd.DataFrame({
    "category_name_pt": raw_tr.product_category_name.str.strip().str.lower(),
    "category_name_en": raw_tr.product_category_name_english.str.strip().str.lower(),
})
stg_products = pd.DataFrame({
    "product_id": raw_prod.product_id,
    "category_name_pt": raw_prod.product_category_name.str.strip().str.lower(),
}).merge(tr, on="category_name_pt", how="left")
stg_products["category_name_en"] = (
    stg_products.category_name_en.fillna(stg_products.category_name_pt).fillna("unknown"))

# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------

print("core ...")

fact_orders = (
    stg_order_items
    .merge(stg_orders[["order_id", "customer_id", "order_status", "purchased_at",
                       "delivery_days", "days_vs_promise", "is_late_vs_promise"]],
           on="order_id", how="inner")
    .merge(stg_products[["product_id", "category_name_en"]], on="product_id", how="inner")
)
fact_orders["freight_ratio"] = np.where(
    fact_orders.item_price > 0,
    rnd(fact_orders.freight_value / fact_orders.item_price.replace(0, np.nan), 4),
    np.nan)

hist = (
    stg_customers.merge(stg_orders[["customer_id", "purchased_at"]],
                        on="customer_id", how="inner")
    .sort_values("purchased_at", ascending=False)
    .drop_duplicates(subset="customer_unique_id", keep="first")
)
spend = (
    fact_orders.merge(stg_customers[["customer_id", "customer_unique_id"]],
                      on="customer_id", how="inner")
    .groupby("customer_unique_id")
    .agg(lifetime_orders=("order_id", "nunique"), lifetime_spend=("item_price", "sum"))
    .reset_index()
)
dim_customers = hist.merge(spend, on="customer_unique_id", how="left")
dim_customers["lifetime_orders"] = dim_customers.lifetime_orders.fillna(0).astype(int)
dim_customers["lifetime_spend"] = dim_customers.lifetime_spend.fillna(0.0)

# ---------------------------------------------------------------------------
# insight marts — column names must match Snowflake
# ---------------------------------------------------------------------------

print("marts ...")

# mart_retention
d = dim_customers[dim_customers.lifetime_orders > 0].copy()
d["order_frequency"] = np.select(
    [d.lifetime_orders == 1, d.lifetime_orders == 2], ["1 order", "2 orders"], "3+ orders")
mart_retention = (
    d.groupby("order_frequency").size().reset_index(name="customers")
    .sort_values("order_frequency").reset_index(drop=True))
mart_retention["pct_of_customers"] = rnd(
    mart_retention.customers * 100.0 / mart_retention.customers.sum(), 2)

# mart_review_distribution
rv = stg_order_reviews[stg_order_reviews.review_score.between(1, 5)]
mart_review_distribution = rv.groupby("review_score").size().reset_index(name="reviews")
mart_review_distribution["pct_of_reviews"] = rnd(
    mart_review_distribution.reviews * 100.0 / mart_review_distribution.reviews.sum(), 1)

# mart_delivery_satisfaction
delivered = fact_orders[(fact_orders.order_status == "delivered")
                        & fact_orders.delivery_days.notna()]
delivered = delivered[["order_id", "delivery_days", "is_late_vs_promise",
                       "days_vs_promise"]].drop_duplicates()
wr = delivered.merge(rv[["order_id", "review_score"]], on="order_id", how="inner")

wr["bucket"] = np.select(
    [wr.delivery_days <= 7, wr.delivery_days <= 14, wr.delivery_days <= 21],
    ["1-7 days", "8-14 days", "15-21 days"], "22+ days")
wr["bucket_order"] = np.select(
    [wr.delivery_days <= 7, wr.delivery_days <= 14, wr.delivery_days <= 21], [1, 2, 3], 4)


def summarise(df, lens, by):
    g = df.groupby(by, dropna=False).apply(
        lambda x: pd.Series({
            "orders": len(x),
            "avg_review_score": rnd(x.review_score.mean(), 2),
            "avg_delivery_days": rnd(
                (x.delivery_days if lens == "speed" else x.days_vs_promise).mean(), 1),
            "pct_bad_review": rnd((x.review_score <= 2).sum() * 100.0 / len(x), 1),
        }), include_groups=False).reset_index()
    g.insert(0, "lens", lens)
    return g


by_speed = summarise(wr, "speed", ["bucket", "bucket_order"])
wr["pbucket"] = np.where(wr.is_late_vs_promise == True, "Late vs promise", "On time or early")
wr["pbucket_order"] = np.where(wr.is_late_vs_promise == True, 2, 1)
by_promise = summarise(wr, "promise", ["pbucket", "pbucket_order"]).rename(
    columns={"pbucket": "bucket", "pbucket_order": "bucket_order"})
mart_delivery_satisfaction = (
    pd.concat([by_speed, by_promise], ignore_index=True)
    [["lens", "bucket", "bucket_order", "orders", "avg_review_score",
      "avg_delivery_days", "pct_bad_review"]]
    # written in the order the app's `order by bucket_order` would return,
    # so the snapshot loader needs no sorting of its own
    .sort_values(["lens", "bucket_order"], ascending=[False, True])
    .reset_index(drop=True))

# mart_geographic_chain  (column is `state`, not `customer_state`)
geo_orders = (
    fact_orders[(fact_orders.order_status == "delivered") & fact_orders.delivery_days.notna()]
    [["order_id", "customer_id", "delivery_days", "is_late_vs_promise"]].drop_duplicates()
    .merge(stg_customers[["customer_id", "customer_state"]], on="customer_id", how="inner")
    .merge(rv[["order_id", "review_score"]], on="order_id", how="inner")
    .rename(columns={"customer_state": "state"})
)
g = geo_orders.groupby("state").apply(lambda x: pd.Series({
    "orders": x.order_id.nunique(),
    "avg_delivery_days": rnd(x.delivery_days.mean(), 1),
    "avg_review_score": rnd(x.review_score.mean(), 2),
    "pct_late_vs_promise": rnd((x.is_late_vs_promise == True).sum() * 100.0 / len(x), 1),
}), include_groups=False).reset_index()
demand = dim_customers.groupby("customer_state").size().reset_index(name="customers") \
    .rename(columns={"customer_state": "state"})
supply = dim_sellers.groupby("seller_state").size().reset_index(name="sellers") \
    .rename(columns={"seller_state": "state"})
mart_geographic_chain = (
    g.merge(demand, on="state", how="left").merge(supply, on="state", how="left")
    .fillna({"customers": 0, "sellers": 0})
    .query("orders >= 50")
    .sort_values("avg_delivery_days", ascending=False).reset_index(drop=True))
mart_geographic_chain["customers"] = mart_geographic_chain.customers.astype(int)
mart_geographic_chain["sellers"] = mart_geographic_chain.sellers.astype(int)

# mart_customer_segments
c = dim_customers[dim_customers.lifetime_spend > 0].copy()
n = len(c)
c = c.sort_values("lifetime_spend", ascending=False)
c["spend_rank_pct"] = (c.lifetime_spend.rank(method="min", ascending=False) - 1) / (n - 1)
c["value_tier"] = np.select(
    [c.spend_rank_pct <= 0.01, c.spend_rank_pct <= 0.10, c.spend_rank_pct <= 0.50],
    ["Top 1%", "Top 10%", "Next 40%"], "Bottom 50%")
seg = c.groupby("value_tier").apply(lambda x: pd.Series({
    "customers": len(x),
    "avg_spend": rnd(x.lifetime_spend.mean(), 2),
    "tier_revenue": rnd(x.lifetime_spend.sum(), 0),
    "avg_orders": rnd(x.lifetime_orders.mean(), 2),
    "_rev": x.lifetime_spend.sum(),
}), include_groups=False).reset_index()
seg["pct_of_revenue"] = rnd(seg._rev * 100.0 / seg._rev.sum(), 1)
order = ["Top 1%", "Top 10%", "Next 40%", "Bottom 50%"]
mart_customer_segments = (
    seg.drop(columns="_rev")
    .set_index("value_tier").loc[order].reset_index()
    [["value_tier", "customers", "avg_spend", "tier_revenue", "pct_of_revenue", "avg_orders"]])

# mart_freight_burden
it = fact_orders[fact_orders.item_price > 0]
fb = it.groupby("category_name_en").apply(lambda x: pd.Series({
    "items_sold": len(x),
    "orders": x.order_id.nunique(),
    "total_revenue": rnd(x.item_price.sum(), 0),
    "avg_item_price": rnd(x.item_price.mean(), 2),
    "avg_freight": rnd(x.freight_value.mean(), 2),
    "freight_pct_of_price": rnd(x.freight_value.mean() / x.item_price.mean() * 100, 1),
}), include_groups=False).reset_index()
mart_freight_burden = (fb[fb.items_sold >= 100]
                       .sort_values("freight_pct_of_price", ascending=False)
                       .reset_index(drop=True))

# mart_review_risk  (SQL additive score, as the dbt model defines it)
ol = fact_orders[(fact_orders.order_status == "delivered") & fact_orders.delivery_days.notna()]
ol = ol.groupby("order_id").agg(
    delivery_days=("delivery_days", "max"),
    is_late=("is_late_vs_promise", lambda s: int((s == True).any())),
    _min_dvp=("days_vs_promise", "min"),
    order_price=("item_price", "sum"),
    order_freight=("freight_value", "sum"),
).reset_index()
ol["days_late"] = np.maximum(-ol._min_dvp, 0)
ol["freight_ratio"] = np.where(ol.order_price > 0,
                               rnd(ol.order_freight / ol.order_price.replace(0, np.nan), 3),
                               np.nan)
ol["risk_score"] = (
    np.where(ol.is_late == 1, 3, 0)
    + np.where(ol.delivery_days > 20, 1, 0)
    + np.where((ol.order_price > 0) & (ol.order_freight / ol.order_price > 0.30), 1, 0))
ol["risk_bucket"] = np.select(
    [ol.risk_score >= 3, ol.risk_score == 2, ol.risk_score == 1],
    ["Very High", "High", "Medium"], "Low")
mart_review_risk = ol[["order_id", "delivery_days", "is_late", "days_late",
                       "freight_ratio", "risk_score", "risk_bucket"]].copy()
mart_review_risk["delivery_days"] = mart_review_risk.delivery_days.astype(int)
mart_review_risk["days_late"] = mart_review_risk.days_late.astype(int)

# ---------------------------------------------------------------------------
# review_risk_scores — the Python model's write-back table
# ---------------------------------------------------------------------------

print("risk model ...")

FEATURES = ["delivery_days", "is_late", "days_late", "freight_ratio"]
feat = (mart_review_risk.merge(rv[["order_id", "review_score"]], on="order_id", how="inner")
        .assign(bad_review=lambda d: (d.review_score <= 2).astype(int),
                freight_ratio=lambda d: d.freight_ratio.fillna(0))
        .dropna(subset=FEATURES + ["bad_review"]))

X, y = feat[FEATURES], feat.bad_review
X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
model = LogisticRegression(max_iter=1000, class_weight="balanced").fit(X_tr, y_tr)
proba_te = model.predict_proba(X_te)[:, 1]

metrics = {
    "rows": int(len(feat)),
    "base_rate_pct": round(float(y.mean() * 100), 1),
    "test_roc_auc": round(float(roc_auc_score(y_te, proba_te)), 3),
    "test_avg_precision": round(float(average_precision_score(y_te, proba_te)), 3),
    "odds_ratios": {f: round(float(np.exp(c)), 3) for f, c in zip(FEATURES, model.coef_[0])},
}

scored = feat.copy()
scored["risk_probability"] = model.predict_proba(scored[FEATURES])[:, 1]
scored["risk_bucket"] = pd.cut(scored.risk_probability,
                               bins=[-0.001, 0.2, 0.4, 0.6, 1.0],
                               labels=["Low", "Medium", "High", "Very High"])
review_risk_scores = scored[["order_id", "risk_probability", "risk_bucket"]].copy()
review_risk_scores["risk_bucket"] = review_risk_scores.risk_bucket.astype(str)
review_risk_scores["risk_probability"] = review_risk_scores.risk_probability.round(6)

# The dashboard only ever reads the bucket aggregate, so that is what gets
# committed. Shipping 95k per-order scores would bloat the repo for a chart
# with three bars.
review_risk_buckets = (
    review_risk_scores.groupby("risk_bucket")
    .agg(orders=("order_id", "size"),
         avg_predicted_pct=("risk_probability", lambda s: rnd(s.mean() * 100, 1)))
    .reset_index())
bucket_rank = {"Low": 0, "Medium": 1, "High": 2, "Very High": 3}
review_risk_buckets = (review_risk_buckets
                       .assign(_r=lambda d: d.risk_bucket.map(bucket_rank))
                       .sort_values("_r").drop(columns="_r").reset_index(drop=True))

# ---------------------------------------------------------------------------
# kpis + meta — the two header/footer queries, which hit core not insights
# ---------------------------------------------------------------------------

kpis = pd.DataFrame([{
    "gmv": float(fact_orders.item_price.sum()),
    "orders": int(fact_orders.order_id.nunique()),
    "customers": int(len(dim_customers)),
    "avg_review": float(rnd(rv.review_score.mean(), 2)),
    "pct_one_star": float(mart_review_distribution.loc[
        mart_review_distribution.review_score == 1, "pct_of_reviews"].iloc[0]),
    "repeat_rate": float(rnd(mart_retention.loc[
        mart_retention.order_frequency != "1 order", "pct_of_customers"].sum(), 2)),
}])

meta = pd.DataFrame([{
    "latest_order": fact_orders.purchased_at.max().strftime("%Y-%m-%d %H:%M:%S"),
    "raw_orders": int(raw_orders.order_id.nunique()),
    "mart_orders": int(fact_orders.order_id.nunique()),
}])

# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

tables = {
    "mart_retention": mart_retention,
    "mart_review_distribution": mart_review_distribution,
    "mart_delivery_satisfaction": mart_delivery_satisfaction,
    "mart_geographic_chain": mart_geographic_chain,
    "mart_customer_segments": mart_customer_segments,
    "mart_freight_burden": mart_freight_burden,
    "review_risk_buckets": review_risk_buckets,
    "kpis": kpis,
    "meta": meta,
}
for name, df in tables.items():
    df.to_csv(OUT / f"{name}.csv", index=False)
    print(f"  {name:30s} {len(df):>7,} rows  {list(df.columns)}")

# Full-size intermediates: useful as evidence, too large to want in git.
FULL = OUT.parent / "marts_full"
FULL.mkdir(exist_ok=True)
mart_review_risk.to_csv(FULL / "mart_review_risk.csv", index=False)
review_risk_scores.to_csv(FULL / "review_risk_scores.csv", index=False)

import json
(OUT / "model_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

print("\nmetrics:", metrics)
print("\nkpis:", kpis.to_dict("records")[0])
print("meta:", meta.to_dict("records")[0])
print("\nretention:\n", mart_retention)
print("\ndelivery:\n", mart_delivery_satisfaction)
print("\nrisk buckets:\n", review_risk_scores.risk_bucket.value_counts())

"""
BrazilCommerce 360 — Phase 4: bad-review risk model

Predicts whether an order will receive a 1 or 2 star review, using features
available at delivery time. The point is not maximum accuracy — it is an
explainable score that could flag high-risk orders before the review lands,
so service recovery can happen proactively.

Design decisions:

  * Logistic regression, not a boosted tree. Coefficients convert directly to
    odds ratios, so the model supports a recommendation rather than just a
    prediction. A tree would likely score a little higher and explain nothing.

  * Train/test split happens BEFORE any fitting. Nothing is learned from the
    held-out set — no scaling, no imputation, no feature selection.

  * Features are read from the dbt marts, not from CSVs, so the model consumes
    the same tested, documented data as the dashboard.

  * The fitted model is persisted to models/risk_model.pkl and its metrics to
    models/metrics.json, so a run is reproducible and auditable rather than
    printing to a terminal and disappearing.

  * Scores are written back to Snowflake as MART.review_risk_scores, so the
    dashboard can serve risk without loading a Python artefact.

Usage:
    pip install scikit-learn joblib
    python analysis/risk_model.py
    python analysis/risk_model.py --no-write-back    # skip the Snowflake write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

try:
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, average_precision_score
    from sklearn.model_selection import train_test_split
except ImportError:
    sys.exit("\nMissing dependencies. Run: pip install scikit-learn joblib\n")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

MODEL_DIR = PROJECT_ROOT / "analysis" / "artifacts"

CONN = dict(
    account=os.environ.get("SNOWFLAKE_ACCOUNT"),
    user=os.environ.get("SNOWFLAKE_USER"),
    password=os.environ.get("SNOWFLAKE_PASSWORD"),
    role=os.environ.get("SNOWFLAKE_ROLE", "transformer"),
    warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "ECOMMERCE_WH"),
    database=os.environ.get("SNOWFLAKE_DATABASE", "ECOMMERCE_DEV"),
    schema="DBT_MART",
)

FEATURES = ["delivery_days", "is_late", "days_late", "freight_ratio"]

# Order-level features joined to the review outcome. Deduplicated to order grain
# in the mart already, so no fan-out risk here.
FEATURE_QUERY = """
select
    r.order_id,
    r.delivery_days,
    r.is_late,
    r.days_late,
    coalesce(r.freight_ratio, 0)              as freight_ratio,
    case when rev.review_score <= 2 then 1 else 0 end as bad_review
from {db}.dbt_mart.mart_review_risk        r
join {db}.dbt_staging.stg_order_reviews  rev
  on r.order_id = rev.order_id
where rev.review_score between 1 and 5
"""


def check_credentials() -> None:
    missing = [k for k in ("account", "user", "password") if not CONN.get(k)]
    if missing:
        keys = ", ".join(f"SNOWFLAKE_{m.upper()}" for m in missing)
        sys.exit(f"\nMissing credentials: {keys}\nFill in .env at the project root.\n")


def fetch_features(conn) -> pd.DataFrame:
    sql = FEATURE_QUERY.format(db=CONN["database"])
    cur = conn.cursor()
    try:
        cur.execute(sql)
        df = cur.fetch_pandas_all()
    finally:
        cur.close()

    df.columns = [c.lower() for c in df.columns]
    for col in FEATURES + ["bad_review"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=FEATURES + ["bad_review"])


def train(df: pd.DataFrame) -> tuple[LogisticRegression, dict]:
    X = df[FEATURES]
    y = df["bad_review"].astype(int)

    # Split first. Nothing below this line touches the test set until scoring.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    # class_weight='balanced' because bad reviews are the minority class;
    # without it the model would optimise by predicting "good" everywhere.
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train, y_train)

    test_proba = model.predict_proba(X_test)[:, 1]

    metrics = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_rows_total": int(len(df)),
        "n_rows_train": int(len(X_train)),
        "n_rows_test": int(len(X_test)),
        "baseline_bad_review_rate": round(float(y.mean()), 4),
        "test_roc_auc": round(float(roc_auc_score(y_test, test_proba)), 4),
        "test_avg_precision": round(
            float(average_precision_score(y_test, test_proba)), 4
        ),
        "features": FEATURES,
        "coefficients": {
            f: round(float(c), 4) for f, c in zip(FEATURES, model.coef_[0])
        },
        "odds_ratios": {
            f: round(float(np.exp(c)), 3) for f, c in zip(FEATURES, model.coef_[0])
        },
    }
    return model, metrics


def bucket_calibration(df: pd.DataFrame, model: LogisticRegression) -> pd.DataFrame:
    scored = df.copy()
    scored["risk_probability"] = model.predict_proba(scored[FEATURES])[:, 1]
    scored["risk_bucket"] = pd.cut(
        scored["risk_probability"],
        bins=[-0.001, 0.2, 0.4, 0.6, 1.0],
        labels=["Low", "Medium", "High", "Very High"],
    )
    calib = (
        scored.groupby("risk_bucket", observed=True)
        .agg(orders=("bad_review", "size"), actual_bad_rate=("bad_review", "mean"))
        .reset_index()
    )
    calib["actual_bad_rate"] = (calib["actual_bad_rate"] * 100).round(1)
    return scored, calib


def write_scores(conn, scored: pd.DataFrame) -> None:
    out = scored[["order_id", "risk_probability", "risk_bucket"]].copy()
    out["risk_probability"] = out["risk_probability"].round(4)
    out["risk_bucket"] = out["risk_bucket"].astype(str)
    out["scored_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    out.columns = [c.upper() for c in out.columns]

    write_pandas(
        conn, out, "REVIEW_RISK_SCORES",
        database=CONN["database"], schema="DBT_MART",
        auto_create_table=True, overwrite=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write-back", action="store_true",
                    help="skip writing scores to Snowflake")
    args = ap.parse_args()

    check_credentials()
    conn = snowflake.connector.connect(**CONN)

    print(f"\n{'=' * 62}")
    print("Bad-review risk model")
    print(f"{'=' * 62}")

    try:
        df = fetch_features(conn)
        print(f"  loaded {len(df):,} scored orders from {CONN['database']}")

        model, metrics = train(df)
        scored, calib = bucket_calibration(df, model)

        print(f"\n  baseline bad-review rate : {metrics['baseline_bad_review_rate']*100:.1f}%")
        print(f"  test ROC AUC             : {metrics['test_roc_auc']:.3f}")
        print(f"  test avg precision       : {metrics['test_avg_precision']:.3f}")

        print("\n  feature effect (odds ratio, >1 increases risk):")
        for f, o in metrics["odds_ratios"].items():
            print(f"    {f:16s} {o:>6.2f}x")

        print("\n  risk bucket calibration:")
        for _, r in calib.iterrows():
            print(f"    {str(r.risk_bucket):10s} {int(r.orders):>7,} orders"
                  f"   {r.actual_bad_rate:>5.1f}% actually bad")

        # persist artefact and metrics
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, MODEL_DIR / "risk_model.pkl")
        metrics["bucket_calibration"] = calib.to_dict(orient="records")
        (MODEL_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
        print(f"\n  artefact -> {MODEL_DIR / 'risk_model.pkl'}")
        print(f"  metrics  -> {MODEL_DIR / 'metrics.json'}")

        if not args.no_write_back:
            write_scores(conn, scored)
            print(f"  scores   -> {CONN['database']}.DBT_MART.REVIEW_RISK_SCORES")

    finally:
        conn.close()

    print(f"\n{'-' * 62}")
    print("Takeaway: lateness dominates. Flag 'Very High' orders for outreach")
    print("before the review is submitted.\n")


if __name__ == "__main__":
    main()

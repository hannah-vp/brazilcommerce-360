"""
BrazilCommerce 360 — Phase 1 ingestion
Loads the 9 Olist CSVs into Snowflake RAW with schema validation and a
dead-letter quarantine for rows that fail validation.

Design choices (the "why", for your README / interview):
  - Everything loads as VARCHAR into RAW. Type casting happens later in dbt
    STAGING. This keeps RAW source-faithful and prevents load failures from
    unexpected formats.
  - Each row is validated with Pydantic before loading. Valid rows go to the
    target table; invalid rows go to <table>_QUARANTINE so nothing is silently
    dropped and you can inspect what failed.
  - A load log records rows loaded vs quarantined per table.

Usage:
    pip install -r requirements.txt
    python load.py --data-dir ./data          # loads all 9 tables
    python load.py --data-dir ./data --table raw_orders   # one table
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
from pydantic import BaseModel, field_validator, ValidationError


# ---------------------------------------------------------------------------
# Connection — reads credentials from environment or a config dict.
# For a real run, set these as environment variables or edit CONN.
# ---------------------------------------------------------------------------

import os

CONN = dict(
    account=os.environ.get("SNOWFLAKE_ACCOUNT", "xy12345.us-east-1"),
    user=os.environ.get("SNOWFLAKE_USER", "YOUR_USERNAME"),
    password=os.environ.get("SNOWFLAKE_PASSWORD", "YOUR_PASSWORD"),
    role=os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
    warehouse="ECOMMERCE_WH",
    database="ECOMMERCE",
    schema="RAW",
)


# ---------------------------------------------------------------------------
# Validation schemas — one per file. Only the critical columns are validated;
# the rest pass through. Keep validation light: the goal is to catch structural
# breakage (missing keys, wrong types), not to over-police source data.
# ---------------------------------------------------------------------------

class OrderRow(BaseModel):
    order_id: str
    customer_id: str
    order_status: str

    @field_validator("order_id", "customer_id")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("blank key")
        return v


class OrderItemRow(BaseModel):
    order_id: str
    product_id: str
    seller_id: str
    price: float          # must parse as a number
    freight_value: float

    @field_validator("price", "freight_value")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("negative money value")
        return v


class CustomerRow(BaseModel):
    customer_id: str
    customer_unique_id: str


class ProductRow(BaseModel):
    product_id: str


class SellerRow(BaseModel):
    seller_id: str


class PaymentRow(BaseModel):
    order_id: str
    payment_value: float


class ReviewRow(BaseModel):
    review_id: str
    order_id: str
    review_score: int

    @field_validator("review_score")
    @classmethod
    def in_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("score out of 1-5 range")
        return v


class GeoRow(BaseModel):
    geolocation_zip_code_prefix: str


class CategoryRow(BaseModel):
    product_category_name: str
    product_category_name_english: str


# ---------------------------------------------------------------------------
# File -> (table, validation model) mapping
# ---------------------------------------------------------------------------

FILES = {
    "olist_orders_dataset.csv":                 ("raw_orders", OrderRow),
    "olist_order_items_dataset.csv":            ("raw_order_items", OrderItemRow),
    "olist_customers_dataset.csv":              ("raw_customers", CustomerRow),
    "olist_products_dataset.csv":               ("raw_products", ProductRow),
    "olist_sellers_dataset.csv":                ("raw_sellers", SellerRow),
    "olist_order_payments_dataset.csv":         ("raw_order_payments", PaymentRow),
    "olist_order_reviews_dataset.csv":          ("raw_order_reviews", ReviewRow),
    "olist_geolocation_dataset.csv":            ("raw_geolocation", GeoRow),
    "product_category_name_translation.csv":    ("raw_product_category_translation", CategoryRow),
}

EXPECTED_ROWS = {
    "raw_orders": 99_441, "raw_order_items": 112_650, "raw_customers": 99_441,
    "raw_products": 32_951, "raw_sellers": 3_095, "raw_order_payments": 103_886,
    "raw_order_reviews": 99_224, "raw_geolocation": 1_000_163,
    "raw_product_category_translation": 71,
}


# ---------------------------------------------------------------------------
# Core load routine
# ---------------------------------------------------------------------------

def validate_split(df: pd.DataFrame, model: type[BaseModel]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (good_rows, bad_rows) after per-row Pydantic validation."""
    good_idx, bad_idx = [], []
    fields = set(model.model_fields.keys())
    for idx, row in df.iterrows():
        payload = {k: row[k] for k in fields if k in df.columns}
        try:
            model(**payload)
            good_idx.append(idx)
        except (ValidationError, ValueError, TypeError):
            bad_idx.append(idx)
    return df.loc[good_idx], df.loc[bad_idx]


def load_table(conn, path: Path, table: str, model: type[BaseModel]) -> dict:
    # read everything as string to mirror the VARCHAR RAW layer
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[])
    good, bad = validate_split(df, model)

    # write good rows (overwrite so the load is idempotent / re-runnable)
    write_pandas(conn, good, table.upper(), auto_create_table=True, overwrite=True)

    # write quarantine only if there are bad rows
    if len(bad) > 0:
        write_pandas(conn, bad, f"{table}_QUARANTINE".upper(),
                     auto_create_table=True, overwrite=True)

    return {"table": table, "loaded": len(good), "quarantined": len(bad),
            "expected": EXPECTED_ROWS.get(table)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="folder containing the 9 CSVs")
    ap.add_argument("--table", help="load only this table (optional)")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    conn = snowflake.connector.connect(**CONN)

    results = []
    print(f"\n{'='*64}\nBrazilCommerce 360 — RAW ingestion  {datetime.now():%Y-%m-%d %H:%M}\n{'='*64}")
    try:
        for fname, (table, model) in FILES.items():
            if args.table and table != args.table:
                continue
            fpath = data_dir / fname
            if not fpath.exists():
                print(f"  ! {fname} not found — skipping")
                continue
            r = load_table(conn, fpath, table, model)
            results.append(r)
            flag = "" if r["expected"] is None or r["loaded"] + r["quarantined"] == r["expected"] else "  <-- COUNT MISMATCH"
            print(f"  {table:35s} loaded {r['loaded']:>9,}  quarantined {r['quarantined']:>4,}{flag}")
    finally:
        conn.close()

    total_q = sum(r["quarantined"] for r in results)
    print(f"{'-'*64}\nDone. {len(results)} tables, {total_q:,} rows quarantined total.\n")
    if total_q > 0:
        print("Inspect quarantined rows in Snowflake, e.g.:")
        print("  SELECT * FROM ECOMMERCE.RAW.RAW_ORDER_ITEMS_QUARANTINE LIMIT 20;\n")


if __name__ == "__main__":
    main()
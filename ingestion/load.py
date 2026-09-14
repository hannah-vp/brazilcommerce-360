"""
Olist CSV ingestion into Snowflake RAW.

Loads nine source files with vectorised schema validation.
Rows failing validation are written to <TABLE>_QUARANTINE rather than dropped.

Design decisions (stated deliberately for review):

  * Missing values are loaded as SQL NULL, not empty strings. Blank cells in the
    source CSVs become NULL so that standard COUNT(col) / IS NULL checks behave
    correctly for anyone querying RAW.

  * Column names are upper-cased before loading. Snowflake resolves unquoted
    identifiers to uppercase, so this keeps every downstream query free of
    quoted identifiers.

  * Validation is vectorised (whole-column pandas operations) rather than
    row-by-row. Validating the 1M-row geolocation file takes ~4s this way
    versus several minutes with df.iterrows().

  * Values are loaded as VARCHAR. RAW stays source-faithful; type casting is a
    STAGING concern handled in dbt with TRY_TO_* functions.

  * Loads use overwrite=True (truncate-and-replace). This is intentional for a
    fixed historical dataset that is loaded once. An incremental/MERGE strategy
    is demonstrated in the dbt fact model instead.

Usage:
    pip install -r requirements.txt
    python load.py --data-dir ../data
    python load.py --data-dir ../data --table raw_orders
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas


# ---------------------------------------------------------------------------
# Connection
#
# Credentials are read from a gitignored .env file at the project root, so they
# never appear in source control and do not have to be re-exported into every
# terminal session. See .env.example for the required keys.
# ---------------------------------------------------------------------------

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

CONN = dict(
    account=os.environ.get("SNOWFLAKE_ACCOUNT"),
    user=os.environ.get("SNOWFLAKE_USER"),
    password=os.environ.get("SNOWFLAKE_PASSWORD"),
    role=os.environ.get("SNOWFLAKE_ROLE", "transformer"),
    warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "ECOMMERCE_WH"),
    database=os.environ.get("SNOWFLAKE_DATABASE", "ECOMMERCE_DEV"),
    schema=os.environ.get("SNOWFLAKE_SCHEMA", "RAW"),
)


def check_credentials() -> None:
    """Fail fast with a clear message rather than a cryptic connector error."""
    missing = [k for k in ("account", "user", "password") if not CONN.get(k)]
    if missing:
        keys = ", ".join(f"SNOWFLAKE_{m.upper()}" for m in missing)
        sys.exit(
            f"\nMissing credentials: {keys}\n"
            f"Copy .env.example to .env at the project root and fill it in.\n"
        )


# ---------------------------------------------------------------------------
# Validation rules
#
# Each rule set is expressed as vectorised pandas conditions. A row is invalid
# if ANY condition is True. Rules are deliberately minimal: they catch
# structural breakage (missing keys, unparseable numbers, out-of-range scores),
# not business anomalies, which belong in dbt tests further downstream.
# ---------------------------------------------------------------------------

def _blank(series: pd.Series) -> pd.Series:
    """True where a value is missing or whitespace-only."""
    return series.isna() | (series.astype(str).str.strip() == "")


def _not_numeric(series: pd.Series, allow_negative: bool = False) -> pd.Series:
    """True where a value will not parse as a number (or is negative)."""
    parsed = pd.to_numeric(series, errors="coerce")
    bad = parsed.isna()
    if not allow_negative:
        bad = bad | (parsed < 0)
    return bad


def invalid_orders(df: pd.DataFrame) -> pd.Series:
    return _blank(df["order_id"]) | _blank(df["customer_id"]) | _blank(df["order_status"])


def invalid_order_items(df: pd.DataFrame) -> pd.Series:
    return (
        _blank(df["order_id"])
        | _blank(df["product_id"])
        | _blank(df["seller_id"])
        | _not_numeric(df["price"])
        | _not_numeric(df["freight_value"])
    )


def invalid_customers(df: pd.DataFrame) -> pd.Series:
    return _blank(df["customer_id"]) | _blank(df["customer_unique_id"])


def invalid_products(df: pd.DataFrame) -> pd.Series:
    return _blank(df["product_id"])


def invalid_sellers(df: pd.DataFrame) -> pd.Series:
    return _blank(df["seller_id"])


def invalid_payments(df: pd.DataFrame) -> pd.Series:
    return _blank(df["order_id"]) | _not_numeric(df["payment_value"])


def invalid_reviews(df: pd.DataFrame) -> pd.Series:
    score = pd.to_numeric(df["review_score"], errors="coerce")
    return (
        _blank(df["review_id"])
        | _blank(df["order_id"])
        | score.isna()
        | (score < 1)
        | (score > 5)
    )


def invalid_geolocation(df: pd.DataFrame) -> pd.Series:
    return (
        _blank(df["geolocation_zip_code_prefix"])
        | _not_numeric(df["geolocation_lat"], allow_negative=True)
        | _not_numeric(df["geolocation_lng"], allow_negative=True)
    )


def invalid_category_translation(df: pd.DataFrame) -> pd.Series:
    return _blank(df["product_category_name"]) | _blank(df["product_category_name_english"])


# ---------------------------------------------------------------------------
# File -> (target table, validation function)
# ---------------------------------------------------------------------------

FILES = {
    "olist_orders_dataset.csv":              ("raw_orders", invalid_orders),
    "olist_order_items_dataset.csv":         ("raw_order_items", invalid_order_items),
    "olist_customers_dataset.csv":           ("raw_customers", invalid_customers),
    "olist_products_dataset.csv":            ("raw_products", invalid_products),
    "olist_sellers_dataset.csv":             ("raw_sellers", invalid_sellers),
    "olist_order_payments_dataset.csv":      ("raw_order_payments", invalid_payments),
    "olist_order_reviews_dataset.csv":       ("raw_order_reviews", invalid_reviews),
    "olist_geolocation_dataset.csv":         ("raw_geolocation", invalid_geolocation),
    "product_category_name_translation.csv": ("raw_product_category_translation",
                                              invalid_category_translation),
}

EXPECTED_ROWS = {
    "raw_orders": 99_441,
    "raw_order_items": 112_650,
    "raw_customers": 99_441,
    "raw_products": 32_951,
    "raw_sellers": 3_095,
    "raw_order_payments": 103_886,
    "raw_order_reviews": 99_224,
    "raw_geolocation": 1_000_163,
    "raw_product_category_translation": 71,
}


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_table(conn, path: Path, table: str, rule) -> dict:
    # dtype=str keeps everything as text (RAW stays source-faithful) while
    # pandas' default NA handling converts blank cells to NaN -> SQL NULL.
    df = pd.read_csv(path, dtype=str)

    # Snowflake resolves unquoted identifiers to uppercase; matching that here
    # means no quoted identifiers are needed anywhere downstream.
    df.columns = [c.upper() for c in df.columns]

    # Validation rules are written against the original lower-case names.
    lower = df.rename(columns=str.lower)
    is_bad = rule(lower)

    good = df.loc[~is_bad].reset_index(drop=True)
    bad = df.loc[is_bad].reset_index(drop=True)

    write_pandas(conn, good, table.upper(), auto_create_table=True, overwrite=True)
    if len(bad) > 0:
        write_pandas(conn, bad, f"{table}_QUARANTINE".upper(),
                     auto_create_table=True, overwrite=True)

    return {
        "table": table,
        "loaded": len(good),
        "quarantined": len(bad),
        "expected": EXPECTED_ROWS.get(table),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="folder containing the 9 CSVs")
    ap.add_argument("--table", help="load a single table (optional)")
    args = ap.parse_args()

    check_credentials()

    data_dir = Path(args.data_dir)
    conn = snowflake.connector.connect(**CONN)

    print(f"\n{'=' * 64}")
    print(f"BrazilCommerce 360 — RAW ingestion  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"target: {CONN['database']}.{CONN['schema']}  role: {CONN['role']}")
    print(f"{'=' * 64}")

    results: list[dict] = []
    try:
        for fname, (table, rule) in FILES.items():
            if args.table and table != args.table:
                continue

            fpath = data_dir / fname
            if not fpath.exists():
                print(f"  ! {fname} not found — skipping")
                continue

            r = load_table(conn, fpath, table, rule)
            results.append(r)

            total = r["loaded"] + r["quarantined"]
            mismatch = r["expected"] is not None and total != r["expected"]
            flag = "   <-- ROW COUNT MISMATCH" if mismatch else ""
            print(f"  {table:35s} loaded {r['loaded']:>9,}"
                  f"  quarantined {r['quarantined']:>5,}{flag}")
    finally:
        conn.close()

    total_q = sum(r["quarantined"] for r in results)
    print(f"{'-' * 64}")
    print(f"Done. {len(results)} tables, {total_q:,} rows quarantined.\n")

    if total_q:
        print("Inspect quarantined rows, e.g.:")
        print("  SELECT * FROM ECOMMERCE.RAW.RAW_ORDER_ITEMS_QUARANTINE LIMIT 20;\n")


if __name__ == "__main__":
    main()

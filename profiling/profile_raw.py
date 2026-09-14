"""
Automated profiling of the RAW layer.

Generates one HTML report per source table covering completeness, cardinality,
distributions and correlations for every column, so the targeted SQL checks
only have to answer what a single-table profiler cannot.

Why automated profiling rather than hand-written SQL:
  * one command covers every column, so nothing is silently skipped
  * the output is a reproducible artefact that can be committed and reviewed
  * hand-written checks then focus on cross-table questions a single-table
    profiler cannot answer (orphans, missing lookups, timing anomalies)

Sampling: the geolocation table has 1M rows. Profiling it in full is slow and
adds nothing, so it is sampled. Every other table is profiled in full.

Usage:
    pip install -r requirements.txt
    python profile_raw.py                 # profile all tables
    python profile_raw.py --table raw_orders
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

try:
    from ydata_profiling import ProfileReport
except ImportError:
    sys.exit(
        "\nydata-profiling is not installed.\n"
        "Run: pip install ydata-profiling\n"
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

CONN = dict(
    account=os.environ.get("SNOWFLAKE_ACCOUNT"),
    user=os.environ.get("SNOWFLAKE_USER"),
    password=os.environ.get("SNOWFLAKE_PASSWORD"),
    role=os.environ.get("SNOWFLAKE_ROLE", "transformer"),
    warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "ECOMMERCE_WH"),
    database=os.environ.get("SNOWFLAKE_DATABASE", "ECOMMERCE_DEV"),
    schema=os.environ.get("SNOWFLAKE_SCHEMA", "RAW"),
)

OUTPUT_DIR = PROJECT_ROOT / "docs" / "profiling"

# table -> row limit (None = profile every row)
TABLES = {
    "raw_orders": None,
    "raw_order_items": None,
    "raw_customers": None,
    "raw_products": None,
    "raw_sellers": None,
    "raw_order_payments": None,
    "raw_order_reviews": None,
    "raw_geolocation": 100_000,   # 1M rows; a sample is representative here
    "raw_product_category_translation": None,
}


def check_credentials() -> None:
    missing = [k for k in ("account", "user", "password") if not CONN.get(k)]
    if missing:
        keys = ", ".join(f"SNOWFLAKE_{m.upper()}" for m in missing)
        sys.exit(f"\nMissing credentials: {keys}\nFill in .env at the project root.\n")


def fetch(conn, table: str, limit: int | None) -> pd.DataFrame:
    sql = f"SELECT * FROM {CONN['database']}.{CONN['schema']}.{table}"
    if limit:
        sql += f" SAMPLE ({limit} ROWS)"
    cur = conn.cursor()
    try:
        cur.execute(sql)
        return cur.fetch_pandas_all()
    finally:
        cur.close()


def profile(df: pd.DataFrame, table: str, sampled: bool) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{table}.html"

    title = f"{table} — profile"
    if sampled:
        title += " (sampled)"

    # minimal=True skips expensive correlation matrices, which are meaningless
    # on all-VARCHAR RAW tables anyway.
    report = ProfileReport(df, title=title, minimal=True)
    report.to_file(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", help="profile a single table")
    args = ap.parse_args()

    check_credentials()
    conn = snowflake.connector.connect(**CONN)

    print(f"\n{'=' * 64}")
    print(f"RAW profiling  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"source: {CONN['database']}.{CONN['schema']}")
    print(f"{'=' * 64}")

    try:
        for table, limit in TABLES.items():
            if args.table and table != args.table:
                continue

            df = fetch(conn, table, limit)
            out = profile(df, table, sampled=limit is not None)
            note = "  (sampled)" if limit else ""
            print(f"  {table:35s} {len(df):>9,} rows -> {out.name}{note}")
    finally:
        conn.close()

    print(f"{'-' * 64}")
    print(f"Reports written to {OUTPUT_DIR}\n")


if __name__ == "__main__":
    main()

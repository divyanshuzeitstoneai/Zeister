"""src/generators/validate_and_merge.py — Schema validation and merge for Zeitster datasets.

Validates that generated zeitster_* tables are schema-compatible with existing
category3_* tables, checks for ID collisions, and verifies edge-case coverage.

Steps:
  1. Load both zeitster_* and category3_* tables
  2. Compare column names exactly for overlapping tables
  3. Check for colliding IDs (order_id, customer_id, test_case_id)
  4. Spot-check that every claimed edge-case test_case_id has matching rows
  5. Report results (pass/fail per check)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")

# Mapping of category3 table names to their zeitster equivalents
# Only tables that exist in BOTH sets need schema comparison
TABLE_PAIRS = {
    "customers": ("category3_customers.csv.gz", "zeitster_customers.csv.gz"),
    "orders": ("category3_orders.csv.gz", "zeitster_orders.csv.gz"),
    "line_items": ("category3_line_items.csv.gz", "zeitster_line_items.csv.gz"),
    "subscriptions": ("category3_subscriptions.csv.gz", "zeitster_subscriptions.csv.gz"),
    "subscription_events": ("category3_subscription_events.csv.gz", "zeitster_subscription_events.csv.gz"),
    "support_tickets": ("category3_support_tickets.csv.gz", "zeitster_support_tickets.csv.gz"),
}

# Expected edge-case prefixes (from the dataset generation spec)
EDGE_CASE_PREFIXES = [
    "EC02-BOUNDARY",
    "EC03-FALLBACK",
    "EC04-NO-FALLBACK",
    "EC05-PRECUTOVER",
    "EC06-POSTCUTOVER",
    "EC07-PARTIAL-REFUND",
    "EC08-FULL-CANCEL",
    "EC09-MULTI-LINEITEM",
    "EC10-CROSS-CHANNEL",
    "EC11-LATE-EXTERNAL",
    "EC12-CHURN",
    "EC13-DISPUTE",
    "EC14-ORPHAN",
]


def load_table(filename: str) -> pd.DataFrame | None:
    """Load a CSV table from the data directory. Returns None if not found."""
    path = DATA_DIR / filename
    if not path.exists():
        return None
    if filename.endswith(".gz"):
        return pd.read_csv(path, compression="gzip")
    return pd.read_csv(path)


def check_schema_compatibility() -> list[str]:
    """Compare column names between category3_* and zeitster_* tables.

    Returns a list of issues found. Empty = all good.
    """
    issues = []

    for table_name, (cat3_file, zeit_file) in TABLE_PAIRS.items():
        cat3_df = load_table(cat3_file)
        zeit_df = load_table(zeit_file)

        if cat3_df is None:
            logger.warning("  %s: category3 file not found, skipping", table_name)
            continue
        if zeit_df is None:
            logger.warning("  %s: zeitster file not found, skipping", table_name)
            continue

        cat3_cols = set(cat3_df.columns)
        zeit_cols = set(zeit_df.columns)

        # Columns in category3 but not in zeitster
        missing_in_zeit = cat3_cols - zeit_cols
        if missing_in_zeit:
            issues.append(
                f"[{table_name}] Columns in category3 but MISSING in zeitster: {sorted(missing_in_zeit)}"
            )

        # Columns in zeitster but not in category3 (informational — new schema is a superset)
        extra_in_zeit = zeit_cols - cat3_cols
        if extra_in_zeit:
            logger.info(
                "  [%s] New columns in zeitster (expected superset): %s",
                table_name, sorted(extra_in_zeit),
            )

    return issues


def check_id_collisions() -> list[str]:
    """Check for colliding IDs between category3_* and zeitster_* tables."""
    issues = []

    id_checks = [
        ("orders", "order_id", "category3_orders.csv.gz", "zeitster_orders.csv.gz"),
        ("customers", "customer_id", "category3_customers.csv.gz", "zeitster_customers.csv.gz"),
        ("subscriptions", "subscription_id", "category3_subscriptions.csv.gz", "zeitster_subscriptions.csv.gz"),
    ]

    for table_name, id_col, cat3_file, zeit_file in id_checks:
        cat3_df = load_table(cat3_file)
        zeit_df = load_table(zeit_file)

        if cat3_df is None or zeit_df is None:
            continue

        if id_col not in cat3_df.columns or id_col not in zeit_df.columns:
            continue

        cat3_ids = set(cat3_df[id_col].dropna())
        zeit_ids = set(zeit_df[id_col].dropna())
        collisions = cat3_ids & zeit_ids

        if collisions:
            issues.append(
                f"[{table_name}] {len(collisions)} colliding {id_col} values: "
                f"{sorted(list(collisions))[:10]}..."
            )
        else:
            logger.info("  [%s] No %s collisions ✓", table_name, id_col)

    return issues


def check_edge_case_coverage() -> list[str]:
    """Verify that every required edge-case type has actual rows in the data."""
    issues = []

    # Check edge cases in orders and line_items (primary tables)
    for table_file in ["zeitster_orders.csv.gz", "zeitster_line_items.csv.gz"]:
        df = load_table(table_file)
        if df is None:
            issues.append(f"Cannot check edge cases: {table_file} not found")
            continue

        if "test_case_id" not in df.columns:
            issues.append(f"[{table_file}] Missing test_case_id column!")
            continue

        all_ids = set(df["test_case_id"].dropna().astype(str))
        for prefix in EDGE_CASE_PREFIXES:
            matching = [tid for tid in all_ids if tid.startswith(prefix)]
            if not matching:
                issues.append(
                    f"[{table_file}] MISSING edge case type: {prefix} (no matching test_case_ids)"
                )
            elif len(matching) < 3:
                issues.append(
                    f"[{table_file}] LOW coverage for {prefix}: only {len(matching)} rows"
                )
            else:
                logger.info("  [%s] %s: %d rows ✓", table_file, prefix, len(matching))

    return issues


def check_null_rates() -> list[str]:
    """Spot-check that null rates roughly match field-status classifications."""
    issues = []

    orders = load_table("zeitster_orders.csv.gz")
    if orders is None:
        return ["Cannot check null rates: zeitster_orders.csv.gz not found"]

    total = len(orders)
    checks = [
        ("actual_shipping_cost", 0.03, 0.25, "❌ EXTERNAL ~5-10%"),
        ("gateway_fee", 0.05, 0.35, "⚠️ PARTIAL ~15-20%"),
    ]

    for col, min_rate, max_rate, label in checks:
        if col not in orders.columns:
            issues.append(f"Missing column {col} in orders")
            continue
        null_rate = orders[col].isna().mean()
        if null_rate < min_rate or null_rate > max_rate:
            issues.append(
                f"[orders.{col}] Null rate {null_rate:.1%} outside expected range "
                f"{min_rate:.0%}-{max_rate:.0%} ({label})"
            )
        else:
            logger.info("  [orders.%s] Null rate %.1f%% ✓ (%s)", col, null_rate * 100, label)

    return issues


def check_referential_integrity() -> list[str]:
    """Check that foreign keys resolve (except explicitly tagged orphans)."""
    issues = []

    orders = load_table("zeitster_orders.csv.gz")
    line_items = load_table("zeitster_line_items.csv.gz")

    if orders is None or line_items is None:
        return ["Cannot check referential integrity: tables not found"]

    order_ids = set(orders["order_id"])

    # Line items pointing to non-existent orders (excluding tagged orphans)
    non_orphan_lis = line_items[~line_items["test_case_id"].str.startswith("EC14-ORPHAN", na=False)]
    missing_orders = set(non_orphan_lis["order_id"]) - order_ids
    if missing_orders:
        issues.append(
            f"[line_items] {len(missing_orders)} non-orphan line items reference missing orders: "
            f"{sorted(list(missing_orders))[:5]}..."
        )
    else:
        logger.info("  [line_items → orders] Referential integrity OK ✓")

    # Verify orphan rows ARE actually orphaned
    orphan_lis = line_items[line_items["test_case_id"].str.startswith("EC14-ORPHAN", na=False)]
    orphan_valid = set(orphan_lis["order_id"]) - order_ids
    if len(orphan_lis) > 0 and len(orphan_valid) == 0:
        issues.append("[line_items] EC14-ORPHAN rows are NOT actually orphaned (orders exist)")
    elif len(orphan_lis) > 0:
        logger.info("  [line_items] EC14-ORPHAN rows correctly orphaned ✓ (%d rows)", len(orphan_valid))

    return issues


def run_all_checks() -> bool:
    """Run all validation checks. Returns True if all pass."""
    print("\n" + "=" * 70)
    print("ZEITSTER DATASET VALIDATION REPORT")
    print("=" * 70)

    all_issues = []

    print("\n--- 1. Schema Compatibility ---")
    all_issues.extend(check_schema_compatibility())

    print("\n--- 2. ID Collision Check ---")
    all_issues.extend(check_id_collisions())

    print("\n--- 3. Edge Case Coverage ---")
    all_issues.extend(check_edge_case_coverage())

    print("\n--- 4. Null Rate Validation ---")
    all_issues.extend(check_null_rates())

    print("\n--- 5. Referential Integrity ---")
    all_issues.extend(check_referential_integrity())

    print("\n" + "=" * 70)
    if all_issues:
        print(f"VALIDATION RESULT: {len(all_issues)} ISSUES FOUND")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
        print("=" * 70)
        return False
    else:
        print("VALIDATION RESULT: ALL CHECKS PASSED ✓")
        print("=" * 70)
        return True


if __name__ == "__main__":
    success = run_all_checks()
    sys.exit(0 if success else 1)

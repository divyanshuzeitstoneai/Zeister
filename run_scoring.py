"""Scoring pipeline runner."""

import logging
import sys

import pandas as pd

from src.data_clean import clean_pipeline
from src.scoring.f01_f03 import compute_f03, aggregate_f03, compute_f01, aggregate_f01
from src.scoring.f05 import compute_f05, aggregate_f05

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/synthetic_1m_orders_clean.csv.gz"

df = pd.read_csv(DATA_PATH, compression="gzip")
logger.info("Loaded %s rows from %s", f"{len(df):,}", DATA_PATH)

df = clean_pipeline(df, recompute_targets=True)
logger.info("After cleaning: %s rows", f"{len(df):,}")

active = df[~df["is_returned"]].copy()
logger.info("Excluded %s refunded orders (%.1f%%)",
            f"{df['is_returned'].sum():,}",
            df["is_returned"].sum() / len(df) * 100)

scored = compute_f03(active)
f03_result = aggregate_f03(scored)

print("\n" + "=" * 60)
print("F03 — Margin Floor Breach")
print("=" * 60)
print(f"  Orders evaluated:  {f03_result['orders_evaluated']:,}")
print(f"  Orders flagged:    {f03_result['orders_flagged']:,} ({f03_result['breach_rate_pct']:.2f}%)")
print(f"  Total loss:        ${f03_result['total_loss']:,.2f}")

f01_scored = compute_f01(active)
f01_result = aggregate_f01(f01_scored)

print("\n" + "=" * 60)
print("F01 — Promotion Margin Leakage")
print("=" * 60)
print(f"  Orders evaluated:  {f01_result['orders_evaluated']:,}")
print(f"  Discounted orders: {f01_result['discounted_orders']:,}")
print(f"  Orders flagged:    {f01_result['orders_flagged']:,} (F01 Score: {f01_result['f01_score_pct']:.2f}% of total orders, {f01_result['discounted_breach_rate_pct']:.2f}% of promo orders)")
print(f"  Total promo loss:  ${f01_result['total_loss']:,.2f}")

f05_scored = compute_f05(active)
f05_result = aggregate_f05(f05_scored)

print("\n" + "=" * 60)
print("F05 — Shipping Cost Recovery")
print("=" * 60)
print(f"  Orders evaluated:       {f05_result['orders_evaluated']:,}")
print(f"  Orders with surplus:    {f05_result['orders_surplus']:,}")
print(f"  Orders with deficit:    {f05_result['orders_deficit']:,}")
print(f"  Total surplus:          ${f05_result['total_surplus']:,.2f}")
print(f"  Total deficit:          ${f05_result['total_deficit']:,.2f}")
print(f"  Net shipping position:  ${f05_result['net_shipping_position']:,.2f}")

print("\n" + "=" * 60)
print("Done.")
print("=" * 60)
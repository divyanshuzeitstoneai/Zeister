"""run_scoring.py — Full scoring pipeline: clean → F03 → F01 → F05.

Usage:
    python run_scoring.py                           # uses cleaned dataset
    python run_scoring.py data/synthetic_1m_orders.csv.gz  # cleans on the fly
"""

import logging
import sys

import pandas as pd

from src.data_clean import clean_pipeline
from src.scoring.f01_f03 import compute_f03, compute_f01, aggregate_losses
from src.scoring.f05 import compute_f05, aggregate_f05

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load and clean
# ---------------------------------------------------------------------------

DATA_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/synthetic_1m_orders_clean.csv.gz"

df = pd.read_csv(DATA_PATH, compression="gzip")
logger.info("Loaded %s rows from %s", f"{len(df):,}", DATA_PATH)

# If using the raw dataset, clean on the fly; if using _clean, this is ~a no-op
df = clean_pipeline(df, recompute_targets=True)
logger.info("After cleaning: %s rows", f"{len(df):,}")

# ---------------------------------------------------------------------------
# Exclude returns
# ---------------------------------------------------------------------------

active = df[~df["is_returned"]].copy()
logger.info("Excluded %s refunded orders (%.1f%%)",
            f"{df['is_returned'].sum():,}",
            df["is_returned"].sum() / len(df) * 100)

# ---------------------------------------------------------------------------
# F03 — Margin Floor Breach
# ---------------------------------------------------------------------------

scored = compute_f03(active)
f03_result = aggregate_losses(scored, loss_col="f03_loss", flag_col="f03_breach")

print("\n" + "=" * 60)
print("F03 — Margin Floor Breach")
print("=" * 60)
print(f"  Orders evaluated:  {f03_result['orders_evaluated']:,}")
print(f"  Orders flagged:    {f03_result['orders_flagged']:,} "
      f"({f03_result['orders_flagged']/f03_result['orders_evaluated']*100:.2f}%)")
print(f"  Total loss:        ${f03_result['total_loss']:,.2f}")

# ---------------------------------------------------------------------------
# F01 — Promotion Margin Leakage (discounted orders only)
# ---------------------------------------------------------------------------

disc = scored[scored["is_discounted"]].copy()
disc = compute_f01(disc)
f01_result = aggregate_losses(disc, loss_col="f01_loss", flag_col="f01_flagged")

print("\n" + "=" * 60)
print("F01 — Promotion Margin Leakage")
print("=" * 60)
print(f"  Discounted orders: {f01_result['orders_evaluated']:,}")
print(f"  Orders flagged:    {f01_result['orders_flagged']:,} "
      f"({f01_result['orders_flagged']/f01_result['orders_evaluated']*100:.2f}%)")
print(f"  Total loss:        ${f01_result['total_loss']:,.2f}")

# ---------------------------------------------------------------------------
# F05 — Shipping Cost Recovery (all orders, net aggregation)
# ---------------------------------------------------------------------------

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
"""src/data_clean.py — Data-integrity pipeline: dedup, validation, COGS policy.

Run standalone:
    python -m src.data_clean data/synthetic_1m_orders.csv.gz data/synthetic_1m_orders_clean.csv.gz

Or import the functions into any pipeline script.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np
import pandas as pd

from src.config import COGS_POLICY, TARGET_MARGINS, DEFAULT_TARGET_MARGIN, REQUIRED_ORDER_COLUMNS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1.5 — Deduplication
# ---------------------------------------------------------------------------

def dedup_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate ``order_id`` rows, keeping the first occurrence.

    Logs the number of rows dropped so the caller can audit the impact.
    """
    n_before = len(df)
    df = df.drop_duplicates(subset="order_id", keep="first")
    n_dropped = n_before - len(df)
    if n_dropped > 0:
        logger.warning("Dropped %d duplicate order_id rows (%.2f%% of input)",
                        n_dropped, n_dropped / n_before * 100)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_required_columns(df: pd.DataFrame,
                               columns: list[str] | None = None) -> pd.DataFrame:
    """Assert that *columns* exist and contain no nulls.

    Parameters
    ----------
    df : DataFrame
    columns : list of column names.  Defaults to ``REQUIRED_ORDER_COLUMNS``.

    Returns
    -------
    df (unchanged) — raises ``ValueError`` if validation fails.
    """
    columns = columns or REQUIRED_ORDER_COLUMNS
    missing_cols = [c for c in columns if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    for col in columns:
        n_null = df[col].isna().sum()
        if n_null > 0:
            raise ValueError(
                f"Column '{col}' has {n_null:,} null values — "
                f"this column must not contain nulls."
            )
    return df


# ---------------------------------------------------------------------------
# 1.4 — COGS policy
# ---------------------------------------------------------------------------

def apply_cogs_policy(df: pd.DataFrame,
                       policy: Literal["exclude", "impute_category_avg"] | None = None,
                       ) -> pd.DataFrame:
    """Handle rows where ``cogs_total`` is null.

    Parameters
    ----------
    policy : ``"exclude"`` drops rows; ``"impute_category_avg"`` fills nulls
             with the category-level average COGS.  Defaults to
             ``config.COGS_POLICY``.
    """
    policy = policy or COGS_POLICY
    n_null = df["cogs_total"].isna().sum()
    if n_null == 0:
        return df

    if policy == "exclude":
        logger.info("COGS policy 'exclude': dropping %d rows (%.1f%%) with null cogs_total",
                     n_null, n_null / len(df) * 100)
        return df.dropna(subset=["cogs_total"]).reset_index(drop=True)

    if policy == "impute_category_avg":
        # Compute category-average COGS from rows that DO have a value
        cat_avg = df.groupby("category")["cogs_total"].transform("mean")
        global_avg = df["cogs_total"].mean()
        imputed = df["cogs_total"].fillna(cat_avg).fillna(global_avg)
        n_imputed = imputed.notna().sum() - df["cogs_total"].notna().sum()
        logger.info("COGS policy 'impute_category_avg': imputed %d rows", n_imputed)
        df = df.copy()
        df["cogs_total"] = imputed
        df["cogs_imputed"] = df.index.isin(
            df.index[df["cogs_total"].isna()]  # mark the ones we just filled
        )
        return df

    raise ValueError(f"Unknown COGS policy: {policy!r}")


# ---------------------------------------------------------------------------
# 1.3 — Consistent target-min-profit
# ---------------------------------------------------------------------------

def recompute_target_min_profit(df: pd.DataFrame,
                                 margins: dict[str, float] | None = None,
                                 default: float | None = None) -> pd.DataFrame:
    """(Re)compute ``target_min_profit`` from ``selling_price`` × category margin.

    Uses ``config.TARGET_MARGINS`` and ``config.DEFAULT_TARGET_MARGIN``
    unless overridden.
    """
    margins = margins or TARGET_MARGINS
    default = default if default is not None else DEFAULT_TARGET_MARGIN
    df = df.copy()
    df["target_min_profit"] = df.apply(
        lambda row: row["selling_price"] * margins.get(row["category"], default),
        axis=1,
    )
    return df


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def clean_pipeline(df: pd.DataFrame,
                    cogs_policy: str | None = None,
                    recompute_targets: bool = True) -> pd.DataFrame:
    """Run the full cleaning pipeline in order.

    1. Dedup on ``order_id``
    2. Validate required columns
    3. Apply COGS policy
    4. Optionally recompute ``target_min_profit`` from config

    Returns the cleaned DataFrame.
    """
    df = dedup_orders(df)
    validate_required_columns(df)
    df = apply_cogs_policy(df, policy=cogs_policy)
    if recompute_targets:
        df = recompute_target_min_profit(df)
    return df


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    in_path = sys.argv[1] if len(sys.argv) > 1 else "data/synthetic_1m_orders.csv.gz"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data/synthetic_1m_orders_clean.csv.gz"

    logger.info("Reading %s ...", in_path)
    raw = pd.read_csv(in_path, compression="gzip")
    logger.info("Loaded %d rows", len(raw))

    cleaned = clean_pipeline(raw)
    logger.info("Cleaned dataset: %d rows", len(cleaned))

    cleaned.to_csv(out_path, index=False, compression="gzip")
    logger.info("Written to %s", out_path)

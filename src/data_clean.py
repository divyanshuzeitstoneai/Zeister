"""src/data_clean.py — Data-integrity pipeline: dedup, validation, COGS policy."""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np
import pandas as pd

from src.config import COGS_POLICY, TARGET_MARGINS, DEFAULT_TARGET_MARGIN, REQUIRED_ORDER_COLUMNS

logger = logging.getLogger(__name__)


def dedup_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate order_id rows, keeping the first occurrence."""
    n_before = len(df)
    df = df.drop_duplicates(subset="order_id", keep="first")
    n_dropped = n_before - len(df)
    if n_dropped > 0:
        logger.warning("Dropped %d duplicate order_id rows (%.2f%% of input)",
                        n_dropped, n_dropped / n_before * 100)
    return df.reset_index(drop=True)


def validate_required_columns(df: pd.DataFrame,
                               columns: list[str] | None = None) -> pd.DataFrame:
    """Assert that required columns exist and contain no nulls."""
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


def apply_cogs_policy(df: pd.DataFrame,
                       policy: Literal["exclude", "impute_category_avg"] | None = None,
                       ) -> pd.DataFrame:
    """Handle rows where cogs_total is null and flag estimated COGS."""
    policy = policy or COGS_POLICY
    df = df.copy()
    
    if "is_cogs_estimated" not in df.columns:
        df["is_cogs_estimated"] = False

    n_null = df["cogs_total"].isna().sum()
    if n_null == 0:
        return df

    if policy == "exclude":
        logger.info("COGS policy 'exclude': dropping %d rows (%.1f%%) with null cogs_total",
                     n_null, n_null / len(df) * 100)
        return df.dropna(subset=["cogs_total"]).reset_index(drop=True)

    if policy == "impute_category_avg":
        missing_mask = df["cogs_total"].isna()
        if "category" in df.columns:
            cat_avg = df.groupby("category")["cogs_total"].transform("mean")
        else:
            cat_avg = pd.Series(np.nan, index=df.index)
        
        global_avg = df["cogs_total"].mean()
        # Fallback to category average, then global average
        imputed = df["cogs_total"].fillna(cat_avg).fillna(global_avg)
        
        df["cogs_total"] = imputed
        df["is_cogs_estimated"] = missing_mask
        df["cogs_imputed"] = missing_mask  # backward compatibility alias
        return df

    raise ValueError(f"Unknown COGS policy: {policy!r}")


def recompute_target_min_profit(df: pd.DataFrame,
                                 margins: dict[str, float] | None = None,
                                 default: float | None = None) -> pd.DataFrame:
    """Computes target_min_profit using NET SELLING PRICE after discounts."""
    margins = margins or TARGET_MARGINS
    default = default if default is not None else DEFAULT_TARGET_MARGIN
    df = df.copy()
    
    price_col = (
        "net_selling_price"
        if "net_selling_price" in df.columns
        else ("net_sales" if "net_sales" in df.columns else "selling_price")
    )
    
    df["target_min_profit"] = df.apply(
        lambda row: row[price_col] * margins.get(row["category"], default) if "category" in row else row[price_col] * default,
        axis=1,
    )
    return df


def clean_pipeline(df: pd.DataFrame,
                    cogs_policy: str | None = None,
                    recompute_targets: bool = True) -> pd.DataFrame:
    """Run data cleaning and normalization pipeline."""
    df = dedup_orders(df)
    validate_required_columns(df)
    df = apply_cogs_policy(df, policy=cogs_policy)
    if recompute_targets:
        df = recompute_target_min_profit(df)
    return df

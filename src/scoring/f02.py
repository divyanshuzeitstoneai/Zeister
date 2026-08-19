"""src/scoring/f02.py — F02: Discount Dependency Score.

Business Definition:
    F02 measures the percentage of sales revenue coming from discounted orders
    and evaluates whether the store is excessively dependent on discounts.

Formulas:
    discounted_sales_share = total_discounted_sales / total_sales
    f02_score_pct = discounted_sales_share * 100.0
    excess_discount_share = max(0.0, discounted_sales_share - healthy_discount_share)
    avg_discount_depth = total_discount_given / total_discounted_sales (if discounted_sales > 0 else 0)
    f02_loss = total_sales * excess_discount_share * avg_discount_depth
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import HEALTHY_DISCOUNT_SHARE


def compute_f02(
    df_orders: pd.DataFrame, 
    df_line_items: pd.DataFrame,
    healthy_share: float | None = None,
) -> dict:
    """Computes store-level F02 Discount Dependency.

    Parameters:
        df_orders: Order-level DataFrame (active/completed orders)
        df_line_items: Line-item level DataFrame
        healthy_share: Benchmark threshold (default: config.HEALTHY_DISCOUNT_SHARE, 0.20)

    Returns:
        Dictionary containing metric breakdown, percentage scores, and financial loss.
    """
    healthy_share = healthy_share if healthy_share is not None else HEALTHY_DISCOUNT_SHARE

    # Filter out cancelled orders if present
    if "is_cancelled" in df_orders.columns:
        valid_order_ids = set(df_orders[~df_orders["is_cancelled"]]["order_id"])
        items = df_line_items[df_line_items["order_id"].isin(valid_order_ids)].copy()
    else:
        items = df_line_items.copy()

    total_gross_sales = float(items["selling_price"].sum()) if "selling_price" in items.columns else 0.0
    if total_gross_sales <= 0.0:
        return {
            "total_sales": 0.0,
            "discounted_sales": 0.0,
            "discounted_share": 0.0,
            "f02_score_pct": 0.0,
            "healthy_benchmark": healthy_share,
            "excess_share": 0.0,
            "is_breached": False,
            "avg_discount_depth": 0.0,
            "total_discount_given": 0.0,
            "f02_loss": 0.0,
        }

    # Determine discounted items
    if "is_discounted" in items.columns:
        disc_mask = items["is_discounted"]
    elif "discount_given" in items.columns:
        disc_mask = items["discount_given"] > 0
    else:
        disc_mask = pd.Series(False, index=items.index)

    disc_items = items[disc_mask]
    total_disc_sales = float(disc_items["selling_price"].sum())
    total_disc_given = float(disc_items["discount_given"].sum()) if "discount_given" in disc_items.columns else 0.0

    discounted_share = total_disc_sales / total_gross_sales
    f02_score_pct = discounted_share * 100.0
    avg_discount_depth = (total_disc_given / total_disc_sales) if total_disc_sales > 0 else 0.0

    excess_share = max(0.0, discounted_share - healthy_share)
    f02_loss = float(total_gross_sales * excess_share * avg_discount_depth)

    return {
        "total_sales": total_gross_sales,
        "discounted_sales": total_disc_sales,
        "discounted_share": discounted_share,
        "f02_score_pct": f02_score_pct,
        "healthy_benchmark": healthy_share,
        "excess_share": excess_share,
        "is_breached": discounted_share > healthy_share,
        "avg_discount_depth": avg_discount_depth,
        "total_discount_given": total_disc_given,
        "f02_loss": f02_loss,
    }

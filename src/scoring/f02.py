"""F02: Discount Dependency Score."""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import HEALTHY_DISCOUNT_SHARE


def compute_f02(
    df_orders: pd.DataFrame, 
    df_line_items: pd.DataFrame,
    healthy_share: float | None = None,
) -> dict:
    """Computes store-level F02 Discount Dependency score and excess loss."""
    healthy_share = healthy_share if healthy_share is not None else HEALTHY_DISCOUNT_SHARE

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

    if "is_discounted" in items.columns:
        order_has_disc = items.groupby("order_id")["is_discounted"].any()
    elif "discount_given" in items.columns:
        order_has_disc = items.groupby("order_id")["discount_given"].sum() > 0
    else:
        order_has_disc = pd.Series(False, index=items["order_id"].unique())

    disc_order_ids = set(order_has_disc[order_has_disc].index)

    disc_sales = float(items[items["order_id"].isin(disc_order_ids)]["selling_price"].sum())
    discounted_share = disc_sales / total_gross_sales
    f02_score_pct = discounted_share * 100.0

    total_disc_given = float(items["discount_given"].sum()) if "discount_given" in items.columns else 0.0
    avg_discount_depth = (total_disc_given / disc_sales) if disc_sales > 0 else 0.0

    excess_share = max(0.0, discounted_share - healthy_share)
    is_breached = excess_share > 0.0
    f02_loss = total_gross_sales * excess_share * avg_discount_depth

    return {
        "total_sales": total_gross_sales,
        "discounted_sales": disc_sales,
        "discounted_share": discounted_share,
        "f02_score_pct": f02_score_pct,
        "healthy_benchmark": healthy_share,
        "excess_share": excess_share,
        "is_breached": is_breached,
        "avg_discount_depth": avg_discount_depth,
        "total_discount_given": total_disc_given,
        "f02_loss": f02_loss,
    }

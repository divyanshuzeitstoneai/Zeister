"""src/scoring/f02.py — F02: Discount Dependency Score.

Formula:
    discounted_sales_share = total_discounted_sales / total_sales
    excess_discount_share = max(0, discounted_sales_share - healthy_discount_share)
    f02_loss = total_sales * excess_discount_share * avg_discount_depth

Evaluates store-level discount dependency and financial loss from subsidizing normal volume.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from src.config import HEALTHY_DISCOUNT_SHARE


def compute_f02(df_orders: pd.DataFrame, 
                df_line_items: pd.DataFrame,
                healthy_share: float | None = None) -> dict:
    """Computes store-level F02 Discount Dependency.

    Parameters:
        df_orders: Order-level DataFrame (active/completed orders)
        df_line_items: Line-item level DataFrame
        healthy_share: Benchmark threshold (default: config.HEALTHY_DISCOUNT_SHARE)

    Returns:
        Dictionary containing metric breakdown and financial loss.
    """
    healthy_share = healthy_share if healthy_share is not None else HEALTHY_DISCOUNT_SHARE

    # Filter out cancelled orders
    if "is_cancelled" in df_orders.columns:
        valid_orders = df_orders[~df_orders["is_cancelled"]]["order_id"]
        items = df_line_items[df_line_items["order_id"].isin(valid_orders)].copy()
    else:
        items = df_line_items.copy()

    total_gross_sales = float(items["selling_price"].sum())
    if total_gross_sales <= 0:
        return {
            "total_sales": 0.0,
            "discounted_sales": 0.0,
            "discounted_share": 0.0,
            "healthy_benchmark": healthy_share,
            "is_breached": False,
            "avg_discount_depth": 0.0,
            "f02_loss": 0.0,
        }

    disc_items = items[items["is_discounted"]]
    total_disc_sales = float(disc_items["selling_price"].sum())
    total_disc_given = float(disc_items["discount_given"].sum())

    discounted_share = total_disc_sales / total_gross_sales
    avg_discount_depth = (total_disc_given / total_disc_sales) if total_disc_sales > 0 else 0.0

    excess_share = max(0.0, discounted_share - healthy_share)
    f02_loss = float(total_gross_sales * excess_share * avg_discount_depth)

    return {
        "total_sales": total_gross_sales,
        "discounted_sales": total_disc_sales,
        "discounted_share": discounted_share,
        "healthy_benchmark": healthy_share,
        "is_breached": discounted_share > healthy_share,
        "avg_discount_depth": avg_discount_depth,
        "f02_loss": f02_loss,
    }

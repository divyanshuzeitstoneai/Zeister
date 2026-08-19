"""src/scoring/f10.py — F10: Return & Refund Profitability Score.

Calculates the true financial loss caused by returned products, including lost revenue,
restocking/inspection operational costs, unrecovered shipping, and reverse logistics.

Formula:
    f10_return_loss = refund_amount + restocking_cost + return_shipping_cost + lost_cogs_depreciation
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from src.config import DEFAULT_RESTOCKING_RATE, DEFAULT_RETURN_SHIPPING_FLAT


def compute_f10(df_orders: pd.DataFrame, df_line_items: pd.DataFrame) -> dict:
    """Computes F10 Return & Refund Profitability metrics.

    Parameters:
        df_orders: Order-level DataFrame
        df_line_items: Line-item level DataFrame

    Returns:
        Dictionary containing return loss breakdown across categories and products.
    """
    items = df_line_items.copy()
    
    # Filter to returned items
    returned = items[items["is_returned"]].copy()
    
    if len(returned) == 0:
        return {
            "total_returns": 0,
            "return_rate_pct": 0.0,
            "total_refunded_amount": 0.0,
            "total_restocking_cost": 0.0,
            "total_f10_loss": 0.0,
            "category_return_losses": {},
        }
    
    total_items = len(items)
    return_count = len(returned)
    return_rate = (return_count / total_items) * 100.0
    
    # Restocking cost (fallback to default if 0 or null)
    restocking = returned["restocking_cost"].fillna(0.0)
    restocking = np.where(
        restocking > 0,
        restocking,
        returned["selling_price"] * DEFAULT_RESTOCKING_RATE
    )
    
    # Reverse logistics estimate
    return_shipping = DEFAULT_RETURN_SHIPPING_FLAT
    
    returned["total_item_return_loss"] = returned["refund_amount"].fillna(0.0) + restocking + return_shipping
    
    total_refund = float(returned["refund_amount"].sum())
    total_restock = float(restocking.sum())
    total_loss = float(returned["total_item_return_loss"].sum())
    
    # Category breakdown
    cat_loss = returned.groupby("category")["total_item_return_loss"].sum().to_dict()
    
    return {
        "total_items": total_items,
        "total_returns": return_count,
        "return_rate_pct": return_rate,
        "total_refunded_amount": total_refund,
        "total_restocking_cost": total_restock,
        "total_f10_loss": total_loss,
        "category_return_losses": cat_loss,
    }

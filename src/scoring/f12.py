"""src/scoring/f12.py — F12: Revenue Leakage Ratio Score.

Aggregates all components of financial loss across the store into a single unified health ratio:
Discounts, Returns/Restocking, Unrecovered Shipping, Payment Gateway Fees, and Chargebacks.

Formula:
    Total Leakage = Total Discounts + Total Return Costs + Unrecovered Shipping Deficit + Gateway Fees + Chargebacks
    Leakage Ratio (%) = (Total Leakage / Gross Sales) * 100
    Revenue Retention (%) = 100 - Leakage Ratio (%)
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def compute_f12(df_orders: pd.DataFrame, df_line_items: pd.DataFrame) -> dict:
    """Computes store-level F12 Revenue Leakage Ratio.

    Parameters:
        df_orders: Order-level DataFrame
        df_line_items: Line-item level DataFrame

    Returns:
        Comprehensive dictionary of financial leaks and overall revenue retention ratio.
    """
    # Active orders (not cancelled)
    orders = df_orders[~df_orders["is_cancelled"]].copy()
    valid_order_ids = set(orders["order_id"])
    items = df_line_items[df_line_items["order_id"].isin(valid_order_ids)].copy()

    total_gross_sales = float(items["selling_price"].sum())
    if total_gross_sales <= 0:
        return {
            "gross_sales": 0.0,
            "total_leakage": 0.0,
            "leakage_ratio_pct": 0.0,
            "revenue_retention_pct": 100.0,
            "leak_breakdown": {},
        }

    # 1. Discount Leakage
    total_discounts = float(items["discount_given"].sum())

    # 2. Return & Refund Costs (Refunded Amount + Restocking)
    returned = items[items["is_returned"]]
    total_refunds = float(returned["refund_amount"].sum())
    total_restocking = float(returned["restocking_cost"].sum())
    total_return_loss = total_refunds + total_restocking

    # 3. Unrecovered Shipping Deficit
    shipping_deficit = np.maximum(
        0.0,
        orders["actual_shipping_cost"] - orders["shipping_charged_to_customer"]
    )
    total_shipping_deficit = float(shipping_deficit.sum())

    # 4. Gateway Fees
    total_gateway_fees = float(orders["gateway_fee"].fillna(0.0).sum())

    # 5. Chargebacks & Disputes
    total_chargebacks = float(orders["chargeback_amount"].fillna(0.0).sum())

    # Total Leakage Sum
    total_leakage = (
        total_discounts
        + total_return_loss
        + total_shipping_deficit
        + total_gateway_fees
        + total_chargebacks
    )

    leakage_ratio_pct = (total_leakage / total_gross_sales) * 100.0
    retention_pct = max(0.0, 100.0 - leakage_ratio_pct)

    return {
        "gross_sales": total_gross_sales,
        "total_leakage": total_leakage,
        "leakage_ratio_pct": leakage_ratio_pct,
        "revenue_retention_pct": retention_pct,
        "leak_breakdown": {
            "discounts": total_discounts,
            "returns_and_restocking": total_return_loss,
            "shipping_deficits": total_shipping_deficit,
            "gateway_fees": total_gateway_fees,
            "chargebacks": total_chargebacks,
        },
    }

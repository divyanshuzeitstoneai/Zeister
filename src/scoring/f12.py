"""F12: Revenue Quality Score."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_f12(df_orders: pd.DataFrame, df_line_items: pd.DataFrame | None = None) -> dict:
    """Computes store-level F12 Revenue Quality Score and drain reconciliation."""
    if "is_cancelled" in df_orders.columns:
        orders = df_orders[~df_orders["is_cancelled"]].copy()
    else:
        orders = df_orders.copy()

    if df_line_items is not None:
        valid_order_ids = set(orders["order_id"]) if "order_id" in orders.columns else None
        if valid_order_ids is not None and "order_id" in df_line_items.columns:
            items = df_line_items[df_line_items["order_id"].isin(valid_order_ids)].copy()
        else:
            items = df_line_items.copy()
        
        if "selling_price" in items.columns:
            total_gross_sales = float(items["selling_price"].sum())
        elif "gross_sales" in orders.columns:
            total_gross_sales = float(orders["gross_sales"].sum())
        else:
            total_gross_sales = 0.0

        if "discount_given" in items.columns:
            total_discounts = float(items["discount_given"].sum())
        elif "net_selling_price" in items.columns and "selling_price" in items.columns:
            total_discounts = float(np.maximum(0.0, items["selling_price"] - items["net_selling_price"]).sum())
        else:
            total_discounts = 0.0
        
        if "is_returned" in items.columns:
            returned = items[items["is_returned"]]
            if "refund_amount" in returned.columns:
                total_refunds = float(returned["refund_amount"].fillna(0.0).sum())
            else:
                price_col = returned["net_selling_price"] if "net_selling_price" in returned.columns else returned.get("selling_price", 0.0)
                total_refunds = float(price_col.sum()) if hasattr(price_col, "sum") else 0.0
            
            total_restocking = float(returned["restocking_cost"].fillna(0.0).sum()) if "restocking_cost" in returned.columns else 0.0
        else:
            total_refunds = float(items["refund_amount"].fillna(0.0).sum()) if "refund_amount" in items.columns else 0.0
            total_restocking = float(items["restocking_cost"].fillna(0.0).sum()) if "restocking_cost" in items.columns else 0.0
        
        total_return_loss = total_refunds + total_restocking
    else:
        if "gross_sales" in orders.columns:
            total_gross_sales = float(orders["gross_sales"].sum())
        elif "selling_price" in orders.columns:
            total_gross_sales = float(orders["selling_price"].sum())
        else:
            total_gross_sales = 0.0

        total_discounts = float(orders["discount_amount"].sum()) if "discount_amount" in orders.columns else 0.0
        total_return_loss = float(orders["refund_amount"].sum()) if "refund_amount" in orders.columns else 0.0

    if total_gross_sales <= 0.0:
        return {
            "gross_sales": 0.0,
            "net_retained_revenue": 0.0,
            "total_leakage": 0.0,
            "revenue_quality_score_pct": 100.0,
            "leakage_ratio_pct": 0.0,
            "revenue_retention_pct": 100.0,
            "leak_breakdown": {
                "discounts": 0.0,
                "returns_and_restocking": 0.0,
                "shipping_deficits": 0.0,
                "gateway_fees": 0.0,
                "chargebacks": 0.0,
            },
        }

    charged_shipping = orders["shipping_charged_to_customer"].fillna(0.0) if "shipping_charged_to_customer" in orders.columns else 0.0
    actual_shipping = orders["actual_shipping_cost"].fillna(0.0) if "actual_shipping_cost" in orders.columns else 0.0
    shipping_deficit = np.maximum(0.0, actual_shipping - charged_shipping)
    total_shipping_deficit = float(shipping_deficit.sum()) if hasattr(shipping_deficit, "sum") else 0.0

    total_gateway_fees = float(orders["gateway_fee"].fillna(0.0).sum()) if "gateway_fee" in orders.columns else 0.0
    total_chargebacks = float(orders["chargeback_amount"].fillna(0.0).sum()) if "chargeback_amount" in orders.columns else 0.0

    total_leakage = (
        total_discounts
        + total_return_loss
        + total_shipping_deficit
        + total_gateway_fees
        + total_chargebacks
    )

    net_retained_revenue = total_gross_sales - total_leakage
    revenue_quality_score_pct = (net_retained_revenue / total_gross_sales) * 100.0
    leakage_ratio_pct = (total_leakage / total_gross_sales) * 100.0

    return {
        "gross_sales": total_gross_sales,
        "net_retained_revenue": net_retained_revenue,
        "total_leakage": total_leakage,
        "revenue_quality_score_pct": revenue_quality_score_pct,
        "leakage_ratio_pct": leakage_ratio_pct,
        "revenue_retention_pct": revenue_quality_score_pct,
        "leak_breakdown": {
            "discounts": total_discounts,
            "returns_and_restocking": total_return_loss,
            "shipping_deficits": total_shipping_deficit,
            "gateway_fees": total_gateway_fees,
            "chargebacks": total_chargebacks,
        },
    }

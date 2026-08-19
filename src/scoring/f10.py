"""src/scoring/f10.py — F10: Product Contribution Score.

Business Definition:
    F10 calculates true product/SKU-level net contribution margin after accounting
    for all direct costs: product revenue, discounts, COGS, customer refunds,
    restocking & inspection costs, reverse logistics (return shipping),
    allocated outbound shipping, and payment gateway fees.

    It proves that a high-gross-revenue SKU can yield low or negative true contribution
    when burdened by high return rates, heavy logistics, or excessive discounting.

Formulas:
    SKU Product Contribution =
        Gross Revenue
        - Discounts Given
        - COGS Total
        - Customer Refunds
        - Restocking & Handling Costs
        - Return Shipping (Reverse Logistics)
        - Allocated Outbound Shipping
        - Allocated Payment Gateway Fees

    SKU Contribution Margin (%) = (SKU Product Contribution / SKU Net Revenue) * 100
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import DEFAULT_RESTOCKING_RATE, DEFAULT_RETURN_SHIPPING_FLAT


def compute_f10(
    df_orders: pd.DataFrame, 
    df_line_items: pd.DataFrame,
    return_shipping_flat: float | None = None,
    default_restocking_rate: float | None = None,
) -> pd.DataFrame:
    """Computes SKU-level F10 Product Contribution.

    Parameters:
        df_orders: Order-level DataFrame (contains order_id, actual_shipping_cost, gateway_fee, is_cancelled)
        df_line_items: Line-item level DataFrame (contains product_id, category, quantity, prices, COGS, returns)
        return_shipping_flat: Flat reverse shipping cost per returned unit (default: config.DEFAULT_RETURN_SHIPPING_FLAT)
        default_restocking_rate: Fallback restocking rate (default: config.DEFAULT_RESTOCKING_RATE)

    Returns:
        DataFrame aggregated per product_id with true contribution margin and full cost breakdown.
    """
    ret_shipping_cost = return_shipping_flat if return_shipping_flat is not None else DEFAULT_RETURN_SHIPPING_FLAT
    restock_rate = default_restocking_rate if default_restocking_rate is not None else DEFAULT_RESTOCKING_RATE

    items = df_line_items.copy()
    
    # Filter out cancelled orders if present
    if "is_cancelled" in df_orders.columns:
        valid_order_ids = set(df_orders[~df_orders["is_cancelled"]]["order_id"])
        items = items[items["order_id"].isin(valid_order_ids)].copy()
        orders = df_orders[df_orders["order_id"].isin(valid_order_ids)].copy()
    else:
        orders = df_orders.copy()

    # Ensure required columns exist
    if "quantity" not in items.columns:
        items["quantity"] = 1
    if "selling_price" not in items.columns:
        items["selling_price"] = items["net_selling_price"] if "net_selling_price" in items.columns else 0.0
    if "discount_given" not in items.columns:
        if "net_selling_price" in items.columns:
            items["discount_given"] = np.maximum(0.0, items["selling_price"] - items["net_selling_price"])
        else:
            items["discount_given"] = 0.0
    if "net_selling_price" not in items.columns:
        items["net_selling_price"] = items["selling_price"] - items["discount_given"]
    if "cogs_total" not in items.columns:
        items["cogs_total"] = 0.0
    if "is_returned" not in items.columns:
        items["is_returned"] = False
    if "refund_amount" not in items.columns:
        items["refund_amount"] = np.where(items["is_returned"], items["net_selling_price"], 0.0)
    if "restocking_cost" not in items.columns:
        items["restocking_cost"] = 0.0

    # Restocking cost calculation for returned items
    calc_restocking = np.where(
        items["is_returned"],
        np.where(items["restocking_cost"] > 0, items["restocking_cost"], items["selling_price"] * restock_rate),
        0.0,
    )
    items["restocking_cost_calc"] = calc_restocking
    items["return_shipping_calc"] = np.where(items["is_returned"], ret_shipping_cost * items["quantity"], 0.0)
    items["refund_amount_calc"] = np.where(items["is_returned"], items["refund_amount"].fillna(items["net_selling_price"]), 0.0)

    # Order-level cost allocation (outbound shipping & gateway fees)
    order_totals = items.groupby("order_id")["net_selling_price"].sum().rename("_order_net_total")
    items = items.merge(order_totals, on="order_id", how="left")
    
    order_costs = orders[["order_id"]].copy()
    order_costs["actual_shipping_cost"] = orders["actual_shipping_cost"].fillna(0.0) if "actual_shipping_cost" in orders.columns else 0.0
    order_costs["gateway_fee"] = orders["gateway_fee"].fillna(0.0) if "gateway_fee" in orders.columns else 0.0
    items = items.merge(order_costs, on="order_id", how="left")

    items["alloc_ratio"] = np.where(
        items["_order_net_total"] > 0,
        items["net_selling_price"] / items["_order_net_total"],
        1.0,
    )
    items["allocated_shipping"] = items["actual_shipping_cost"].fillna(0.0) * items["alloc_ratio"]
    items["allocated_gateway"] = items["gateway_fee"].fillna(0.0) * items["alloc_ratio"]

    # Calculate item-level contribution
    # Contribution = net_selling_price - cogs - refunds - restocking - return_shipping - allocated_shipping - allocated_gateway
    cogs_clean = items["cogs_total"].fillna(0.0)
    items["item_contribution"] = (
        items["net_selling_price"]
        - cogs_clean
        - items["refund_amount_calc"]
        - items["restocking_cost_calc"]
        - items["return_shipping_calc"]
        - items["allocated_shipping"]
        - items["allocated_gateway"]
    )

    # Aggregate to SKU level
    group_cols = ["product_id"]
    if "category" in items.columns:
        group_cols.append("category")

    sku_agg = items.groupby(group_cols).agg(
        units_sold=("quantity", "sum"),
        returned_units=("is_returned", "sum"),
        gross_revenue=("selling_price", "sum"),
        total_discounts=("discount_given", "sum"),
        net_revenue=("net_selling_price", "sum"),
        total_cogs=("cogs_total", lambda x: float(x.fillna(0.0).sum())),
        total_refunds=("refund_amount_calc", "sum"),
        total_restocking=("restocking_cost_calc", "sum"),
        total_return_shipping=("return_shipping_calc", "sum"),
        total_allocated_shipping=("allocated_shipping", "sum"),
        total_allocated_gateway=("allocated_gateway", "sum"),
        product_contribution=("item_contribution", "sum"),
    ).reset_index()

    sku_agg["return_rate_pct"] = np.where(
        sku_agg["units_sold"] > 0,
        (sku_agg["returned_units"] / sku_agg["units_sold"]) * 100.0,
        0.0,
    )
    sku_agg["contribution_margin_pct"] = np.where(
        sku_agg["net_revenue"] > 0,
        (sku_agg["product_contribution"] / sku_agg["net_revenue"]) * 100.0,
        0.0,
    )
    sku_agg["is_negative_contribution"] = sku_agg["product_contribution"] < 0.0

    return sku_agg


def aggregate_f10(sku_df: pd.DataFrame) -> dict:
    """Aggregates overall F10 Product Contribution metrics across all SKUs."""
    total_skus = len(sku_df)
    negative_skus = int(sku_df["is_negative_contribution"].sum()) if total_skus > 0 else 0
    total_net_rev = float(sku_df["net_revenue"].sum()) if total_skus > 0 else 0.0
    total_contribution = float(sku_df["product_contribution"].sum()) if total_skus > 0 else 0.0
    avg_margin_pct = (total_contribution / total_net_rev * 100.0) if total_net_rev > 0 else 0.0

    return {
        "skus_evaluated": total_skus,
        "negative_contribution_skus": negative_skus,
        "negative_sku_pct": (negative_skus / total_skus * 100.0) if total_skus > 0 else 0.0,
        "total_gross_revenue": float(sku_df["gross_revenue"].sum()) if total_skus > 0 else 0.0,
        "total_net_revenue": total_net_rev,
        "total_product_contribution": total_contribution,
        "overall_contribution_margin_pct": avg_margin_pct,
    }

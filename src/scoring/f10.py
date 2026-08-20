"""F10: Product Contribution Score."""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import DEFAULT_RESTOCKING_RATE, DEFAULT_RETURN_SHIPPING_FLAT


def compute_f10_normalized_score(net_product_profit: float, price_paid: float) -> float:
    """Computes F10 Product Contribution Normalized Score (0–100 scale).
    Formula: (Net Product Profit / Price Paid by Customer) * 100
    Negative scores are explicitly capped at 0.
    """
    if price_paid > 0:
        raw_score = (net_product_profit / price_paid) * 100.0
        return max(0.0, raw_score)
    return 0.0


def compute_f10(
    df_orders: pd.DataFrame, 
    df_line_items: pd.DataFrame,
    return_shipping_flat: float | None = None,
    default_restocking_rate: float | None = None,
) -> pd.DataFrame:
    """Computes SKU-level F10 Product Contribution and margin percentage."""
    ret_shipping_cost = return_shipping_flat if return_shipping_flat is not None else DEFAULT_RETURN_SHIPPING_FLAT
    restock_rate = default_restocking_rate if default_restocking_rate is not None else DEFAULT_RESTOCKING_RATE

    items = df_line_items.copy()
    
    if "is_cancelled" in df_orders.columns:
        valid_order_ids = set(df_orders[~df_orders["is_cancelled"]]["order_id"])
        items = items[items["order_id"].isin(valid_order_ids)].copy()
        orders = df_orders[df_orders["order_id"].isin(valid_order_ids)].copy()
    else:
        orders = df_orders.copy()

    if "quantity" in items.columns:
        items["quantity"] = items["quantity"].fillna(1)
    else:
        items["quantity"] = 1

    if "selling_price" in items.columns:
        items["gross_sales"] = items["selling_price"]
    else:
        items["gross_sales"] = items.get("net_selling_price", 0.0)

    if "discount_given" in items.columns:
        items["discount_amount"] = items["discount_given"].fillna(0.0)
    else:
        items["discount_amount"] = 0.0

    if "net_selling_price" in items.columns:
        items["net_sales"] = items["net_selling_price"]
    else:
        items["net_sales"] = items["gross_sales"] - items["discount_amount"]

    items["cogs_calc"] = items["cogs_total"].fillna(0.0) if "cogs_total" in items.columns else 0.0

    if "is_returned" in items.columns:
        items["is_returned"] = items["is_returned"].fillna(False)
        if "refund_amount" in items.columns:
            items["refund_calc"] = np.where(items["is_returned"], items["refund_amount"].fillna(items["net_sales"]), 0.0)
        else:
            items["refund_calc"] = np.where(items["is_returned"], items["net_sales"], 0.0)

        if "restocking_cost" in items.columns:
            items["restocking_calc"] = np.where(
                items["is_returned"],
                items["restocking_cost"].fillna(items["net_sales"] * restock_rate),
                0.0,
            )
        else:
            items["restocking_calc"] = np.where(items["is_returned"], items["net_sales"] * restock_rate, 0.0)

        items["return_shipping_calc"] = np.where(items["is_returned"], ret_shipping_cost * items["quantity"], 0.0)
    else:
        items["is_returned"] = False
        items["refund_calc"] = items["refund_amount"].fillna(0.0) if "refund_amount" in items.columns else 0.0
        items["restocking_calc"] = items["restocking_cost"].fillna(0.0) if "restocking_cost" in items.columns else 0.0
        items["return_shipping_calc"] = 0.0

    order_net_totals = items.groupby("order_id")["net_sales"].sum().rename("order_total_net_sales")
    items = items.merge(order_net_totals, on="order_id", how="left")
    
    order_costs = orders[["order_id", "actual_shipping_cost", "gateway_fee"]].copy() if all(c in orders.columns for c in ["actual_shipping_cost", "gateway_fee"]) else pd.DataFrame()
    
    if not order_costs.empty:
        items = items.merge(order_costs, on="order_id", how="left")
        items["actual_shipping_cost"] = items["actual_shipping_cost"].fillna(0.0)
        items["gateway_fee"] = items["gateway_fee"].fillna(0.0)
        
        ratio = np.where(
            items["order_total_net_sales"] > 0,
            items["net_sales"] / items["order_total_net_sales"],
            0.0,
        )
        items["allocated_shipping"] = items["actual_shipping_cost"] * ratio
        items["allocated_gateway"] = items["gateway_fee"] * ratio
    else:
        items["allocated_shipping"] = 0.0
        items["allocated_gateway"] = 0.0

    sku_group = items.groupby("product_id").agg(
        category=("category", "first") if "category" in items.columns else ("gross_sales", "count"),
        units_sold=("quantity", "sum"),
        units_returned=("is_returned", "sum"),
        gross_merchandise_revenue=("gross_sales", "sum"),
        discounts_given=("discount_amount", "sum"),
        net_merchandise_revenue=("net_sales", "sum"),
        cogs_total=("cogs_calc", "sum"),
        refund_loss=("refund_calc", "sum"),
        restocking_loss=("restocking_calc", "sum"),
        return_shipping_loss=("return_shipping_calc", "sum"),
        allocated_outbound_shipping=("allocated_shipping", "sum"),
        allocated_gateway_fees=("allocated_gateway", "sum"),
    ).reset_index()

    sku_group["total_reverse_logistics_loss"] = (
        sku_group["refund_loss"]
        + sku_group["restocking_loss"]
        + sku_group["return_shipping_loss"]
    )

    sku_group["product_contribution"] = (
        sku_group["net_merchandise_revenue"]
        - sku_group["cogs_total"]
        - sku_group["total_reverse_logistics_loss"]
        - sku_group["allocated_outbound_shipping"]
        - sku_group["allocated_gateway_fees"]
    )

    sku_group["contribution_margin_pct"] = np.where(
        sku_group["net_merchandise_revenue"] > 0,
        (sku_group["product_contribution"] / sku_group["net_merchandise_revenue"]) * 100.0,
        0.0,
    )

    sku_group["normalized_contribution_score"] = np.where(
        sku_group["net_merchandise_revenue"] > 0,
        np.maximum(0.0, (sku_group["product_contribution"] / sku_group["net_merchandise_revenue"]) * 100.0),
        0.0,
    )

    sku_group["is_negative_contribution"] = sku_group["product_contribution"] < 0.0
    sku_group["is_positive_contribution"] = sku_group["product_contribution"] > 0.0

    return sku_group


def aggregate_f10(sku_df: pd.DataFrame) -> dict:
    """Aggregates storewide F10 Product Contribution metrics across all SKUs."""
    total_skus = len(sku_df)
    negative_skus = int(sku_df["is_negative_contribution"].sum()) if total_skus > 0 else 0
    positive_skus = int(sku_df["is_positive_contribution"].sum()) if total_skus > 0 else 0

    total_net_rev = float(sku_df["net_merchandise_revenue"].sum()) if total_skus > 0 else 0.0
    total_contrib = float(sku_df["product_contribution"].sum()) if total_skus > 0 else 0.0
    overall_margin = (total_contrib / total_net_rev * 100.0) if total_net_rev > 0 else 0.0

    return {
        "total_skus_evaluated": total_skus,
        "positive_contribution_skus": positive_skus,
        "negative_contribution_skus": negative_skus,
        "negative_sku_pct": (negative_skus / total_skus * 100.0) if total_skus > 0 else 0.0,
        "total_net_revenue": total_net_rev,
        "total_product_contribution": total_contrib,
        "overall_contribution_margin_pct": overall_margin,
    }

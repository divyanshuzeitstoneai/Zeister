"""src/scoring/f11.py — F11: Product Net Profit Score.

Computes SKU-level and order-level bottom-line true profit by deducting all operational costs:
COGS, gateway fees, courier shipping costs, and statistical expected refund costs.

Formula:
    Net Profit = Net Sales - COGS - Actual Delivery Cost - Gateway Fees - Expected Refund Cost
    Expected Refund Cost = SKU Return Rate * Historical Avg Refund Cost
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def compute_f11(df_orders: pd.DataFrame, df_line_items: pd.DataFrame) -> pd.DataFrame:
    """Computes SKU-level F11 True Net Profit.

    Parameters:
        df_orders: Order-level DataFrame (shipping, gateway fees)
        df_line_items: Line-item level DataFrame (prices, COGS, returns)

    Returns:
        DataFrame aggregated per product_id with net profitability breakdown.
    """
    items = df_line_items.copy()
    
    # 1. Calculate SKU-level historical return rate & average refund cost
    sku_stats = items.groupby("product_id").agg(
        total_units=("quantity", "sum"),
        returned_units=("is_returned", "sum"),
        total_refunded=("refund_amount", "sum"),
        total_restocking=("restocking_cost", "sum"),
    ).reset_index()
    
    sku_stats["return_rate"] = sku_stats["returned_units"] / sku_stats["total_units"].replace(0, 1)
    sku_stats["expected_refund_per_unit"] = (
        (sku_stats["total_refunded"] + sku_stats["total_restocking"]) / sku_stats["total_units"].replace(0, 1)
    )
    
    # Merge order-level shipping & gateway cost allocations onto line items
    # Order-level shipping/gateway fee allocated proportionally to item net price
    order_totals = items.groupby("order_id")["net_selling_price"].sum().rename("order_net_total")
    items = items.merge(order_totals, on="order_id", how="left")
    items = items.merge(
        df_orders[["order_id", "actual_shipping_cost", "gateway_fee", "is_cancelled"]],
        on="order_id",
        how="left",
    )
    
    # Exclude cancelled orders
    items = items[~items["is_cancelled"]].copy()
    
    # Allocation fraction per line item
    items["alloc_ratio"] = np.where(
        items["order_net_total"] > 0,
        items["net_selling_price"] / items["order_net_total"],
        1.0,
    )
    
    items["allocated_shipping"] = items["actual_shipping_cost"].fillna(0.0) * items["alloc_ratio"]
    items["allocated_gateway"] = items["gateway_fee"].fillna(0.0) * items["alloc_ratio"]
    
    # Merge expected refund stats
    items = items.merge(sku_stats[["product_id", "expected_refund_per_unit", "return_rate"]], on="product_id", how="left")
    items["expected_refund_cost"] = items["expected_refund_per_unit"].fillna(0.0) * items["quantity"]
    
    # Calculate True Net Profit per item
    # Non-returned items contribute net selling price; returned items have revenue refunded
    items["revenue_collected"] = np.where(items["is_returned"], 0.0, items["net_selling_price"])
    
    items["true_net_profit"] = (
        items["revenue_collected"]
        - items["cogs_total"].fillna(0.0)
        - items["allocated_shipping"]
        - items["allocated_gateway"]
        - items["expected_refund_cost"]
    )
    
    # Aggregate to SKU level
    sku_summary = items.groupby(["product_id", "category"]).agg(
        total_units=("quantity", "sum"),
        gross_sales=("selling_price", "sum"),
        net_sales=("net_selling_price", "sum"),
        total_cogs=("cogs_total", "sum"),
        total_shipping_cost=("allocated_shipping", "sum"),
        total_gateway_fees=("allocated_gateway", "sum"),
        total_expected_returns=("expected_refund_cost", "sum"),
        total_net_profit=("true_net_profit", "sum"),
        avg_return_rate=("return_rate", "mean"),
    ).reset_index()
    
    sku_summary["net_margin_pct"] = np.where(
        sku_summary["net_sales"] > 0,
        (sku_summary["total_net_profit"] / sku_summary["net_sales"]) * 100.0,
        0.0,
    )
    
    sku_summary["is_unprofitable_sku"] = sku_summary["total_net_profit"] < 0
    return sku_summary

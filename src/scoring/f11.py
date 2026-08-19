"""F11: Order Profitability Score."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_f11(
    df_orders: pd.DataFrame, 
    df_line_items: pd.DataFrame | None = None,
    expected_refund_rate: float | None = None,
) -> pd.DataFrame:
    """Computes order-level net profitability after COGS, shipping, gateway, and refund costs."""
    orders = df_orders.copy()

    if "is_cancelled" in orders.columns:
        orders = orders[~orders["is_cancelled"]].copy()

    if df_line_items is not None:
        items = df_line_items.copy()
        if "is_cancelled" in items.columns:
            items = items[~items["is_cancelled"]].copy()
        
        if "net_selling_price" in items.columns:
            items["_calc_net_price"] = items["net_selling_price"]
        elif "selling_price" in items.columns:
            items["_calc_net_price"] = items["selling_price"]
        else:
            items["_calc_net_price"] = 0.0

        if "cogs_total" in items.columns:
            items["_calc_cogs"] = items["cogs_total"].fillna(0.0)
        else:
            items["_calc_cogs"] = 0.0
        
        if "expected_refund_cost" in items.columns:
            items["_calc_exp_refund"] = items["expected_refund_cost"].fillna(0.0)
        elif "is_returned" in items.columns and "refund_amount" in items.columns:
            ref_amt = items["refund_amount"].fillna(items["_calc_net_price"])
            restock_amt = items["restocking_cost"].fillna(0.0) if "restocking_cost" in items.columns else 0.0
            items["_calc_exp_refund"] = np.where(items["is_returned"], ref_amt + restock_amt, 0.0)
        elif expected_refund_rate is not None and expected_refund_rate > 0:
            items["_calc_exp_refund"] = items["_calc_net_price"] * expected_refund_rate
        else:
            items["_calc_exp_refund"] = 0.0

        order_line_agg = items.groupby("order_id").agg(
            order_net_merchandise_sales=("_calc_net_price", "sum"),
            order_cogs=("_calc_cogs", "sum"),
            order_expected_refund_cost=("_calc_exp_refund", "sum"),
        ).reset_index()

        orders = orders.merge(order_line_agg, on="order_id", how="left")
        orders["order_net_merchandise_sales"] = orders["order_net_merchandise_sales"].fillna(0.0)
        orders["order_cogs"] = orders["order_cogs"].fillna(0.0)
        orders["order_expected_refund_cost"] = orders["order_expected_refund_cost"].fillna(0.0)
    else:
        if "order_net_merchandise_sales" not in orders.columns:
            if "net_sales" in orders.columns:
                orders["order_net_merchandise_sales"] = orders["net_sales"]
            elif "net_selling_price" in orders.columns:
                orders["order_net_merchandise_sales"] = orders["net_selling_price"]
            elif "gross_sales" in orders.columns:
                orders["order_net_merchandise_sales"] = orders["gross_sales"]
            else:
                orders["order_net_merchandise_sales"] = 0.0
        
        if "order_cogs" not in orders.columns:
            orders["order_cogs"] = orders["cogs_total"].fillna(0.0) if "cogs_total" in orders.columns else 0.0
        
        if "order_expected_refund_cost" not in orders.columns:
            if "expected_refund_cost" in orders.columns:
                orders["order_expected_refund_cost"] = orders["expected_refund_cost"].fillna(0.0)
            elif expected_refund_rate is not None and expected_refund_rate > 0:
                orders["order_expected_refund_cost"] = orders["order_net_merchandise_sales"] * expected_refund_rate
            else:
                orders["order_expected_refund_cost"] = 0.0

    if "shipping_charged_to_customer" in orders.columns:
        orders["shipping_charged_to_customer"] = orders["shipping_charged_to_customer"].fillna(0.0)
    else:
        orders["shipping_charged_to_customer"] = 0.0
    orders["total_money_collected"] = orders["order_net_merchandise_sales"] + orders["shipping_charged_to_customer"]

    if "actual_shipping_cost" in orders.columns:
        orders["actual_shipping_cost"] = orders["actual_shipping_cost"].fillna(0.0)
    else:
        orders["actual_shipping_cost"] = 0.0

    if "gateway_fee" in orders.columns:
        orders["gateway_fee"] = orders["gateway_fee"].fillna(0.0)
    else:
        orders["gateway_fee"] = 0.0

    if "expected_refund_cost" in orders.columns and "order_expected_refund_cost" in orders.columns:
        orders["order_expected_refund_cost"] = np.where(
            orders["expected_refund_cost"].notna(),
            orders["expected_refund_cost"],
            orders["order_expected_refund_cost"],
        )

    orders["order_net_profit"] = (
        orders["total_money_collected"]
        - orders["order_cogs"]
        - orders["actual_shipping_cost"]
        - orders["gateway_fee"]
        - orders["order_expected_refund_cost"]
    )

    orders["is_profitable_order"] = orders["order_net_profit"] > 0.0
    orders["is_unprofitable_order"] = orders["order_net_profit"] < 0.0
    orders["is_breakeven_order"] = orders["order_net_profit"] == 0.0

    orders["order_net_margin_pct"] = np.where(
        orders["total_money_collected"] > 0,
        (orders["order_net_profit"] / orders["total_money_collected"]) * 100.0,
        0.0,
    )

    return orders


def aggregate_f11(orders_df: pd.DataFrame) -> dict:
    """Aggregates overall F11 Order Profitability metrics across the store."""
    deduped = orders_df.drop_duplicates(subset="order_id") if "order_id" in orders_df.columns else orders_df
    total_orders = len(deduped)
    profitable_count = int(deduped["is_profitable_order"].sum()) if total_orders > 0 else 0
    unprofitable_count = int(deduped["is_unprofitable_order"].sum()) if total_orders > 0 else 0
    breakeven_count = int(deduped["is_breakeven_order"].sum()) if total_orders > 0 else 0

    total_collected = float(deduped["total_money_collected"].sum()) if total_orders > 0 else 0.0
    total_net_profit = float(deduped["order_net_profit"].sum()) if total_orders > 0 else 0.0
    avg_order_profit = (total_net_profit / total_orders) if total_orders > 0 else 0.0
    overall_net_margin_pct = (total_net_profit / total_collected * 100.0) if total_collected > 0 else 0.0

    return {
        "orders_evaluated": total_orders,
        "profitable_orders": profitable_count,
        "unprofitable_orders": unprofitable_count,
        "breakeven_orders": breakeven_count,
        "unprofitable_order_pct": (unprofitable_count / total_orders * 100.0) if total_orders > 0 else 0.0,
        "total_revenue_collected": total_collected,
        "total_order_net_profit": total_net_profit,
        "avg_order_net_profit": avg_order_profit,
        "overall_net_margin_pct": overall_net_margin_pct,
    }

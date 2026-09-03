"""src/scoring/inventory_risk.py — Inventory & Capital Risk Scoring (I03, I04, I05, I08).

Category: Inventory & Capital Risk
Implements the 4 core formulas:
  1. I03: Capital-at-Risk Score
     Capital at Risk = Σ (Unsold Units × Unit Wholesale Cost) for SKUs where Days on Hand > threshold (default 180)
     Fallback: Days on hand missing -> Unresolved (NEVER 0 or 999).
  
  2. I04: Stockout Risk Score
     Days of Supply = Current Inventory ÷ Daily Sales Velocity
     Blackout Window = max(0, Supplier Lead Time − Days of Supply)
     Missed Revenue = Daily Sales Velocity × Blackout Window × Avg Unit Price
     Fallback: Supplier lead time missing -> Unresolved (no arbitrary default).
  
  3. I05: Oversell Risk Score
     Total Oversell Loss = Σ (Canceled Order Value + Gateway Fee + Support Cost) for orders accepted post-stockout
     Fallback: Only cancel_reason == 'INVENTORY' counted. Support cost falls back to default ($15.00) with flag.
  
  4. I08: Return-to-Inventory Risk Score
     Trapped Capital = Σ Retail Value of Refunded Items where delay > 48hrs OR restock is null
     Fallback: No restock event within window -> Trapped (ongoing risk), NOT Unresolved.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from src.config import (
    I03_DEFAULT_AGING_THRESHOLD_DAYS,
    I04_DEFAULT_VELOCITY_WINDOW_DAYS,
    I05_DEFAULT_SUPPORT_COST,
    I08_RESTOCK_DELAY_THRESHOLD_HOURS,
    I08_MAX_RESTOCK_WINDOW_DAYS,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# I03: CAPITAL-AT-RISK SCORE
# ═══════════════════════════════════════════════════════════════════════

def compute_i03(
    df_inventory: pd.DataFrame,
    aging_threshold_days: int | None = None,
) -> pd.DataFrame:
    """Computes I03 Capital-at-Risk Score per SKU.

    Formula:
      Capital at Risk = Unsold Units × Unit Wholesale Cost (for SKUs where days_on_hand > threshold)

    Required/Expected Columns:
      - sku or product_id
      - current_inventory_qty (or unsold_units / quantity)
      - unit_wholesale_cost (or unit_cost / cogs)
      - days_on_hand (days since batch received; null if unknown)
      - [optional] aging_threshold_days

    Fallback:
      - If days_on_hand is null/missing -> status = "Unresolved" (NEVER default to 0 or 999).
      - If aging_threshold_days is null -> use I03_DEFAULT_AGING_THRESHOLD_DAYS (180), flag estimated.
    """
    df = df_inventory.copy()

    # Resolve unit cost column
    cost_col = None
    for c in ["unit_wholesale_cost", "unit_cost", "actual_cogs", "cogs"]:
        if c in df.columns:
            cost_col = c
            break

    # Resolve quantity column
    qty_col = None
    for c in ["current_inventory_qty", "unsold_units", "quantity", "inventory_quantity"]:
        if c in df.columns:
            qty_col = c
            break

    if cost_col is None or qty_col is None:
        raise ValueError(f"Missing required inventory cost/quantity columns in DataFrame: {df.columns.tolist()}")

    qty = df[qty_col].fillna(0).astype(float)
    cost = df[cost_col].fillna(0).astype(float)
    df["total_inventory_value"] = qty * cost

    # Aging threshold resolution
    thresholds = []
    is_thresh_est = []
    for idx in df.index:
        if aging_threshold_days is not None:
            thresholds.append(int(aging_threshold_days))
            is_thresh_est.append(False)
        elif "aging_threshold_days" in df.columns and pd.notna(df.at[idx, "aging_threshold_days"]):
            thresholds.append(int(df.at[idx, "aging_threshold_days"]))
            is_thresh_est.append(False)
        else:
            thresholds.append(I03_DEFAULT_AGING_THRESHOLD_DAYS)
            is_thresh_est.append(True)

    df["aging_threshold_days"] = thresholds
    df["is_aging_threshold_estimated"] = is_thresh_est

    # Days on hand check
    if "days_on_hand" not in df.columns:
        df["days_on_hand"] = np.nan

    doh = df["days_on_hand"]
    is_unresolved = doh.isna()

    # Rule: Days on hand > threshold (strict or >= depending on spec: spec says > 180)
    is_at_risk = (doh > df["aging_threshold_days"]) & (~is_unresolved)

    df["capital_at_risk"] = np.where(
        is_unresolved,
        np.nan,
        np.where(is_at_risk, df["total_inventory_value"], 0.0),
    )

    df["i03_status"] = np.where(
        is_unresolved,
        "Unresolved",
        np.where(is_at_risk, "AtRisk", "Normal"),
    )

    return df


def aggregate_i03(df: pd.DataFrame) -> dict:
    """Aggregates I03 Capital-at-Risk across all inventory SKUs."""
    total_skus = len(df)
    unresolved_mask = df["i03_status"] == "Unresolved"
    at_risk_mask = df["i03_status"] == "AtRisk"
    normal_mask = df["i03_status"] == "Normal"

    evaluated_skus = total_skus - int(unresolved_mask.sum())
    capital_at_risk = float(df.loc[at_risk_mask, "capital_at_risk"].sum()) if at_risk_mask.any() else 0.0
    total_inventory_value = float(df["total_inventory_value"].sum()) if "total_inventory_value" in df.columns else 0.0

    risk_pct = (capital_at_risk / total_inventory_value * 100.0) if total_inventory_value > 0 else 0.0

    return {
        "skus_evaluated": evaluated_skus,
        "skus_unresolved": int(unresolved_mask.sum()),
        "skus_at_risk": int(at_risk_mask.sum()),
        "skus_normal": int(normal_mask.sum()),
        "total_capital_at_risk": round(capital_at_risk, 2),
        "total_inventory_value": round(total_inventory_value, 2),
        "capital_at_risk_pct": round(risk_pct, 2),
    }


# ═══════════════════════════════════════════════════════════════════════
# I04: STOCKOUT RISK SCORE
# ═══════════════════════════════════════════════════════════════════════

def compute_i04(
    df_inventory: pd.DataFrame,
    df_sales: pd.DataFrame | None = None,
    velocity_window_days: int = I04_DEFAULT_VELOCITY_WINDOW_DAYS,
) -> pd.DataFrame:
    """Computes I04 Stockout Risk Score per SKU.

    Formulas:
      Days of Supply = Current Inventory ÷ Daily Sales Velocity
      Blackout Window = max(0, Supplier Lead Time − Days of Supply)
      Missed Revenue = Daily Sales Velocity × Blackout Window × Avg Unit Price

    Required/Expected Columns:
      - sku or product_id
      - current_inventory_qty
      - supplier_lead_time_days (if missing -> Unresolved)
      - avg_unit_price (or price / discounted_unit_price)
      - daily_sales_velocity (or computed from df_sales)

    Fallback:
      - If supplier_lead_time_days is null -> Unresolved, DO NOT assume default lead time.
      - If daily_sales_velocity <= 0 -> Days of Supply is infinite, Blackout Window is 0, Missed Revenue is 0.
    """
    df = df_inventory.copy()

    # Determine inventory quantity
    qty_col = None
    for c in ["current_inventory_qty", "inventory_quantity", "quantity"]:
        if c in df.columns:
            qty_col = c
            break
    if qty_col is None:
        raise ValueError(f"Missing inventory quantity column in: {df.columns.tolist()}")

    qty = df[qty_col].fillna(0).astype(float)

    # Determine unit price
    price_col = None
    for c in ["avg_unit_price", "discounted_unit_price", "price", "unit_price", "net_price"]:
        if c in df.columns:
            price_col = c
            break
    if price_col is None:
        raise ValueError(f"Missing price column in: {df.columns.tolist()}")
    price = df[price_col].fillna(0).astype(float)

    # Calculate or retrieve daily sales velocity
    if "daily_sales_velocity" not in df.columns:
        if df_sales is not None and not df_sales.empty and "sku" in df_sales.columns and "quantity" in df_sales.columns:
            # Trailing N-day sales velocity
            vel = df_sales.groupby("sku")["quantity"].sum() / float(velocity_window_days)
            df = df.merge(vel.rename("daily_sales_velocity"), on="sku", how="left")
            df["daily_sales_velocity"] = df["daily_sales_velocity"].fillna(0.0)
        else:
            df["daily_sales_velocity"] = 0.0

    velocity = df["daily_sales_velocity"].fillna(0.0).astype(float)

    # Days of Supply calculation
    # If velocity > 0 -> qty / velocity
    # If velocity == 0 and qty > 0 -> inf (safe, no stockout)
    # If velocity == 0 and qty == 0 -> 0 (no inventory, but 0 velocity -> 0 demand)
    days_of_supply = np.where(
        velocity > 0,
        qty / velocity,
        np.where(qty > 0, np.inf, 0.0),
    )
    df["days_of_supply"] = days_of_supply

    # Check lead time presence
    if "supplier_lead_time_days" not in df.columns:
        df["supplier_lead_time_days"] = np.nan

    lead_time = df["supplier_lead_time_days"].astype(float)
    is_unresolved = lead_time.isna()

    # Blackout window = max(0, lead_time - days_of_supply)
    blackout_window = np.where(
        is_unresolved,
        np.nan,
        np.maximum(0.0, lead_time - days_of_supply),
    )
    df["blackout_window_days"] = blackout_window

    # Missed revenue = Daily Sales Velocity × Blackout Window × Avg Unit Price
    missed_rev = np.where(
        is_unresolved,
        np.nan,
        velocity * blackout_window * price,
    )
    df["missed_revenue"] = missed_rev

    df["i04_status"] = np.where(
        is_unresolved,
        "Unresolved",
        np.where(df["blackout_window_days"] > 0, "AtRisk", "Safe"),
    )

    return df


def aggregate_i04(df: pd.DataFrame) -> dict:
    """Aggregates I04 Stockout Risk across inventory SKUs."""
    total_skus = len(df)
    unresolved_mask = df["i04_status"] == "Unresolved"
    at_risk_mask = df["i04_status"] == "AtRisk"
    safe_mask = df["i04_status"] == "Safe"

    evaluated = total_skus - int(unresolved_mask.sum())
    total_missed_revenue = float(df.loc[at_risk_mask, "missed_revenue"].sum()) if at_risk_mask.any() else 0.0
    avg_blackout = float(df.loc[at_risk_mask, "blackout_window_days"].mean()) if at_risk_mask.any() else 0.0

    return {
        "skus_evaluated": evaluated,
        "skus_unresolved": int(unresolved_mask.sum()),
        "skus_at_risk": int(at_risk_mask.sum()),
        "skus_safe": int(safe_mask.sum()),
        "total_missed_revenue": round(total_missed_revenue, 2),
        "avg_blackout_window_days": round(avg_blackout, 1),
    }


# ═══════════════════════════════════════════════════════════════════════
# I05: OVERSELL RISK SCORE
# ═══════════════════════════════════════════════════════════════════════

def compute_i05(
    df_orders: pd.DataFrame,
    support_cost_per_ticket: float | None = None,
) -> pd.DataFrame:
    """Computes I05 Oversell Risk Score per Order.

    Formula:
      Total Oversell Loss = Canceled Order Value + Gateway Fee + Support Cost
      (Evaluated for orders accepted post-stockout)

    Required/Expected Columns:
      - order_id
      - cancel_reason (Shopify enum 'INVENTORY') or is_oversold flag
      - canceled_order_value (or total_price, net_sales, gross_sales)
      - gateway_fee (processor fee retained despite cancellation; nullable)
      - [optional] support_cost (from ticket table or metafield)

    Fallback:
      - Only count orders where cancel_reason == 'INVENTORY' explicitly (or is_oversold == True).
      - If support_cost_per_ticket is unset -> default to $15.00 flat default, flag estimated.
      - If gateway_fee is null -> fill with 0.0, flag estimated.
    """
    df = df_orders.copy()

    # Determine canceled order value
    val_col = None
    for c in ["canceled_order_value", "total_price", "net_sales", "gross_sales", "net_paid_amount"]:
        if c in df.columns:
            val_col = c
            break
    if val_col is None:
        raise ValueError(f"Missing order value column in: {df.columns.tolist()}")

    order_val = df[val_col].fillna(0.0).astype(float)

    # Determine gateway fee
    gw_col = "gateway_fee" if "gateway_fee" in df.columns else None
    if gw_col:
        is_gw_null = df[gw_col].isna()
        gw_fee = df[gw_col].fillna(0.0).astype(float)
    else:
        is_gw_null = pd.Series(True, index=df.index)
        gw_fee = pd.Series(0.0, index=df.index)

    df["gateway_fee_filled"] = gw_fee
    df["is_gateway_fee_estimated"] = is_gw_null

    # Determine support cost per ticket
    costs = []
    is_supp_est = []
    for idx in df.index:
        if support_cost_per_ticket is not None:
            costs.append(float(support_cost_per_ticket))
            is_supp_est.append(False)
        elif "support_cost" in df.columns and pd.notna(df.at[idx, "support_cost"]):
            costs.append(float(df.at[idx, "support_cost"]))
            is_supp_est.append(False)
        elif "support_cost_per_ticket" in df.columns and pd.notna(df.at[idx, "support_cost_per_ticket"]):
            costs.append(float(df.at[idx, "support_cost_per_ticket"]))
            is_supp_est.append(False)
        else:
            costs.append(I05_DEFAULT_SUPPORT_COST)
            is_supp_est.append(True)

    df["support_cost_allocated"] = costs
    df["is_support_cost_estimated"] = is_supp_est

    # Identify oversold orders (confirmed signal: cancel_reason == 'INVENTORY' or is_oversold is True)
    if "is_oversold" in df.columns:
        is_oversold = df["is_oversold"].fillna(False).astype(bool)
    elif "cancel_reason" in df.columns:
        is_oversold = df["cancel_reason"].astype(str).str.upper() == "INVENTORY"
    else:
        is_oversold = pd.Series(False, index=df.index)

    df["is_oversold_order"] = is_oversold

    # Total Oversell Loss = Canceled Order Value + Gateway Fee + Support Cost
    df["oversell_loss"] = np.where(
        is_oversold,
        order_val + df["gateway_fee_filled"] + df["support_cost_allocated"],
        0.0,
    )

    df["i05_status"] = np.where(is_oversold, "OversoldLoss", "Normal")

    return df


def aggregate_i05(df: pd.DataFrame) -> dict:
    """Aggregates I05 Oversell Loss across all orders."""
    total_orders = len(df)
    oversold_mask = df["is_oversold_order"] == True

    oversold_orders = int(oversold_mask.sum())
    total_loss = float(df.loc[oversold_mask, "oversell_loss"].sum()) if oversold_orders > 0 else 0.0

    val_col = None
    for c in ["canceled_order_value", "total_price", "net_sales", "gross_sales", "net_paid_amount"]:
        if c in df.columns:
            val_col = c
            break

    canceled_val_sum = float(df.loc[oversold_mask, val_col].sum()) if oversold_orders > 0 and val_col else 0.0
    gateway_fee_sum = float(df.loc[oversold_mask, "gateway_fee_filled"].sum()) if oversold_orders > 0 else 0.0
    support_cost_sum = float(df.loc[oversold_mask, "support_cost_allocated"].sum()) if oversold_orders > 0 else 0.0

    return {
        "orders_evaluated": total_orders,
        "oversold_orders": oversold_orders,
        "oversell_rate_pct": round(oversold_orders / total_orders * 100.0, 2) if total_orders > 0 else 0.0,
        "total_oversell_loss": round(total_loss, 2),
        "loss_breakdown": {
            "canceled_order_value": round(canceled_val_sum, 2),
            "gateway_fees": round(gateway_fee_sum, 2),
            "support_costs": round(support_cost_sum, 2),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# I08: RETURN-TO-INVENTORY RISK SCORE
# ═══════════════════════════════════════════════════════════════════════

def compute_i08(
    df_returns: pd.DataFrame,
    restock_delay_threshold_hours: float = I08_RESTOCK_DELAY_THRESHOLD_HOURS,
    max_restock_window_days: int = I08_MAX_RESTOCK_WINDOW_DAYS,
) -> pd.DataFrame:
    """Computes I08 Return-to-Inventory Trapped Capital per returned item.

    Formula:
      Trapped Capital = Retail Value of Refunded Items
                        where (restock_event_at − refund_processed_at) > 48hrs
                        OR restock_event_at is null

    Required/Expected Columns:
      - refund_id or line_item_id
      - refund_processed_at (timestamp)
      - retail_value (or gross_price, selling_price, refund_amount)
      - restock_event_at (timestamp of restock, or null)

    Fallback:
      - If restock_event_at is null or not found within window -> Trapped (ongoing risk), NOT Unresolved.
    """
    df = df_returns.copy()

    # Determine retail value
    val_col = None
    for c in ["retail_value", "gross_price", "selling_price", "refund_amount"]:
        if c in df.columns:
            val_col = c
            break
    if val_col is None:
        raise ValueError(f"Missing retail value column in: {df.columns.tolist()}")

    retail_val = df[val_col].fillna(0.0).astype(float)
    df["item_retail_value"] = retail_val

    # Ensure datetime format for timestamps
    refund_dt = pd.to_datetime(df["refund_processed_at"])
    restock_dt = pd.to_datetime(df["restock_event_at"]) if "restock_event_at" in df.columns else pd.Series(pd.NaT, index=df.index)

    # Delay in hours
    delay_hours = (restock_dt - refund_dt).dt.total_seconds() / 3600.0
    df["restock_delay_hours"] = delay_hours

    # Condition: delay > 48h OR never restocked (NaT) OR delayed beyond max window
    is_never_restocked = restock_dt.isna()
    is_delayed = (delay_hours > restock_delay_threshold_hours) | is_never_restocked

    df["is_trapped_capital"] = is_delayed
    df["trapped_capital"] = np.where(is_delayed, retail_val, 0.0)

    # Status breakdown: Delayed, NeverRestocked, OnTime
    status = []
    for idx in df.index:
        if is_never_restocked.iloc[df.index.get_loc(idx)]:
            status.append("NeverRestocked")
        elif delay_hours.iloc[df.index.get_loc(idx)] > restock_delay_threshold_hours:
            status.append("DelayedRestock")
        else:
            status.append("OnTimeRestock")

    df["i08_status"] = status

    return df


def aggregate_i08(df: pd.DataFrame) -> dict:
    """Aggregates I08 Return-to-Inventory Trapped Capital."""
    total_returns = len(df)
    trapped_mask = df["is_trapped_capital"] == True
    never_restocked_mask = df["i08_status"] == "NeverRestocked"
    delayed_mask = df["i08_status"] == "DelayedRestock"
    ontime_mask = df["i08_status"] == "OnTimeRestock"

    total_trapped = float(df.loc[trapped_mask, "trapped_capital"].sum()) if trapped_mask.any() else 0.0
    total_returned_value = float(df["item_retail_value"].sum()) if "item_retail_value" in df.columns else 0.0

    valid_delays = df.loc[~df["restock_delay_hours"].isna(), "restock_delay_hours"]
    avg_delay = float(valid_delays.mean()) if len(valid_delays) > 0 else 0.0

    return {
        "refunds_evaluated": total_returns,
        "items_on_time": int(ontime_mask.sum()),
        "items_delayed": int(delayed_mask.sum()),
        "items_never_restocked": int(never_restocked_mask.sum()),
        "total_trapped_capital": round(total_trapped, 2),
        "total_refunded_retail_value": round(total_returned_value, 2),
        "trapped_capital_pct": round(total_trapped / total_returned_value * 100.0, 2) if total_returned_value > 0 else 0.0,
        "avg_restock_delay_hours": round(avg_delay, 1),
    }

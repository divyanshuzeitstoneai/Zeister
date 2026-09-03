"""src/scoring/logistics_risk.py — Logistics & Fulfillment Scoring (L01, L07, L12).

Category: Logistics & Fulfillment
Implements the 3 core formulas:
  1. L01: Shipping Cost Recovery Score
     Under-Recovery Loss = Total Outbound Shipping Expenses Paid − Total Shipping Revenue Collected
     Recovery % (Normalized) = (Shipping Revenue Collected ÷ Actual Shipping Cost) × 100
     Fallback: Missing per-order cost -> Period-average cost with flag (NEVER silently $0).

  2. L07: Zone Profitability Score
     Zone Loss = Σ (Regional Carrier Surcharge Paid − Location Surcharge Collected from Buyer)
     Fallback: Unmapped postal code -> zone = "Unclassified", excluded from zone-level rollup.

  3. L12: Fulfillment SLA Risk Score
     Breach = (Fulfillment Created At − Order Created At) > SLA Threshold (default 48h)
     Loss per Delayed Order = (WISMO Ticket Cost × Ticket Volume) + Wasted Fulfillment Labor
     Fallback: Ticket data unlinked -> SLA-only score, support_cost_unavailable = True (never 0 tickets).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from src.config import (
    L01_DEFAULT_PERIOD_AVG_SHIPPING_COST,
    L07_DEFAULT_ZONE_SURCHARGE_COLLECTED,
    L12_DEFAULT_DISPATCH_SLA_HOURS,
    L12_DEFAULT_WISMO_TICKET_COST,
    L12_DEFAULT_WASTED_LABOR_COST,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# L01: SHIPPING COST RECOVERY SCORE
# ═══════════════════════════════════════════════════════════════════════

def compute_l01(
    df_orders: pd.DataFrame,
    period_avg_shipping_cost: float | None = None,
) -> pd.DataFrame:
    """Computes L01 Shipping Cost Recovery per order.

    Formulas:
      Under-Recovery Loss = Actual Shipping Cost − Shipping Charged
      Recovery % = (Shipping Charged ÷ Actual Shipping Cost) × 100

    Required/Expected Columns:
      - order_id
      - shipping_charged (or shipping_charged_to_customer)
      - actual_shipping_cost (from 3PL / carrier invoice; nullable)

    Fallback:
      - If actual_shipping_cost is null -> use period_avg_shipping_cost (default $6.50),
        flag is_shipping_cost_averaged = True. NEVER silently default to $0.00.
    """
    df = df_orders.copy()

    # Resolve shipping charged
    charged_col = None
    for c in ["shipping_charged", "shipping_charged_to_customer", "shipping_fee_collected"]:
        if c in df.columns:
            charged_col = c
            break
    if charged_col is None:
        raise ValueError(f"Missing shipping charged column in: {df.columns.tolist()}")

    charged = df[charged_col].fillna(0.0).astype(float)
    df["shipping_revenue_collected"] = charged

    # Resolve actual shipping cost
    cost_col = None
    for c in ["actual_shipping_cost", "carrier_shipping_cost", "outbound_shipping_expense"]:
        if c in df.columns:
            cost_col = c
            break

    default_avg = period_avg_shipping_cost or L01_DEFAULT_PERIOD_AVG_SHIPPING_COST

    if cost_col is None or df[cost_col].isna().all():
        # Entire column missing or all null
        is_averaged = pd.Series(True, index=df.index)
        actual_cost = pd.Series(default_avg, index=df.index)
    else:
        is_averaged = df[cost_col].isna()
        actual_cost = df[cost_col].fillna(default_avg).astype(float)

    df["actual_shipping_expense"] = actual_cost
    df["is_shipping_cost_averaged"] = is_averaged

    # Under-Recovery Loss: Actual Cost − Charged (positive = loss/leakage, negative = surplus)
    # Note: Spec defines: Under-Recovery Loss = Expenses Paid − Revenue Collected
    df["under_recovery_loss"] = actual_cost - charged

    # Recovery % Normalized = (Revenue Collected ÷ Actual Cost) × 100
    # Guard against 0 actual cost
    recovery_pct = np.where(
        actual_cost > 0,
        (charged / actual_cost) * 100.0,
        np.where(charged == 0, 100.0, 100.0),
    )
    df["shipping_recovery_pct"] = recovery_pct

    # Status classification
    df["l01_status"] = np.where(
        df["under_recovery_loss"] > 0.001,
        "UnderRecovered",
        np.where(df["under_recovery_loss"] < -0.001, "Surplus", "FullRecovery"),
    )

    return df


def aggregate_l01(df: pd.DataFrame) -> dict:
    """Aggregates L01 Shipping Cost Recovery across the store."""
    total_orders = len(df)
    under_mask = df["l01_status"] == "UnderRecovered"
    surplus_mask = df["l01_status"] == "Surplus"
    full_mask = df["l01_status"] == "FullRecovery"

    total_expenses = float(df["actual_shipping_expense"].sum()) if total_orders > 0 else 0.0
    total_revenue = float(df["shipping_revenue_collected"].sum()) if total_orders > 0 else 0.0
    net_loss = total_expenses - total_revenue

    overall_recovery_pct = (total_revenue / total_expenses * 100.0) if total_expenses > 0 else 100.0
    averaged_orders = int(df["is_shipping_cost_averaged"].sum())

    return {
        "orders_evaluated": total_orders,
        "orders_under_recovered": int(under_mask.sum()),
        "orders_full_recovery": int(full_mask.sum()),
        "orders_surplus": int(surplus_mask.sum()),
        "orders_with_averaged_cost": averaged_orders,
        "total_shipping_expenses": round(total_expenses, 2),
        "total_shipping_revenue": round(total_revenue, 2),
        "net_under_recovery_loss": round(net_loss, 2),
        "overall_recovery_pct": round(overall_recovery_pct, 2),
    }


# ═══════════════════════════════════════════════════════════════════════
# L07: ZONE PROFITABILITY SCORE
# ═══════════════════════════════════════════════════════════════════════

def compute_l07(
    df_orders: pd.DataFrame,
    zone_mapping: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Computes L07 Zone Profitability Score per order.

    Formula:
      Zone Loss = Regional Carrier Surcharge Paid − Location Surcharge Collected from Buyer

    Required/Expected Columns:
      - order_id
      - customer_postal_code (or zip / shipping_zip)
      - carrier_surcharge_amount (itemized surcharge from carrier invoice)
      - [optional] location_surcharge_collected (what buyer paid specifically for location/extended area)
      - [optional] zone_classification (if already enriched)

    Fallback:
      - If postal code is not in zone_mapping -> tag zone = "Unclassified",
        flag is_zone_unclassified = True, exclude from zone-level rollup.
    """
    df = df_orders.copy()

    # Resolve postal code
    zip_col = None
    for c in ["customer_postal_code", "postal_code", "shipping_zip", "zip"]:
        if c in df.columns:
            zip_col = c
            break

    # Carrier surcharge paid
    surch_paid_col = None
    for c in ["carrier_surcharge_amount", "regional_surcharge_paid", "extended_area_surcharge"]:
        if c in df.columns:
            surch_paid_col = c
            break
    surch_paid = df[surch_paid_col].fillna(0.0).astype(float) if surch_paid_col else pd.Series(0.0, index=df.index)
    df["carrier_surcharge_paid"] = surch_paid

    # Surcharge collected from buyer
    surch_coll_col = None
    for c in ["location_surcharge_collected", "surcharge_collected", "shipping_surcharge"]:
        if c in df.columns:
            surch_coll_col = c
            break
    surch_collected = df[surch_coll_col].fillna(L07_DEFAULT_ZONE_SURCHARGE_COLLECTED).astype(float) if surch_coll_col else pd.Series(L07_DEFAULT_ZONE_SURCHARGE_COLLECTED, index=df.index)
    df["location_surcharge_collected"] = surch_collected

    # Zone classification lookup
    zones = []
    is_unclassified = []
    for idx in df.index:
        # Check if already present
        if "zone_classification" in df.columns and pd.notna(df.at[idx, "zone_classification"]) and df.at[idx, "zone_classification"] != "Unclassified":
            zones.append(str(df.at[idx, "zone_classification"]))
            is_unclassified.append(False)
            continue

        raw_zip = str(df.at[idx, zip_col]).strip().upper() if zip_col and pd.notna(df.at[idx, zip_col]) else None
        if raw_zip and zone_mapping and raw_zip in zone_mapping:
            zones.append(zone_mapping[raw_zip])
            is_unclassified.append(False)
        elif raw_zip and zone_mapping and raw_zip[:3] in zone_mapping:  # 3-digit prefix matching
            zones.append(zone_mapping[raw_zip[:3]])
            is_unclassified.append(False)
        else:
            zones.append("Unclassified")
            is_unclassified.append(True)

    df["zone_classification"] = zones
    df["is_zone_unclassified"] = is_unclassified

    # Zone Loss = Regional Carrier Surcharge Paid − Location Surcharge Collected
    # (Only non-negative counts as loss, or signed variance)
    df["zone_loss"] = surch_paid - surch_collected
    df["zone_leakage"] = np.maximum(0.0, df["zone_loss"])

    df["l07_status"] = np.where(
        df["is_zone_unclassified"],
        "UnclassifiedReview",
        np.where(df["zone_loss"] > 0, "ZoneLoss", "ZoneProfitable"),
    )

    return df


def aggregate_l07(df: pd.DataFrame) -> dict:
    """Aggregates L07 Zone Profitability by zone tier."""
    classified = df[~df["is_zone_unclassified"]].copy()
    unclassified = df[df["is_zone_unclassified"]].copy()

    total_classified_loss = float(classified["zone_leakage"].sum()) if len(classified) > 0 else 0.0
    total_unclassified_loss = float(unclassified["zone_leakage"].sum()) if len(unclassified) > 0 else 0.0

    zone_breakdown = {}
    if len(classified) > 0:
        for zone, group in classified.groupby("zone_classification"):
            zone_breakdown[zone] = {
                "orders": len(group),
                "total_surcharge_paid": round(float(group["carrier_surcharge_paid"].sum()), 2),
                "total_surcharge_collected": round(float(group["location_surcharge_collected"].sum()), 2),
                "zone_loss": round(float(group["zone_leakage"].sum()), 2),
                "orders_with_loss": int((group["zone_loss"] > 0).sum()),
            }

    return {
        "orders_evaluated": len(df),
        "orders_classified": len(classified),
        "orders_unclassified": len(unclassified),
        "total_zone_loss": round(total_classified_loss, 2),
        "unclassified_zone_loss": round(total_unclassified_loss, 2),
        "zone_breakdown": zone_breakdown,
    }


# ═══════════════════════════════════════════════════════════════════════
# L12: FULFILLMENT SLA RISK SCORE
# ═══════════════════════════════════════════════════════════════════════

def compute_l12(
    df_fulfillments: pd.DataFrame,
    sla_threshold_hours: float | None = None,
    wismo_ticket_cost: float | None = None,
    wasted_labor_cost: float | None = None,
) -> pd.DataFrame:
    """Computes L12 Fulfillment SLA Risk Score per fulfillment.

    Formulas:
      Fulfillment Delay (Hours) = (Fulfillment Created At − Order Created At) / 3600
      Breach = Fulfillment Delay > SLA Threshold (default 48h)
      Loss per Delayed Order = (WISMO Ticket Cost × Ticket Volume) + Wasted Labor Cost

    Required/Expected Columns:
      - order_id
      - order_created_at
      - fulfillment_created_at
      - [optional] wismo_ticket_count (from support tool join; nullable)
      - [optional] cancelled_at (order cancellation timestamp; nullable)

    Fallback:
      - If wismo_ticket_count is null -> compute SLA-breach portion only (time-based),
        flag support_cost_unavailable = True (NEVER assume 0 tickets).
      - If sla_threshold_hours is unset -> default to 48.0h with estimation flag.
    """
    df = df_fulfillments.copy()

    # Default costs
    ticket_cost = wismo_ticket_cost or L12_DEFAULT_WISMO_TICKET_COST
    labor_cost = wasted_labor_cost or L12_DEFAULT_WASTED_LABOR_COST
    default_sla = sla_threshold_hours or L12_DEFAULT_DISPATCH_SLA_HOURS

    # SLA Threshold
    if "sla_threshold_hours" not in df.columns:
        df["sla_threshold_hours"] = default_sla
        df["is_sla_threshold_estimated"] = True
    else:
        df["is_sla_threshold_estimated"] = df["sla_threshold_hours"].isna()
        df["sla_threshold_hours"] = df["sla_threshold_hours"].fillna(default_sla).astype(float)

    # Calculate fulfillment delay in hours
    order_dt = pd.to_datetime(df["order_created_at"])
    fulf_dt = pd.to_datetime(df["fulfillment_created_at"])
    delay_hours = (fulf_dt - order_dt).dt.total_seconds() / 3600.0
    df["fulfillment_delay_hours"] = delay_hours

    # Breach flag: delay > sla_threshold_hours
    is_breached = delay_hours > df["sla_threshold_hours"]
    df["is_sla_breached"] = is_breached

    # Check WISMO support ticket linkage
    if "wismo_ticket_count" not in df.columns:
        df["wismo_ticket_count"] = np.nan

    is_support_unavail = df["wismo_ticket_count"].isna()
    df["support_cost_unavailable"] = is_support_unavail

    wismo_count = df["wismo_ticket_count"].fillna(0.0).astype(float)
    df["wismo_support_loss"] = np.where(
        is_support_unavail,
        np.nan,
        wismo_count * ticket_cost,
    )

    # Wasted labor: applies if fulfillment created AFTER order was cancelled
    if "cancelled_at" in df.columns and not df["cancelled_at"].isna().all():
        cancel_dt = pd.to_datetime(df["cancelled_at"])
        is_wasted_labor = (~cancel_dt.isna()) & (fulf_dt > cancel_dt)
    else:
        is_wasted_labor = pd.Series(False, index=df.index)

    df["is_wasted_labor"] = is_wasted_labor
    df["wasted_labor_loss"] = np.where(is_wasted_labor, labor_cost, 0.0)

    # Total Loss per Delayed Order
    # If support cost is unavailable, loss reflects wasted labor only, flagged accordingly
    total_loss = np.where(
        is_breached,
        df["wasted_labor_loss"] + df["wismo_support_loss"].fillna(0.0),
        df["wasted_labor_loss"],
    )
    df["sla_delayed_order_loss"] = total_loss

    df["l12_status"] = np.where(
        is_breached,
        np.where(is_support_unavail, "BreachedSupportUnavail", "BreachedLoss"),
        "WithinSLA",
    )

    return df


def aggregate_l12(df: pd.DataFrame) -> dict:
    """Aggregates L12 Fulfillment SLA Risk across all fulfillments."""
    total_fulfillments = len(df)
    breached_mask = df["is_sla_breached"] == True
    within_mask = df["is_sla_breached"] == False
    support_unavail_mask = df["support_cost_unavailable"] == True
    wasted_labor_mask = df["is_wasted_labor"] == True

    breached_count = int(breached_mask.sum())
    breach_rate_pct = (breached_count / total_fulfillments * 100.0) if total_fulfillments > 0 else 0.0

    total_loss = float(df["sla_delayed_order_loss"].sum()) if total_fulfillments > 0 else 0.0
    total_wasted_labor = float(df["wasted_labor_loss"].sum()) if total_fulfillments > 0 else 0.0
    total_wismo_loss = float(df.loc[~df["support_cost_unavailable"], "wismo_support_loss"].sum()) if (~df["support_cost_unavailable"]).any() else 0.0

    valid_delays = df["fulfillment_delay_hours"]
    avg_delay = float(valid_delays.mean()) if len(valid_delays) > 0 else 0.0

    return {
        "fulfillments_evaluated": total_fulfillments,
        "fulfillments_within_sla": int(within_mask.sum()),
        "fulfillments_breached": breached_count,
        "breach_rate_pct": round(breach_rate_pct, 2),
        "orders_support_cost_unavailable": int(support_unavail_mask.sum()),
        "orders_with_wasted_labor": int(wasted_labor_mask.sum()),
        "total_sla_delay_loss": round(total_loss, 2),
        "loss_breakdown": {
            "wismo_ticket_loss": round(total_wismo_loss, 2),
            "wasted_labor_loss": round(total_wasted_labor, 2),
        },
        "avg_fulfillment_delay_hours": round(avg_delay, 1),
    }

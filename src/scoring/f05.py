"""src/scoring/f05.py — F05: Shipping Cost Recovery.

Business Definition:
    F05 measures the difference between shipping collected from customers
    and actual shipping cost paid to carriers.

Formula:
    shipping_delta = shipping_charged_to_customer − actual_shipping_cost

    Surplus: shipping_delta > 0
    Deficit: shipping_delta < 0
    Net Shipping Position = Σ(shipping_delta) across ALL orders.

Key distinction from F04:
    F05 is the storewide shipping balance ledger (surplus vs deficit).
    F04 is the product-profit-eroding free shipping leakage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_f05(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-order shipping delta.

    Adds:
        ``shipping_delta``   — positive = surplus (overcharged), negative = deficit
        ``f05_surplus``      — True where delta > 0
        ``f05_deficit``      — True where delta < 0
    """
    df = df.copy()
    charged = df["shipping_charged_to_customer"].fillna(0.0)
    actual = df["actual_shipping_cost"].fillna(0.0)
    df["shipping_delta"] = charged - actual
    df["f05_surplus"] = df["shipping_delta"] > 0.0
    df["f05_deficit"] = df["shipping_delta"] < 0.0
    return df


def aggregate_f05(df: pd.DataFrame) -> dict:
    """Aggregate shipping cost recovery across all orders (net sum).

    Deduplicates on ``order_id`` to avoid double-counting multi-item orders.

    Returns dict with:
        orders_evaluated, orders_surplus, orders_deficit,
        total_surplus, total_deficit, net_shipping_position
    """
    deduped = df.drop_duplicates(subset="order_id") if "order_id" in df.columns else df

    surplus_mask = deduped["f05_surplus"]
    deficit_mask = deduped["f05_deficit"]

    total_surplus = float(deduped.loc[surplus_mask, "shipping_delta"].sum()) if surplus_mask.any() else 0.0
    total_deficit = float(deduped.loc[deficit_mask, "shipping_delta"].sum()) if deficit_mask.any() else 0.0
    net_position = float(deduped["shipping_delta"].sum()) if len(deduped) > 0 else 0.0

    return {
        "orders_evaluated": len(deduped),
        "orders_surplus": int(surplus_mask.sum()),
        "orders_deficit": int(deficit_mask.sum()),
        "total_surplus": total_surplus,
        "total_deficit": total_deficit,
        "net_shipping_position": net_position,
    }

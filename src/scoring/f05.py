"""src/scoring/f05.py — F05: Shipping Cost Recovery.

Formula (internally consistent per spec audit):
    shipping_delta = shipping_charged_to_customer − actual_shipping_cost

    F05_total = Σ(shipping_delta) across ALL orders (net sum, not filtered).

Key difference from F01/F03/F04:
    F05 aggregates BOTH surpluses (overcharges) and deficits (undercharges)
    into a net position.  A positive net means the store overall over-recovers
    shipping costs; a negative net means it's subsidizing shipping.
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
    df["shipping_delta"] = (
        df["shipping_charged_to_customer"] - df["actual_shipping_cost"]
    )
    df["f05_surplus"] = df["shipping_delta"] > 0
    df["f05_deficit"] = df["shipping_delta"] < 0
    return df


def aggregate_f05(df: pd.DataFrame) -> dict:
    """Aggregate shipping cost recovery across all orders (net sum).

    Deduplicates on ``order_id`` to avoid double-counting multi-item orders
    (shipping is an order-level cost).

    Returns dict with:
        orders_evaluated, orders_surplus, orders_deficit,
        total_surplus, total_deficit, net_shipping_position
    """
    deduped = df.drop_duplicates(subset="order_id")

    surplus_mask = deduped["f05_surplus"]
    deficit_mask = deduped["f05_deficit"]

    total_surplus = float(deduped.loc[surplus_mask, "shipping_delta"].sum())
    total_deficit = float(deduped.loc[deficit_mask, "shipping_delta"].sum())
    net_position = float(deduped["shipping_delta"].sum())

    return {
        "orders_evaluated": len(deduped),
        "orders_surplus": int(surplus_mask.sum()),
        "orders_deficit": int(deficit_mask.sum()),
        "total_surplus": total_surplus,
        "total_deficit": total_deficit,
        "net_shipping_position": net_position,
    }

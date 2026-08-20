"""F05: Shipping Cost Recovery."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_f05_normalized_score(charged: float, actual: float) -> float:
    """Computes F05 Shipping Cost Recovery Score (0–100 scale).
    Formula: (Shipping Fee Charged to Customer / Actual Courier Delivery Fee) * 100
    """
    if actual > 0:
        return (charged / actual) * 100.0
    elif actual == 0:
        if charged == 0:
            return 100.0  # 0 cost & 0 charged: full cost recovery (no deficit)
        else:
            return 100.0  # Charged customer with 0 courier cost: full recovery + surplus
    return 0.0


def compute_f05(df: pd.DataFrame) -> pd.DataFrame:
    """Computes per-order shipping delta (charged - actual) and normalized recovery score."""
    df = df.copy()
    charged = df["shipping_charged_to_customer"].fillna(0.0)
    actual = df["actual_shipping_cost"].fillna(0.0)
    df["shipping_delta"] = charged - actual
    df["f05_surplus"] = df["shipping_delta"] > 0.0
    df["f05_deficit"] = df["shipping_delta"] < 0.0
    df["shipping_recovery_score_pct"] = np.where(
        actual > 0,
        (charged / actual) * 100.0,
        np.where(charged == 0, 100.0, 100.0),
    )
    return df


def aggregate_f05(df: pd.DataFrame) -> dict:
    """Aggregates storewide shipping cost recovery surplus/deficit position."""
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

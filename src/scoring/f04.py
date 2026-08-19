"""src/scoring/f04.py — F04: Free-Shipping Leakage Score.

Calculates volumetric weight and financial leakage on orders where free shipping was granted
or courier cost exceeded charged amount on unprofitable orders.

Formulas:
    Chargeable weight = max(actual_weight, volumetric_weight)
    Volumetric weight (kg) = (L_cm * W_cm * H_cm) / 5000 (if dims present)
    
    Formula A: Courier Cost - Shipping Charged (unrecovered courier cost)
    Formula B: max(0, Courier Cost - Product Gross Profit) (net absorbed cash loss)
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from src.config import (
    VOLUMETRIC_DIVISOR,
    FREE_SHIPPING_THRESHOLD,
    F04_FORMULA_CHOICE,
)


def compute_chargeable_weight(df_line_items: pd.DataFrame) -> pd.DataFrame:
    """Computes volumetric weight per line item and returns aggregated order chargeable weight."""
    df = df_line_items.copy()
    
    # Check if dimensions exist
    has_dims = df["length_cm"].notna() & df["width_cm"].notna() & df["height_cm"].notna()
    
    df["volumetric_weight_kg"] = np.where(
        has_dims,
        (df["length_cm"] * df["width_cm"] * df["height_cm"]) / VOLUMETRIC_DIVISOR,
        np.nan,
    )
    
    # Chargeable weight per item: max(actual, volumetric) if volumetric exists, else actual
    df["item_chargeable_weight"] = np.where(
        df["volumetric_weight_kg"].notna(),
        np.maximum(df["product_weight_kg"].fillna(0.0), df["volumetric_weight_kg"]),
        df["product_weight_kg"].fillna(0.0),
    )
    
    # Rollup to order level
    order_weights = df.groupby("order_id")["item_chargeable_weight"].sum().rename("order_chargeable_weight")
    return order_weights.to_frame()


def compute_f04(df_orders: pd.DataFrame, 
                df_line_items: pd.DataFrame,
                formula: str | None = None) -> pd.DataFrame:
    """Computes F04 Free-Shipping Leakage per order.

    Parameters:
        df_orders: Order-level DataFrame
        df_line_items: Line-item level DataFrame
        formula: "formula_a" or "formula_b" (default: config.F04_FORMULA_CHOICE)
    """
    formula = formula or F04_FORMULA_CHOICE
    
    # Compute product gross profit per order (excluding returned items)
    items = df_line_items.copy()
    if "is_returned" in items.columns:
        items = items[~items["is_returned"]]
    
    items["item_margin"] = items["net_selling_price"] - items["cogs_total"].fillna(0.0)
    order_product_profit = items.groupby("order_id")["item_margin"].sum().rename("product_gross_profit")
    
    # Chargeable weight rollup
    order_weight = compute_chargeable_weight(df_line_items)
    
    merged = df_orders.merge(order_product_profit, on="order_id", how="left")
    merged = merged.merge(order_weight, on="order_id", how="left")
    merged["product_gross_profit"] = merged["product_gross_profit"].fillna(0.0)
    
    # Compute leakage
    if formula == "formula_a":
        # Full unrecovered courier cost on free/subsidized orders
        merged["f04_leakage"] = np.where(
            merged["shipping_charged_to_customer"] < merged["actual_shipping_cost"],
            merged["actual_shipping_cost"] - merged["shipping_charged_to_customer"],
            0.0,
        )
    else:  # formula_b (net cash loss absorbed by merchant)
        uncovered_shipping = merged["actual_shipping_cost"] - merged["shipping_charged_to_customer"]
        merged["f04_leakage"] = np.maximum(0.0, uncovered_shipping - merged["product_gross_profit"])
    
    merged["f04_flagged"] = merged["f04_leakage"] > 0
    return merged


def aggregate_f04(df_scored: pd.DataFrame) -> dict:
    """Aggregates F04 Free-Shipping Leakage results."""
    deduped = df_scored.drop_duplicates(subset="order_id")
    flagged = deduped[deduped["f04_flagged"]]
    
    return {
        "orders_evaluated": len(deduped),
        "orders_flagged": len(flagged),
        "total_leakage": float(flagged["f04_leakage"].sum()),
        "avg_leakage_per_flagged_order": float(flagged["f04_leakage"].mean()) if len(flagged) > 0 else 0.0,
    }

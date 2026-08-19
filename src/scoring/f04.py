"""src/scoring/f04.py — F04: Free-Shipping Leakage Score.

Business Definition:
    F04 identifies cases where free (or subsidized) shipping causes the merchant's
    shipping cost to consume the product profit and create a net loss.

Formulas:
    chargeable_weight = max(actual_weight, volumetric_weight)
    volumetric_weight (kg) = (L_cm * W_cm * H_cm) / 5000 (if dims present, else actual)
    
    product_profit = sum(net_selling_price - cogs_total) across active items
    uncovered_shipping = max(0.0, actual_shipping_cost - shipping_charged_to_customer)
    f04_leakage = max(0.0, uncovered_shipping - product_profit)
    f04_flagged = f04_leakage > 0
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
    
    # Check if dimensions exist and are non-null
    has_dims = (
        ("length_cm" in df.columns) & ("width_cm" in df.columns) & ("height_cm" in df.columns)
    )
    if has_dims:
        valid_dims = df["length_cm"].notna() & df["width_cm"].notna() & df["height_cm"].notna()
        df["volumetric_weight_kg"] = np.where(
            valid_dims,
            (df["length_cm"] * df["width_cm"] * df["height_cm"]) / VOLUMETRIC_DIVISOR,
            np.nan,
        )
    else:
        df["volumetric_weight_kg"] = np.nan
    
    weight_col = df["product_weight_kg"].fillna(0.0) if "product_weight_kg" in df.columns else pd.Series(0.0, index=df.index)
    
    # Chargeable weight per item: max(actual, volumetric) if volumetric exists, else actual
    df["item_chargeable_weight"] = np.where(
        df["volumetric_weight_kg"].notna(),
        np.maximum(weight_col, df["volumetric_weight_kg"]),
        weight_col,
    )
    
    if "order_id" in df.columns:
        order_weights = df.groupby("order_id")["item_chargeable_weight"].sum().rename("order_chargeable_weight")
        return order_weights.to_frame()
    else:
        df["order_chargeable_weight"] = df["item_chargeable_weight"]
        return df[["order_chargeable_weight"]]


def compute_f04(
    df_orders: pd.DataFrame, 
    df_line_items: pd.DataFrame | None = None,
    formula: str | None = None,
) -> pd.DataFrame:
    """Computes F04 Free-Shipping Leakage per order.

    Parameters:
        df_orders: Order-level DataFrame (or single merged DataFrame)
        df_line_items: Line-item level DataFrame (optional if df_orders is already combined)
        formula: "formula_b" (true net loss, default) or "formula_a" (unrecovered shipping)
    """
    formula = formula or F04_FORMULA_CHOICE

    if df_line_items is not None:
        items = df_line_items.copy()
        if "is_returned" in items.columns:
            items = items[~items["is_returned"]]
        
        cogs = items["cogs_total"].fillna(0.0) if "cogs_total" in items.columns else 0.0
        price = items["net_selling_price"] if "net_selling_price" in items.columns else items["selling_price"]
        items["item_margin"] = price - cogs
        order_product_profit = items.groupby("order_id")["item_margin"].sum().rename("product_gross_profit")
        
        order_weight = compute_chargeable_weight(df_line_items)
        
        merged = df_orders.merge(order_product_profit, on="order_id", how="left")
        merged = merged.merge(order_weight, on="order_id", how="left")
        merged["product_gross_profit"] = merged["product_gross_profit"].fillna(0.0)
    else:
        merged = df_orders.copy()
        if "product_gross_profit" not in merged.columns:
            price = merged["net_selling_price"] if "net_selling_price" in merged.columns else merged.get("selling_price", 0.0)
            cogs = merged.get("cogs_total", 0.0)
            cogs = pd.Series(cogs, index=merged.index).fillna(0.0)
            merged["product_gross_profit"] = price - cogs
        if "order_chargeable_weight" not in merged.columns:
            merged["order_chargeable_weight"] = merged.get("product_weight_kg", 0.0)

    shipping_charged = merged["shipping_charged_to_customer"].fillna(0.0)
    actual_shipping = merged["actual_shipping_cost"].fillna(0.0)
    uncovered_shipping = np.maximum(0.0, actual_shipping - shipping_charged)
    merged["uncovered_shipping"] = uncovered_shipping

    # Compute leakage
    if formula == "formula_a":
        # Gross unrecovered shipping subsidy
        merged["f04_leakage"] = uncovered_shipping
    else:
        # Formula B: True net financial leakage (uncovered shipping exceeding product profit)
        merged["f04_leakage"] = np.maximum(0.0, uncovered_shipping - merged["product_gross_profit"])

    merged["f04_flagged"] = merged["f04_leakage"] > 0
    return merged


def aggregate_f04(df_scored: pd.DataFrame) -> dict:
    """Aggregates F04 Free-Shipping Leakage results."""
    deduped = df_scored.drop_duplicates(subset="order_id") if "order_id" in df_scored.columns else df_scored
    flagged = deduped[deduped["f04_flagged"]]
    total_orders = len(deduped)
    flagged_count = len(flagged)
    total_leakage = float(flagged["f04_leakage"].sum()) if flagged_count > 0 else 0.0
    leakage_rate_pct = (flagged_count / total_orders * 100.0) if total_orders > 0 else 0.0
    avg_leakage = (total_leakage / flagged_count) if flagged_count > 0 else 0.0

    return {
        "orders_evaluated": total_orders,
        "orders_flagged": flagged_count,
        "leakage_rate_pct": leakage_rate_pct,
        "total_leakage": total_leakage,
        "avg_leakage_per_flagged_order": avg_leakage,
    }

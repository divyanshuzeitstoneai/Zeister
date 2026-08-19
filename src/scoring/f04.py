"""F04: Free-Shipping Leakage Score."""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import VOLUMETRIC_DIVISOR, FREE_SHIPPING_THRESHOLD, F04_FORMULA_CHOICE


def compute_chargeable_weight(df_line_items: pd.DataFrame) -> pd.DataFrame:
    """Computes volumetric weight per line item and aggregates order chargeable weight."""
    df = df_line_items.copy()
    
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
    formula_choice: str = F04_FORMULA_CHOICE,
) -> pd.DataFrame:
    """Computes F04 Free Shipping Leakage per order."""
    orders = df_orders.copy()
    
    if df_line_items is not None:
        items = df_line_items.copy()
        
        if "is_returned" in items.columns:
            active_items = items[~items["is_returned"]].copy()
        else:
            active_items = items.copy()
            
        if "net_selling_price" in active_items.columns:
            price_col = active_items["net_selling_price"]
        elif "selling_price" in active_items.columns:
            price_col = active_items["selling_price"]
        else:
            price_col = pd.Series(0.0, index=active_items.index)
            
        cogs_col = active_items["cogs_total"].fillna(0.0) if "cogs_total" in active_items.columns else pd.Series(0.0, index=active_items.index)
        active_items["item_profit"] = price_col - cogs_col
        
        order_profit = active_items.groupby("order_id")["item_profit"].sum().rename("product_profit")
        orders = orders.merge(order_profit, on="order_id", how="left")
        orders["product_profit"] = orders["product_profit"].fillna(0.0)
        
        order_weights = compute_chargeable_weight(items)
        orders = orders.merge(order_weights, on="order_id", how="left")
    else:
        if "product_profit" not in orders.columns:
            price = orders["net_sales"] if "net_sales" in orders.columns else (orders["gross_sales"] if "gross_sales" in orders.columns else 0.0)
            cogs = orders["cogs_total"].fillna(0.0) if "cogs_total" in orders.columns else 0.0
            orders["product_profit"] = price - cogs

    charged_shipping = orders["shipping_charged_to_customer"].fillna(0.0) if "shipping_charged_to_customer" in orders.columns else pd.Series(0.0, index=orders.index)
    actual_shipping = orders["actual_shipping_cost"].fillna(0.0) if "actual_shipping_cost" in orders.columns else pd.Series(0.0, index=orders.index)

    orders["uncovered_shipping"] = np.maximum(0.0, actual_shipping - charged_shipping)
    orders["f04_leakage"] = np.maximum(0.0, orders["uncovered_shipping"] - orders["product_profit"])
    orders["f04_flagged"] = orders["f04_leakage"] > 0.0

    return orders


def aggregate_f04(orders_df: pd.DataFrame) -> dict:
    """Aggregates overall F04 Free-Shipping Leakage metrics."""
    deduped = orders_df.drop_duplicates(subset="order_id") if "order_id" in orders_df.columns else orders_df
    total_orders = len(deduped)
    flagged = deduped[deduped["f04_flagged"]]
    flagged_count = len(flagged)
    total_leakage = float(flagged["f04_leakage"].sum()) if flagged_count > 0 else 0.0
    avg_leakage = (total_leakage / flagged_count) if flagged_count > 0 else 0.0
    order_leakage_pct = (flagged_count / total_orders * 100.0) if total_orders > 0 else 0.0

    return {
        "orders_evaluated": total_orders,
        "orders_flagged": flagged_count,
        "order_leakage_pct": order_leakage_pct,
        "total_f04_leakage": total_leakage,
        "avg_f04_leakage_per_flagged_order": avg_leakage,
    }

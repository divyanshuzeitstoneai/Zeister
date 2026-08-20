"""F09: Channel Margin Divergence Score."""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import PRIMARY_CHANNEL


def compute_f09_normalized_score(mkt_unit_profit: float, web_unit_profit: float) -> float:
    """Computes F09 Channel Margin Normalization Score (0-100 scale).
    Formula: (Marketplace Unit Profit / Website Unit Profit) * 100
    """
    if web_unit_profit != 0:
        return (mkt_unit_profit / web_unit_profit) * 100.0
    elif web_unit_profit == 0:
        if mkt_unit_profit == 0:
            return 100.0  # Equal margin parity at zero profit
        else:
            return 0.0   # Marketplace profit with 0 web profit - div-by-zero fallback
    return 0.0


def compute_f09(
    df_orders: pd.DataFrame, 
    df_line_items: pd.DataFrame, 
    primary_channel: str | None = None,
) -> dict:
    """Computes F09 Channel Margin Divergence loss vs primary direct channel."""
    primary_channel = primary_channel or PRIMARY_CHANNEL
    
    if "channel" not in df_line_items.columns:
        orders_sub = df_orders[["order_id", "channel"]].copy()
        if "is_cancelled" in df_orders.columns:
            orders_sub["is_cancelled"] = df_orders["is_cancelled"]
        merged = df_line_items.merge(orders_sub, on="order_id", how="inner")
    else:
        merged = df_line_items.copy()
    
    if "is_cancelled" in merged.columns:
        merged = merged[~merged["is_cancelled"]].copy()
    if "is_returned" in merged.columns:
        merged = merged[~merged["is_returned"]].copy()
    
    if "cogs_total" in merged.columns:
        valid_items = merged[merged["cogs_total"].notna()].copy()
    else:
        valid_items = merged.copy()
        valid_items["cogs_total"] = 0.0

    if len(valid_items) == 0:
        return {
            "primary_channel": primary_channel,
            "total_divergence_loss": 0.0,
            "channel_breakdown": {},
        }

    if "net_selling_price" in valid_items.columns:
        price_col = valid_items["net_selling_price"]
    elif "selling_price" in valid_items.columns:
        price_col = valid_items["selling_price"]
    else:
        price_col = pd.Series(0.0, index=valid_items.index)

    if "channel_fee_pct" in valid_items.columns:
        fee_amt = price_col * valid_items["channel_fee_pct"].fillna(0.0)
    else:
        fee_amt = 0.0

    valid_items["item_margin"] = price_col - valid_items["cogs_total"] - fee_amt
    qty_col = valid_items["quantity"].fillna(1) if "quantity" in valid_items.columns else pd.Series(1, index=valid_items.index)
    valid_items["quantity_clean"] = qty_col

    primary_df = valid_items[valid_items["channel"].str.lower() == primary_channel.lower()]
    if len(primary_df) == 0:
        primary_unit_profit = float(valid_items["item_margin"].sum() / valid_items["quantity_clean"].sum()) if valid_items["quantity_clean"].sum() > 0 else 0.0
    else:
        primary_unit_profit = float(primary_df["item_margin"].sum() / primary_df["quantity_clean"].sum())

    divergence_losses = {}
    total_loss = 0.0

    for ch, group in valid_items.groupby(valid_items["channel"].str.upper()):
        if ch.lower() == primary_channel.lower():
            continue
        
        ch_units = float(group["quantity_clean"].sum())
        ch_unit_profit = float(group["item_margin"].sum() / ch_units) if ch_units > 0 else 0.0
        
        unit_diff = max(0.0, primary_unit_profit - ch_unit_profit)
        ch_loss = unit_diff * ch_units
        norm_score = compute_f09_normalized_score(ch_unit_profit, primary_unit_profit)
        
        total_loss += ch_loss
        divergence_losses[ch] = {
            "units_sold": int(ch_units),
            "unit_profit": ch_unit_profit,
            "unit_profit_gap": unit_diff,
            "channel_divergence_loss": ch_loss,
            "normalized_score": norm_score,
        }

    return {
        "primary_channel": primary_channel,
        "primary_channel_unit_profit": primary_unit_profit,
        "total_divergence_loss": total_loss,
        "channel_breakdown": divergence_losses,
    }

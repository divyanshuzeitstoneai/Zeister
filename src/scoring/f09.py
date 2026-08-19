"""src/scoring/f09.py — F09: Channel Margin Divergence Score.

Business Definition:
    F09 measures the profit difference between the primary/high-margin channel
    (e.g., Direct Web) and lower-margin channels (e.g., Amazon, TikTok Shop, Walmart).
    It quantifies the financial drag incurred when sales volume shifts to lower-margin channels.

Formulas:
    channel_unit_profit = (net_selling_price - cogs_total - channel_fee_amount - channel_shipping) / quantity
    unit_divergence = max(0.0, primary_channel_unit_profit - marketplace_channel_unit_profit)
    f09_loss = sum(units_sold * unit_divergence)

Business Example:
    Primary direct channel profit = $57/unit
    Marketplace channel profit = $32/unit
    Difference = $25/unit
    For 1,000 units -> $25,000 divergence loss.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import PRIMARY_CHANNEL


def compute_f09(
    df_orders: pd.DataFrame, 
    df_line_items: pd.DataFrame, 
    primary_channel: str | None = None,
) -> dict:
    """Computes F09 Channel Margin Divergence.

    Parameters:
        df_orders: Order-level DataFrame (contains order_id, channel, is_cancelled)
        df_line_items: Line-item level DataFrame (contains order_id, prices, COGS, category, channel_fee_pct)
        primary_channel: Benchmark channel (default: config.PRIMARY_CHANNEL, "web")

    Returns:
        Dictionary containing channel profit breakdown and financial divergence loss.
    """
    primary_channel = primary_channel or PRIMARY_CHANNEL
    
    # Merge channel into line items if not already present
    if "channel" not in df_line_items.columns:
        orders_sub = df_orders[["order_id", "channel"]].copy()
        if "is_cancelled" in df_orders.columns:
            orders_sub["is_cancelled"] = df_orders["is_cancelled"]
        merged = df_line_items.merge(orders_sub, on="order_id", how="inner")
    else:
        merged = df_line_items.copy()
    
    # Exclude cancelled orders and returns
    if "is_cancelled" in merged.columns:
        merged = merged[~merged["is_cancelled"]].copy()
    if "is_returned" in merged.columns:
        merged = merged[~merged["is_returned"]].copy()
    
    # Clean margin calculation requires valid COGS
    if "cogs_total" in merged.columns:
        computable = merged.dropna(subset=["cogs_total"]).copy()
    else:
        computable = merged.copy()
        computable["cogs_total"] = 0.0

    if len(computable) == 0:
        return {
            "channels_evaluated": [],
            "primary_channel": primary_channel,
            "total_divergence_loss": 0.0,
            "channel_breakdown": {},
        }
    
    # Calculate item-level costs and profit
    qty = computable["quantity"] if "quantity" in computable.columns else pd.Series(1, index=computable.index)
    qty = qty.replace(0, 1)
    
    price = computable["net_selling_price"] if "net_selling_price" in computable.columns else computable["selling_price"]
    cogs = computable["cogs_total"].fillna(0.0)
    fee_pct = computable["channel_fee_pct"].fillna(0.0) if "channel_fee_pct" in computable.columns else pd.Series(0.0, index=computable.index)
    fee_amt = price * fee_pct
    
    computable["channel_fee_amount"] = fee_amt
    computable["item_net_profit"] = price - cogs - fee_amt
    computable["unit_net_profit"] = computable["item_net_profit"] / qty
    
    # Primary channel benchmark profit per unit by category (or overall)
    primary_items = computable[computable["channel"] == primary_channel]
    
    if len(primary_items) > 0:
        if "category" in computable.columns:
            cat_primary_avg = primary_items.groupby("category")["unit_net_profit"].mean().to_dict()
            overall_primary_avg = float(primary_items["unit_net_profit"].mean())
        else:
            cat_primary_avg = {}
            overall_primary_avg = float(primary_items["unit_net_profit"].mean())
    else:
        # Fallback to store average if primary channel is missing
        if "category" in computable.columns:
            cat_primary_avg = computable.groupby("category")["unit_net_profit"].mean().to_dict()
            overall_primary_avg = float(computable["unit_net_profit"].mean())
        else:
            cat_primary_avg = {}
            overall_primary_avg = float(computable["unit_net_profit"].mean())

    channel_results = {}
    total_loss = 0.0
    
    channels = computable["channel"].unique()
    for ch in channels:
        if ch == primary_channel:
            continue
        
        ch_df = computable[computable["channel"] == ch].copy()
        if "category" in ch_df.columns and cat_primary_avg:
            ch_df["benchmark_unit_profit"] = ch_df["category"].map(cat_primary_avg).fillna(overall_primary_avg)
        else:
            ch_df["benchmark_unit_profit"] = overall_primary_avg
        
        ch_df["unit_divergence"] = np.maximum(0.0, ch_df["benchmark_unit_profit"] - ch_df["unit_net_profit"])
        ch_qty = ch_df["quantity"] if "quantity" in ch_df.columns else pd.Series(1, index=ch_df.index)
        ch_loss = float((ch_df["unit_divergence"] * ch_qty).sum())
        total_loss += ch_loss
        
        channel_results[ch] = {
            "units_sold": int(ch_qty.sum()),
            "gross_revenue": float(ch_df["selling_price"].sum()) if "selling_price" in ch_df.columns else float(price.sum()),
            "avg_channel_profit_per_unit": float(ch_df["unit_net_profit"].mean()),
            "benchmark_primary_profit_per_unit": float(ch_df["benchmark_unit_profit"].mean()),
            "total_channel_fee": float(ch_df["channel_fee_amount"].sum()),
            "divergence_loss": ch_loss,
        }
    
    return {
        "primary_channel": primary_channel,
        "channels_evaluated": list(channels),
        "total_divergence_loss": total_loss,
        "channel_breakdown": channel_results,
    }

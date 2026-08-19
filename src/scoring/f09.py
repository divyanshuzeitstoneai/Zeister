"""src/scoring/f09.py — F09: Channel Margin Divergence Score.

Measures profitability divergence across multi-channel sales (e.g. Amazon, TikTok Shop, Walmart vs Direct Web).
Calculates the profit loss incurred when volume shifts to lower-margin marketplace channels.

Formula:
    channel_gross_profit = net_selling_price - cogs_total - (net_selling_price * channel_fee_pct)
    divergence = primary_channel_avg_profit - marketplace_channel_avg_profit
    f09_loss = sum(channel_units * divergence)
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from src.config import PRIMARY_CHANNEL, F09_FORMULA_CHOICE


def compute_f09(df_orders: pd.DataFrame, 
                df_line_items: pd.DataFrame, 
                primary_channel: str | None = None) -> dict:
    """Computes F09 Channel Margin Divergence.

    Parameters:
        df_orders: Order-level DataFrame (contains channel mapping)
        df_line_items: Line-item level DataFrame (contains prices, COGS, category)
        primary_channel: Benchmark channel (default: config.PRIMARY_CHANNEL)

    Returns:
        Dictionary containing channel profit breakdown and financial divergence loss.
    """
    primary_channel = primary_channel or PRIMARY_CHANNEL
    
    # Merge channel into line items
    merged = df_line_items.merge(
        df_orders[["order_id", "channel", "is_cancelled"]],
        on="order_id",
        how="inner",
    )
    
    # Exclude cancelled orders and returns
    merged = merged[~merged["is_cancelled"] & ~merged["is_returned"]].copy()
    
    # Drop rows with missing COGS for clean margin calculation
    computable = merged.dropna(subset=["cogs_total"]).copy()
    if len(computable) == 0:
        return {
            "channels_evaluated": [],
            "primary_channel": primary_channel,
            "total_divergence_loss": 0.0,
            "channel_breakdown": {},
        }
    
    # Calculate item-level contribution profit
    computable["channel_fee_amount"] = computable["net_selling_price"] * computable["channel_fee_pct"].fillna(0.0)
    computable["item_net_profit"] = computable["net_selling_price"] - computable["cogs_total"] - computable["channel_fee_amount"]
    
    # Calculate category-level primary channel profit benchmarks
    primary_items = computable[computable["channel"] == primary_channel]
    
    if len(primary_items) == 0:
        # Fallback to store average if primary channel is missing
        cat_primary_avg = computable.groupby("category")["item_net_profit"].mean().to_dict()
    else:
        cat_primary_avg = primary_items.groupby("category")["item_net_profit"].mean().to_dict()
    
    # Compare each marketplace channel to primary channel benchmark
    channel_results = {}
    total_loss = 0.0
    
    for ch in computable["channel"].unique():
        if ch == primary_channel:
            continue
        
        ch_df = computable[computable["channel"] == ch].copy()
        ch_df["benchmark_profit"] = ch_df["category"].map(cat_primary_avg).fillna(ch_df["item_net_profit"])
        ch_df["unit_divergence"] = np.maximum(0.0, ch_df["benchmark_profit"] - ch_df["item_net_profit"])
        
        ch_loss = float(ch_df["unit_divergence"].sum())
        total_loss += ch_loss
        
        channel_results[ch] = {
            "units_sold": len(ch_df),
            "gross_revenue": float(ch_df["selling_price"].sum()),
            "avg_channel_profit": float(ch_df["item_net_profit"].mean()),
            "total_channel_fee": float(ch_df["channel_fee_amount"].sum()),
            "divergence_loss": ch_loss,
        }
    
    return {
        "primary_channel": primary_channel,
        "total_divergence_loss": total_loss,
        "channel_breakdown": channel_results,
    }

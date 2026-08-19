"""tests/test_f09.py — Tests for F09 Channel Margin Divergence."""

import pandas as pd
import pytest
from src.scoring.f09 import compute_f09


def test_f09_single_channel_store_zero_divergence():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "channel": ["web", "web"],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "category": ["fashion", "fashion"],
        "selling_price": [100.0, 100.0],
        "net_selling_price": [100.0, 100.0],
        "cogs_total": [40.0, 40.0],
        "channel_fee_pct": [0.0, 0.0],
        "is_returned": [False, False],
    })
    res = compute_f09(df_orders, df_items, primary_channel="web")
    assert res["total_divergence_loss"] == 0.0
    assert len(res["channel_breakdown"]) == 0


def test_f09_marketplace_fee_causes_divergence_loss():
    # Web order: $100 price, $40 COGS, 0% fee -> $60 profit
    # Amazon order: $100 price, $40 COGS, 15% fee ($15) -> $45 profit
    # Divergence loss = $60 - $45 = $15
    df_orders = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-AMZ"],
        "channel": ["web", "amazon"],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-AMZ"],
        "category": ["electronics", "electronics"],
        "selling_price": [100.0, 100.0],
        "net_selling_price": [100.0, 100.0],
        "cogs_total": [40.0, 40.0],
        "channel_fee_pct": [0.0, 0.15],
        "is_returned": [False, False],
    })
    res = compute_f09(df_orders, df_items, primary_channel="web")
    assert res["total_divergence_loss"] == pytest.approx(15.0)
    assert res["channel_breakdown"]["amazon"]["divergence_loss"] == pytest.approx(15.0)

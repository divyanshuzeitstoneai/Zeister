"""tests/test_f09.py — Comprehensive Tests for F09 Channel Margin Divergence.

Validates the business formula:
    unit_divergence = max(0, primary_channel_unit_profit - marketplace_channel_unit_profit)
    f09_loss = sum(units_sold * unit_divergence)

Tests verify:
    - Core business example: $57 primary profit vs $32 marketplace profit = $25 * 1000 units = $25,000 divergence
    - Single channel store (zero divergence)
    - Equal margins across channels (zero divergence)
    - Multiple marketplace channels (Amazon, TikTok, Walmart)
    - Channel fee variations and category benchmarks
"""

import pandas as pd
import pytest
from src.scoring.f09 import compute_f09


def test_f09_core_business_example():
    """Core Business Spec Example:
    Primary Web Channel: Selling $100, COGS $43, Fee $0 -> Unit Profit = $57.00
    Marketplace Channel: Selling $100, COGS $43, Fee 25% ($25) -> Unit Profit = $32.00
    Unit Divergence = $57 - $32 = $25.00
    Volume: 1,000 units on Marketplace
    -> Divergence Loss = 1,000 * $25 = $25,000.00.
    """
    df_orders = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-MKT"],
        "channel": ["web", "amazon"],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-MKT"],
        "category": ["fashion", "fashion"],
        "quantity": [100, 1000],
        "selling_price": [10000.0, 100000.0],
        "net_selling_price": [10000.0, 100000.0],
        "cogs_total": [4300.0, 43000.0],
        "channel_fee_pct": [0.0, 0.25],  # 0% on web, 25% on amazon
        "is_returned": [False, False],
    })
    res = compute_f09(df_orders, df_items, primary_channel="web")
    assert res["primary_channel"] == "web"
    assert res["total_divergence_loss"] == pytest.approx(25000.0)
    assert res["channel_breakdown"]["amazon"]["units_sold"] == 1000
    assert res["channel_breakdown"]["amazon"]["avg_channel_profit_per_unit"] == pytest.approx(32.0)
    assert res["channel_breakdown"]["amazon"]["benchmark_primary_profit_per_unit"] == pytest.approx(57.0)
    assert res["channel_breakdown"]["amazon"]["divergence_loss"] == pytest.approx(25000.0)


def test_f09_single_channel_store_zero_divergence():
    """Store selling only through primary web channel -> zero divergence loss."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "channel": ["web", "web"],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "category": ["fashion", "fashion"],
        "quantity": [1, 1],
        "selling_price": [100.0, 100.0],
        "net_selling_price": [100.0, 100.0],
        "cogs_total": [40.0, 40.0],
        "channel_fee_pct": [0.0, 0.0],
        "is_returned": [False, False],
    })
    res = compute_f09(df_orders, df_items, primary_channel="web")
    assert res["total_divergence_loss"] == 0.0
    assert len(res["channel_breakdown"]) == 0


def test_f09_equal_margins_zero_divergence():
    """Marketplace has the same profit per unit as Web -> zero divergence loss."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-AMZ"],
        "channel": ["web", "amazon"],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-AMZ"],
        "category": ["electronics", "electronics"],
        "quantity": [1, 10],
        "selling_price": [100.0, 1000.0],
        "net_selling_price": [100.0, 1000.0],
        "cogs_total": [50.0, 500.0],
        "channel_fee_pct": [0.0, 0.0],
        "is_returned": [False, False],
    })
    res = compute_f09(df_orders, df_items, primary_channel="web")
    assert res["total_divergence_loss"] == 0.0


def test_f09_multiple_marketplaces():
    """Multiple marketplace channels with different fees:
    Web: Profit $50/unit
    Amazon (fee 15%): Profit $35/unit -> Divergence $15 * 10 units = $150
    TikTok (fee 20%): Profit $30/unit -> Divergence $20 * 5 units = $100
    Total divergence = $250.
    """
    df_orders = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-AMZ", "ORD-TT"],
        "channel": ["web", "amazon", "tiktok"],
        "is_cancelled": [False, False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-AMZ", "ORD-TT"],
        "category": ["beauty", "beauty", "beauty"],
        "quantity": [1, 10, 5],
        "selling_price": [100.0, 1000.0, 500.0],
        "net_selling_price": [100.0, 1000.0, 500.0],
        "cogs_total": [50.0, 500.0, 250.0],
        "channel_fee_pct": [0.0, 0.15, 0.20],
        "is_returned": [False, False, False],
    })
    res = compute_f09(df_orders, df_items, primary_channel="web")
    assert res["total_divergence_loss"] == pytest.approx(250.0)
    assert res["channel_breakdown"]["amazon"]["divergence_loss"] == pytest.approx(150.0)
    assert res["channel_breakdown"]["tiktok"]["divergence_loss"] == pytest.approx(100.0)

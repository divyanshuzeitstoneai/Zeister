"""Tests for F09 Channel Margin Divergence."""

import pandas as pd
import pytest
from src.scoring.f09 import compute_f09


def test_f09_core_business_example():
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
        "channel_fee_pct": [0.0, 0.25],
        "is_returned": [False, False],
    })
    res = compute_f09(df_orders, df_items, primary_channel="web")
    assert res["primary_channel"] == "web"
    assert res["total_divergence_loss"] == pytest.approx(25000.0)
    assert res["channel_breakdown"]["AMAZON"]["units_sold"] == 1000
    assert res["channel_breakdown"]["AMAZON"]["unit_profit"] == pytest.approx(32.0)
    assert res["channel_breakdown"]["AMAZON"]["channel_divergence_loss"] == pytest.approx(25000.0)


def test_f09_single_channel_store_zero_divergence():
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
    assert res["channel_breakdown"]["AMAZON"]["channel_divergence_loss"] == pytest.approx(150.0)
    assert res["channel_breakdown"]["TIKTOK"]["channel_divergence_loss"] == pytest.approx(100.0)

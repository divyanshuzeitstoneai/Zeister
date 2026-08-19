"""tests/test_f02.py — Tests for F02 Discount Dependency Score."""

import pandas as pd
import pytest
from src.scoring.f02 import compute_f02


def test_f02_no_discounts_zero_loss():
    df_orders = pd.DataFrame({"order_id": ["ORD-1"], "is_cancelled": [False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "selling_price": [100.0],
        "discount_given": [0.0],
        "is_discounted": [False],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == 0.0
    assert res["is_breached"] is False
    assert res["f02_loss"] == 0.0


def test_f02_below_healthy_threshold():
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [100.0, 100.0],
        "discount_given": [10.0, 0.0],
        "is_discounted": [True, False],
    })
    # Discounted share = 100 / 200 = 50%
    # With healthy share = 60%, excess = 0 -> loss = 0
    res = compute_f02(df_orders, df_items, healthy_share=0.60)
    assert res["discounted_share"] == 0.50
    assert res["is_breached"] is False
    assert res["f02_loss"] == 0.0


def test_f02_above_healthy_threshold_calculates_loss():
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [100.0, 100.0],
        "discount_given": [20.0, 0.0],
        "is_discounted": [True, False],
    })
    # Total sales: 200, discounted sales: 100 (50% share)
    # Healthy share: 20% -> excess share = 30%
    # Avg discount depth on discounted = 20 / 100 = 20%
    # Loss = 200 * 0.30 * 0.20 = 12.0
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == 0.50
    assert res["is_breached"] is True
    assert res["f02_loss"] == pytest.approx(12.0)

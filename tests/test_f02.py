"""Tests for F02 Discount Dependency Score."""

import pandas as pd
import pytest
from src.scoring.f02 import compute_f02


def test_f02_zero_discounted_sales():
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [100.0, 150.0],
        "discount_given": [0.0, 0.0],
        "is_discounted": [False, False],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["total_sales"] == 250.0
    assert res["discounted_sales"] == 0.0
    assert res["discounted_share"] == 0.0
    assert res["f02_score_pct"] == 0.0
    assert res["is_breached"] is False
    assert res["f02_loss"] == 0.0


def test_f02_all_sales_discounted_100_percent():
    df_orders = pd.DataFrame({"order_id": ["ORD-1"], "is_cancelled": [False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "selling_price": [500.0],
        "discount_given": [50.0],
        "is_discounted": [True],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == 1.0
    assert res["f02_score_pct"] == 100.0
    assert res["excess_share"] == pytest.approx(0.80)
    assert res["avg_discount_depth"] == pytest.approx(0.10)
    assert res["f02_loss"] == pytest.approx(40.0)


def test_f02_discounted_revenue_below_benchmark():
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [100.0, 900.0],
        "discount_given": [20.0, 0.0],
        "is_discounted": [True, False],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == pytest.approx(0.10)
    assert res["f02_score_pct"] == pytest.approx(10.0)
    assert res["excess_share"] == 0.0
    assert res["is_breached"] is False
    assert res["f02_loss"] == 0.0


def test_f02_boundary_exactly_at_benchmark():
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [200.0, 800.0],
        "discount_given": [40.0, 0.0],
        "is_discounted": [True, False],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == pytest.approx(0.20)
    assert res["excess_share"] == 0.0
    assert res["is_breached"] is False
    assert res["f02_loss"] == 0.0


def test_f02_above_benchmark_calculates_loss():
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [100.0, 100.0],
        "discount_given": [20.0, 0.0],
        "is_discounted": [True, False],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == pytest.approx(0.50)
    assert res["f02_score_pct"] == pytest.approx(50.0)
    assert res["is_breached"] is True
    assert res["f02_loss"] == pytest.approx(12.0)


def test_f02_different_discount_depths():
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2", "ORD-3"], "is_cancelled": [False, False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2", "ORD-3"],
        "selling_price": [200.0, 300.0, 500.0],
        "discount_given": [50.0, 100.0, 0.0],
        "is_discounted": [True, True, False],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["total_sales"] == 1000.0
    assert res["discounted_sales"] == 500.0
    assert res["avg_discount_depth"] == pytest.approx(0.30)
    assert res["f02_loss"] == pytest.approx(90.0)


def test_f02_zero_total_revenue_handles_cleanly():
    df_orders = pd.DataFrame({"order_id": ["ORD-1"], "is_cancelled": [False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "selling_price": [0.0],
        "discount_given": [0.0],
        "is_discounted": [False],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["total_sales"] == 0.0
    assert res["discounted_share"] == 0.0
    assert res["f02_loss"] == 0.0


def test_f02_revenue_share_not_order_count():
    df_orders = pd.DataFrame({"order_id": [f"ORD-{i}" for i in range(10)], "is_cancelled": [False] * 10})
    df_items = pd.DataFrame({
        "order_id": [f"ORD-{i}" for i in range(10)],
        "selling_price": [10.0] * 9 + [910.0],
        "discount_given": [0.0] * 9 + [91.0],
        "is_discounted": [False] * 9 + [True],
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["total_sales"] == 1000.0
    assert res["discounted_sales"] == 910.0
    assert res["discounted_share"] == pytest.approx(0.91)
    assert res["is_breached"] is True

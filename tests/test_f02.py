"""tests/test_f02.py — Comprehensive Tests for F02 Discount Dependency Score.

Validates the business formula:
    discounted_sales_share = total_discounted_sales / total_sales
    f02_score_pct = discounted_sales_share * 100
    excess_discount_share = max(0, discounted_sales_share - healthy_benchmark)
    f02_loss = total_sales * excess_discount_share * avg_discount_depth
"""

import pandas as pd
import pytest
from src.scoring.f02 import compute_f02


def test_f02_zero_discounted_sales():
    """Store with 0% discounted sales -> share 0%, loss $0."""
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
    """100% of sales discounted with 10% average discount depth."""
    df_orders = pd.DataFrame({"order_id": ["ORD-1"], "is_cancelled": [False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "selling_price": [500.0],
        "discount_given": [50.0],
        "is_discounted": [True],
    })
    # Total sales: 500, Discounted sales: 500 (100% share)
    # Healthy benchmark: 20% -> Excess share: 80%
    # Discount depth: 50 / 500 = 10%
    # Loss = 500 * 0.80 * 0.10 = 40.0
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == 1.0
    assert res["f02_score_pct"] == 100.0
    assert res["excess_share"] == pytest.approx(0.80)
    assert res["avg_discount_depth"] == pytest.approx(0.10)
    assert res["f02_loss"] == pytest.approx(40.0)


def test_f02_discounted_revenue_below_benchmark():
    """Discounted revenue share 10% is below 20% benchmark -> excess 0, loss $0."""
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [100.0, 900.0],
        "discount_given": [20.0, 0.0],
        "is_discounted": [True, False],
    })
    # Discounted share = 100 / 1000 = 10%
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == pytest.approx(0.10)
    assert res["f02_score_pct"] == pytest.approx(10.0)
    assert res["excess_share"] == 0.0
    assert res["is_breached"] is False
    assert res["f02_loss"] == 0.0


def test_f02_boundary_exactly_at_benchmark():
    """Boundary: Discounted revenue share exactly at 20% benchmark -> excess 0, breached False."""
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [200.0, 800.0],
        "discount_given": [40.0, 0.0],
        "is_discounted": [True, False],
    })
    # Discounted share = 200 / 1000 = 20%
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == pytest.approx(0.20)
    assert res["excess_share"] == 0.0
    assert res["is_breached"] is False
    assert res["f02_loss"] == 0.0


def test_f02_above_benchmark_calculates_loss():
    """Discounted revenue share 50% vs 20% benchmark with 20% avg discount depth."""
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [100.0, 100.0],
        "discount_given": [20.0, 0.0],
        "is_discounted": [True, False],
    })
    # Total sales: 200, discounted sales: 100 (50% share)
    # Excess share: 50% - 20% = 30%
    # Avg discount depth: 20 / 100 = 20%
    # Loss: 200 * 0.30 * 0.20 = 12.0
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["discounted_share"] == pytest.approx(0.50)
    assert res["f02_score_pct"] == pytest.approx(50.0)
    assert res["is_breached"] is True
    assert res["f02_loss"] == pytest.approx(12.0)


def test_f02_different_discount_depths():
    """Multiple orders with varying discount depths."""
    df_orders = pd.DataFrame({"order_id": ["ORD-1", "ORD-2", "ORD-3"], "is_cancelled": [False, False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2", "ORD-3"],
        "selling_price": [200.0, 300.0, 500.0],
        "discount_given": [50.0, 100.0, 0.0],  # 25% and 33.3% depth on discounted
        "is_discounted": [True, True, False],
    })
    # Total sales: 1000. Discounted sales: 500 (50% share).
    # Benchmark: 20% -> excess share: 30%
    # Total discounts given: 150 -> avg depth on discounted = 150 / 500 = 30%
    # Loss = 1000 * 0.30 * 0.30 = 90.0
    res = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res["total_sales"] == 1000.0
    assert res["discounted_sales"] == 500.0
    assert res["avg_discount_depth"] == pytest.approx(0.30)
    assert res["f02_loss"] == pytest.approx(90.0)


def test_f02_zero_total_revenue_handles_cleanly():
    """Empty or 0 revenue dataset returns 0.0 with no ZeroDivisionError."""
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
    """Proves F02 measures revenue share, NOT order count share."""
    # 9 small non-discounted orders ($10 each = $90)
    # 1 huge discounted order ($910)
    # Order count discounted = 10%, but revenue discounted = 91%
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

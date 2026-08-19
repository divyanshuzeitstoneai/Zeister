"""Tests for F12 Revenue Quality Score."""

import pandas as pd
import pytest
from src.scoring.f12 import compute_f12


def test_f12_full_reconciliation_example():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1"],
        "gross_sales": [1000.0],
        "shipping_charged_to_customer": [10.0],
        "actual_shipping_cost": [50.0],
        "gateway_fee": [30.0],
        "chargeback_amount": [80.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-1"],
        "selling_price": [800.0, 200.0],
        "discount_given": [80.0, 20.0],
        "net_selling_price": [720.0, 180.0],
        "is_returned": [False, True],
        "refund_amount": [0.0, 120.0],
        "restocking_cost": [0.0, 30.0],
    })

    res = compute_f12(df_orders, df_items)
    assert res["gross_sales"] == 1000.0
    assert res["leak_breakdown"]["discounts"] == 100.0
    assert res["leak_breakdown"]["returns_and_restocking"] == 150.0
    assert res["leak_breakdown"]["shipping_deficits"] == 40.0
    assert res["leak_breakdown"]["gateway_fees"] == 30.0
    assert res["leak_breakdown"]["chargebacks"] == 80.0
    assert res["total_leakage"] == pytest.approx(400.0)
    assert res["net_retained_revenue"] == pytest.approx(600.0)
    assert res["revenue_quality_score_pct"] == pytest.approx(60.0)
    assert res["leakage_ratio_pct"] == pytest.approx(40.0)


def test_f12_zero_leakage_100_percent_quality():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-PERFECT"],
        "shipping_charged_to_customer": [15.0],
        "actual_shipping_cost": [10.0],
        "gateway_fee": [0.0],
        "chargeback_amount": [0.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-PERFECT"],
        "selling_price": [500.0],
        "discount_given": [0.0],
        "net_selling_price": [500.0],
        "is_returned": [False],
        "refund_amount": [0.0],
        "restocking_cost": [0.0],
    })

    res = compute_f12(df_orders, df_items)
    assert res["gross_sales"] == 500.0
    assert res["total_leakage"] == 0.0
    assert res["net_retained_revenue"] == 500.0
    assert res["revenue_quality_score_pct"] == pytest.approx(100.0)
    assert res["leakage_ratio_pct"] == 0.0


def test_f12_100_percent_leakage_0_percent_quality():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-ZERO-RET"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [0.0],
        "gateway_fee": [0.0],
        "chargeback_amount": [0.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-ZERO-RET"],
        "selling_price": [100.0],
        "discount_given": [100.0],
        "net_selling_price": [0.0],
        "is_returned": [False],
        "refund_amount": [0.0],
        "restocking_cost": [0.0],
    })

    res = compute_f12(df_orders, df_items)
    assert res["gross_sales"] == 100.0
    assert res["total_leakage"] == 100.0
    assert res["net_retained_revenue"] == 0.0
    assert res["revenue_quality_score_pct"] == 0.0
    assert res["leakage_ratio_pct"] == 100.0


def test_f12_negative_retained_revenue():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-NEG"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [50.0],
        "gateway_fee": [10.0],
        "chargeback_amount": [100.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-NEG"],
        "selling_price": [100.0],
        "discount_given": [0.0],
        "net_selling_price": [100.0],
        "is_returned": [True],
        "refund_amount": [100.0],
        "restocking_cost": [20.0],
    })
    res = compute_f12(df_orders, df_items)
    assert res["total_leakage"] == pytest.approx(280.0)
    assert res["net_retained_revenue"] == pytest.approx(-180.0)
    assert res["revenue_quality_score_pct"] == pytest.approx(-180.0)


def test_f12_zero_gross_sales():
    df_orders = pd.DataFrame({"order_id": ["ORD-EMPTY"], "is_cancelled": [False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-EMPTY"],
        "selling_price": [0.0],
        "discount_given": [0.0],
        "is_returned": [False],
    })
    res = compute_f12(df_orders, df_items)
    assert res["gross_sales"] == 0.0
    assert res["revenue_quality_score_pct"] == 100.0

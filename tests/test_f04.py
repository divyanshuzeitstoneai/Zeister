"""Tests for F04 Free-Shipping Leakage Score."""

import numpy as np
import pandas as pd
import pytest
from src.scoring.f04 import compute_f04, compute_chargeable_weight, aggregate_f04


def test_f04_core_business_example():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-SPEC"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [22.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-SPEC"],
        "selling_price": [51.0],
        "net_selling_price": [51.0],
        "cogs_total": [33.0],
        "product_weight_kg": [2.0],
        "is_returned": [False],
    })
    res = compute_f04(df_orders, df_items)
    assert res["f04_flagged"].iloc[0] == True
    assert res["f04_leakage"].iloc[0] == pytest.approx(4.0)


def test_f04_profitable_free_shipping_order():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-PROF"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [15.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-PROF"],
        "selling_price": [100.0],
        "net_selling_price": [100.0],
        "cogs_total": [40.0],
        "product_weight_kg": [1.0],
        "is_returned": [False],
    })
    res = compute_f04(df_orders, df_items)
    assert res["f04_flagged"].iloc[0] == False
    assert res["f04_leakage"].iloc[0] == 0.0


def test_f04_boundary_exact_breakeven():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-EVEN"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [15.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-EVEN"],
        "selling_price": [50.0],
        "net_selling_price": [50.0],
        "cogs_total": [35.0],
        "product_weight_kg": [1.0],
        "is_returned": [False],
    })
    res = compute_f04(df_orders, df_items)
    assert res["f04_flagged"].iloc[0] == False
    assert res["f04_leakage"].iloc[0] == 0.0


def test_f04_paid_shipping_partially_covers_courier():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-PAID"],
        "shipping_charged_to_customer": [10.0],
        "actual_shipping_cost": [22.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-PAID"],
        "selling_price": [30.0],
        "net_selling_price": [30.0],
        "cogs_total": [22.0],
        "product_weight_kg": [2.0],
        "is_returned": [False],
    })
    res = compute_f04(df_orders, df_items)
    assert res["f04_flagged"].iloc[0] == True
    assert res["f04_leakage"].iloc[0] == pytest.approx(4.0)


def test_f04_volumetric_weight_greater_than_actual():
    df_items = pd.DataFrame({
        "order_id": ["ORD-VOL"],
        "product_weight_kg": [2.0],
        "length_cm": [50.0],
        "width_cm": [40.0],
        "height_cm": [30.0],
    })
    weights = compute_chargeable_weight(df_items)
    assert weights.loc["ORD-VOL", "order_chargeable_weight"] == pytest.approx(12.0)


def test_f04_actual_weight_greater_than_volumetric():
    df_items = pd.DataFrame({
        "order_id": ["ORD-ACT"],
        "product_weight_kg": [10.0],
        "length_cm": [10.0],
        "width_cm": [10.0],
        "height_cm": [10.0],
    })
    weights = compute_chargeable_weight(df_items)
    assert weights.loc["ORD-ACT", "order_chargeable_weight"] == pytest.approx(10.0)


def test_f04_missing_dimensions_fallback():
    df_items = pd.DataFrame({
        "order_id": ["ORD-NODIM"],
        "product_weight_kg": [4.5],
        "length_cm": [np.nan],
        "width_cm": [np.nan],
        "height_cm": [np.nan],
    })
    weights = compute_chargeable_weight(df_items)
    assert weights.loc["ORD-NODIM", "order_chargeable_weight"] == pytest.approx(4.5)


def test_f04_multi_item_order_rollup():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-MULTI"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [25.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-MULTI", "ORD-MULTI"],
        "selling_price": [20.0, 15.0],
        "net_selling_price": [20.0, 15.0],
        "cogs_total": [12.0, 8.0],
        "product_weight_kg": [1.0, 1.0],
        "is_returned": [False, False],
    })
    res = compute_f04(df_orders, df_items)
    assert res["f04_flagged"].iloc[0] == True
    assert res["f04_leakage"].iloc[0] == pytest.approx(10.0)


def test_f04_aggregation():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "shipping_charged_to_customer": [0.0, 0.0],
        "actual_shipping_cost": [22.0, 15.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [51.0, 100.0],
        "net_selling_price": [51.0, 100.0],
        "cogs_total": [33.0, 40.0],
        "is_returned": [False, False],
    })
    res = compute_f04(df_orders, df_items)
    agg = aggregate_f04(res)
    assert agg["orders_evaluated"] == 2
    assert agg["orders_flagged"] == 1
    assert agg["order_leakage_pct"] == 50.0
    assert agg["total_f04_leakage"] == pytest.approx(4.0)
    assert agg["avg_f04_leakage_per_flagged_order"] == pytest.approx(4.0)

"""tests/test_f04.py — Tests for F04 Free-Shipping Leakage & Volumetric Weight."""

import numpy as np
import pandas as pd
import pytest
from src.scoring.f04 import compute_f04, compute_chargeable_weight, aggregate_f04


def test_volumetric_weight_greater_than_actual():
    # 50cm x 40cm x 30cm = 60,000 cm3 / 5000 = 12.0 kg volumetric vs 2.0 kg actual
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "product_weight_kg": [2.0],
        "length_cm": [50.0],
        "width_cm": [40.0],
        "height_cm": [30.0],
    })
    res = compute_chargeable_weight(df_items)
    assert res.loc["ORD-1", "order_chargeable_weight"] == pytest.approx(12.0)


def test_missing_dimensions_falls_back_to_actual_weight():
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "product_weight_kg": [3.5],
        "length_cm": [np.nan],
        "width_cm": [np.nan],
        "height_cm": [np.nan],
    })
    res = compute_chargeable_weight(df_items)
    assert res.loc["ORD-1", "order_chargeable_weight"] == pytest.approx(3.5)


def test_f04_formula_a_vs_formula_b():
    # Worked example from doc: Price $51, COGS $33 -> Profit $18. Courier $22, Charged $0
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [22.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "selling_price": [51.0],
        "net_selling_price": [51.0],
        "cogs_total": [33.0],
        "product_weight_kg": [2.0],
        "length_cm": [np.nan],
        "width_cm": [np.nan],
        "height_cm": [np.nan],
        "is_returned": [False],
    })
    
    # Formula A: Courier ($22) - Charged ($0) = $22.0
    res_a = compute_f04(df_orders, df_items, formula="formula_a")
    assert res_a["f04_leakage"].iloc[0] == pytest.approx(22.0)
    
    # Formula B: Uncovered Shipping ($22) - Product Profit ($18) = $4.0
    res_b = compute_f04(df_orders, df_items, formula="formula_b")
    assert res_b["f04_leakage"].iloc[0] == pytest.approx(4.0)


def test_f04_profitable_order_no_leakage_in_formula_b():
    # Price $100, COGS $40 -> Profit $60. Courier $15, Charged $0.
    # Product profit ($60) easily absorbs Courier ($15) -> Leakage = 0
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [15.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "selling_price": [100.0],
        "net_selling_price": [100.0],
        "cogs_total": [40.0],
        "product_weight_kg": [1.0],
        "length_cm": [np.nan],
        "width_cm": [np.nan],
        "height_cm": [np.nan],
        "is_returned": [False],
    })
    res = compute_f04(df_orders, df_items, formula="formula_b")
    assert not res["f04_flagged"].iloc[0]
    assert res["f04_leakage"].iloc[0] == 0.0

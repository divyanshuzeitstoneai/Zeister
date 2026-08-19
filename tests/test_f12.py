"""tests/test_f12.py — Tests for F12 Revenue Leakage Ratio."""

import pandas as pd
import pytest
from src.scoring.f12 import compute_f12


def test_f12_revenue_leakage_aggregation():
    # Order 1: Gross $100, Discount $10, Net $90. Shipping actual $8, charged $5 (deficit $3), GW $3, Chargeback $0, Return $0
    # Leakage = $10 (disc) + $0 (ret) + $3 (ship) + $3 (gw) = $16
    # Leakage ratio = 16 / 100 = 16% -> Retention = 84%
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1"],
        "shipping_charged_to_customer": [5.0],
        "actual_shipping_cost": [8.0],
        "gateway_fee": [3.0],
        "chargeback_amount": [0.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "selling_price": [100.0],
        "discount_given": [10.0],
        "net_selling_price": [90.0],
        "is_returned": [False],
        "refund_amount": [0.0],
        "restocking_cost": [0.0],
    })
    
    res = compute_f12(df_orders, df_items)
    assert res["gross_sales"] == 100.0
    assert res["total_leakage"] == pytest.approx(16.0)
    assert res["leakage_ratio_pct"] == pytest.approx(16.0)
    assert res["revenue_retention_pct"] == pytest.approx(84.0)

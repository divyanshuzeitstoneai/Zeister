"""tests/test_f10.py — Tests for F10 Return & Refund Profitability."""

import pandas as pd
import pytest
from src.scoring.f10 import compute_f10


def test_f10_no_returns_zero_loss():
    df_orders = pd.DataFrame({"order_id": ["ORD-1"]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "category": ["fashion"],
        "selling_price": [100.0],
        "is_returned": [False],
        "refund_amount": [0.0],
        "restocking_cost": [0.0],
    })
    res = compute_f10(df_orders, df_items)
    assert res["total_returns"] == 0
    assert res["total_f10_loss"] == 0.0


def test_f10_return_loss_includes_refund_and_restocking():
    df_orders = pd.DataFrame({"order_id": ["ORD-1"]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "category": ["fashion"],
        "selling_price": [100.0],
        "is_returned": [True],
        "refund_amount": [100.0],
        "restocking_cost": [10.0],
    })
    # Refund ($100) + Restocking ($10) + Reverse Shipping ($4.50) = $114.50
    res = compute_f10(df_orders, df_items)
    assert res["total_returns"] == 1
    assert res["total_refunded_amount"] == 100.0
    assert res["total_restocking_cost"] == 10.0
    assert res["total_f10_loss"] == pytest.approx(114.50)

"""tests/test_f11.py — Tests for F11 Product Net Profit Score."""

import pandas as pd
import pytest
from src.scoring.f11 import compute_f11


def test_f11_sku_net_profit_calculation():
    # 2 orders with SKU-A: Order 1 non-returned, Order 2 returned
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "actual_shipping_cost": [10.0, 10.0],
        "gateway_fee": [3.0, 3.0],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "product_id": ["SKU-A", "SKU-A"],
        "category": ["beauty", "beauty"],
        "quantity": [1, 1],
        "selling_price": [100.0, 100.0],
        "net_selling_price": [100.0, 100.0],
        "cogs_total": [30.0, 30.0],
        "is_returned": [False, True],
        "refund_amount": [0.0, 100.0],
        "restocking_cost": [0.0, 5.0],
    })
    
    sku_df = compute_f11(df_orders, df_items)
    assert len(sku_df) == 1
    row = sku_df.iloc[0]
    assert row["product_id"] == "SKU-A"
    assert row["total_units"] == 2
    assert row["avg_return_rate"] == 0.50  # 1 of 2 returned

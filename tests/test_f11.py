"""tests/test_f11.py — Comprehensive Tests for F11 Order Profitability.

Validates the latest business specification:
    F11 calculates order-level bottom-line true profit:
    Order Profit = Total Money Collected − COGS − Outbound Courier Shipping − Gateway Fees − Expected Refund Cost

Tests verify:
    - Core business example: $80 collected − $50 COGS − $22 shipping − $3 gateway − $8 expected refund = -$3.00
    - Profitable order
    - Negative-profit order
    - Exactly zero profit boundary
    - Discounted orders
    - Free shipping vs paid shipping
    - Multi-item orders
    - Missing value handling
    - Aggregation metrics
"""

import numpy as np
import pandas as pd
import pytest
from src.scoring.f11 import compute_f11, aggregate_f11


def test_f11_core_business_example():
    """Core Business Spec Example:
    Collected revenue = $80 (after discount, $0 shipping charged)
    COGS = $50
    Shipping cost = $22
    Gateway fee = $3
    Expected refund cost = $8
    -> Expected Order Net Profit = $80 - $50 - $22 - $3 - $8 = -$3.00.
    """
    df_orders = pd.DataFrame({
        "order_id": ["ORD-SPEC"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [22.0],
        "gateway_fee": [3.0],
        "expected_refund_cost": [8.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-SPEC"],
        "selling_price": [100.0],
        "discount_given": [20.0],
        "net_selling_price": [80.0],
        "cogs_total": [50.0],
    })

    res = compute_f11(df_orders, df_items)
    assert len(res) == 1
    row = res.iloc[0]
    assert row["total_money_collected"] == 80.0
    assert row["order_cogs"] == 50.0
    assert row["actual_shipping_cost"] == 22.0
    assert row["gateway_fee"] == 3.0
    assert row["order_expected_refund_cost"] == 8.0
    assert row["order_net_profit"] == pytest.approx(-3.0)
    assert row["is_unprofitable_order"] == True
    assert row["is_profitable_order"] == False


def test_f11_profitable_order():
    """Profitable order with paid shipping:
    Net merchandise = $120, Shipping charged = $10 -> Collected = $130.
    COGS = $40, Shipping actual = $12, Gateway = $4, Expected refund = $5.
    Net profit = 130 - 40 - 12 - 4 - 5 = $69.00.
    """
    df_orders = pd.DataFrame({
        "order_id": ["ORD-PROF"],
        "shipping_charged_to_customer": [10.0],
        "actual_shipping_cost": [12.0],
        "gateway_fee": [4.0],
        "expected_refund_cost": [5.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-PROF"],
        "net_selling_price": [120.0],
        "cogs_total": [40.0],
    })

    res = compute_f11(df_orders, df_items)
    row = res.iloc[0]
    assert row["total_money_collected"] == 130.0
    assert row["order_net_profit"] == pytest.approx(69.0)
    assert row["is_profitable_order"] == True
    assert row["is_unprofitable_order"] == False


def test_f11_boundary_exact_zero_profit():
    """Boundary: Order profit exactly 0.0 -> is_breakeven_order is True."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-ZERO"],
        "shipping_charged_to_customer": [0.0],
        "actual_shipping_cost": [10.0],
        "gateway_fee": [5.0],
        "expected_refund_cost": [5.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-ZERO"],
        "net_selling_price": [100.0],
        "cogs_total": [80.0],
    })
    # Collected 100 - COGS 80 - Ship 10 - GW 5 - Refund 5 = 0.0
    res = compute_f11(df_orders, df_items)
    row = res.iloc[0]
    assert row["order_net_profit"] == pytest.approx(0.0)
    assert row["is_breakeven_order"] == True
    assert row["is_profitable_order"] == False
    assert row["is_unprofitable_order"] == False


def test_f11_multi_item_order_aggregation():
    """Multi-item order correctly sums merchandise net price and COGS."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-MULTI"],
        "shipping_charged_to_customer": [5.0],
        "actual_shipping_cost": [15.0],
        "gateway_fee": [4.0],
        "expected_refund_cost": [6.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-MULTI", "ORD-MULTI", "ORD-MULTI"],
        "net_selling_price": [50.0, 30.0, 20.0],  # Total = 100
        "cogs_total": [20.0, 15.0, 10.0],         # Total = 45
    })
    # Total collected = 100 + 5 = 105.
    # Profit = 105 - 45 - 15 - 4 - 6 = 35.0
    res = compute_f11(df_orders, df_items)
    assert len(res) == 1
    row = res.iloc[0]
    assert row["order_net_merchandise_sales"] == 100.0
    assert row["order_cogs"] == 45.0
    assert row["order_net_profit"] == pytest.approx(35.0)


def test_f11_missing_values_handling():
    """Missing gateway fee or expected refund cost defaults to 0.0 without crashing."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-NULL"],
        "shipping_charged_to_customer": [np.nan],
        "actual_shipping_cost": [10.0],
        "gateway_fee": [np.nan],
        "expected_refund_cost": [np.nan],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-NULL"],
        "net_selling_price": [100.0],
        "cogs_total": [40.0],
    })
    # Collected 100 - COGS 40 - Ship 10 - GW 0 - Refund 0 = 50.0
    res = compute_f11(df_orders, df_items)
    row = res.iloc[0]
    assert row["order_net_profit"] == pytest.approx(50.0)


def test_f11_aggregation_metrics():
    """F11 storewide profitability aggregation."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "shipping_charged_to_customer": [0.0, 0.0],
        "actual_shipping_cost": [10.0, 10.0],
        "gateway_fee": [3.0, 3.0],
        "expected_refund_cost": [0.0, 0.0],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "net_selling_price": [100.0, 50.0],
        "cogs_total": [40.0, 60.0],
    })
    # ORD-1: 100 - 40 - 10 - 3 = +47 (profitable)
    # ORD-2: 50 - 60 - 10 - 3 = -23 (unprofitable)
    # Total collected = 150, Net profit = 24.0
    res = compute_f11(df_orders, df_items)
    agg = aggregate_f11(res)
    assert agg["orders_evaluated"] == 2
    assert agg["profitable_orders"] == 1
    assert agg["unprofitable_orders"] == 1
    assert agg["unprofitable_order_pct"] == 50.0
    assert agg["total_revenue_collected"] == 150.0
    assert agg["total_order_net_profit"] == pytest.approx(24.0)

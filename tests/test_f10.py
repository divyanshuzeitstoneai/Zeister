"""Tests for F10 Product Contribution Score."""

import pandas as pd
import pytest
from src.scoring.f10 import compute_f10, aggregate_f10


def test_f10_high_revenue_sku_with_high_returns_yields_negative_contribution():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1"],
        "actual_shipping_cost": [500.0],
        "gateway_fee": [250.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-1"],
        "product_id": ["SKU-HIGH-REV", "SKU-HIGH-REV"],
        "category": ["fashion", "fashion"],
        "quantity": [40, 60],
        "selling_price": [4000.0, 6000.0],
        "discount_given": [400.0, 600.0],
        "net_selling_price": [3600.0, 5400.0],
        "cogs_total": [1600.0, 2400.0],
        "is_returned": [False, True],
        "refund_amount": [0.0, 5400.0],
        "restocking_cost": [0.0, 600.0],
    })

    sku_df = compute_f10(df_orders, df_items, return_shipping_flat=4.50)
    assert len(sku_df) == 1
    row = sku_df.iloc[0]
    assert row["product_id"] == "SKU-HIGH-REV"
    assert row["gross_merchandise_revenue"] == 10000.0
    assert row["net_merchandise_revenue"] == 9000.0
    assert row["discounts_given"] == 1000.0
    assert row["cogs_total"] == 4000.0
    assert row["refund_loss"] == 5400.0
    assert row["restocking_loss"] == 600.0
    assert row["return_shipping_loss"] == pytest.approx(270.0)
    assert row["allocated_outbound_shipping"] == pytest.approx(500.0)
    assert row["allocated_gateway_fees"] == pytest.approx(250.0)
    assert row["product_contribution"] == pytest.approx(-2020.0)
    assert row["is_negative_contribution"] == True


def test_f10_healthy_profitable_sku():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1"],
        "actual_shipping_cost": [50.0],
        "gateway_fee": [25.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1"],
        "product_id": ["SKU-HEALTHY"],
        "category": ["beauty"],
        "quantity": [10],
        "selling_price": [1000.0],
        "discount_given": [100.0],
        "net_selling_price": [900.0],
        "cogs_total": [300.0],
        "is_returned": [False],
        "refund_amount": [0.0],
        "restocking_cost": [0.0],
    })

    sku_df = compute_f10(df_orders, df_items)
    row = sku_df.iloc[0]
    assert row["product_id"] == "SKU-HEALTHY"
    assert row["product_contribution"] == pytest.approx(525.0)
    assert row["is_negative_contribution"] == False
    assert row["contribution_margin_pct"] == pytest.approx(525.0 / 900.0 * 100.0)


def test_f10_aggregation_metrics():
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "actual_shipping_cost": [20.0, 20.0],
        "gateway_fee": [5.0, 5.0],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "product_id": ["SKU-A", "SKU-B"],
        "category": ["fashion", "beauty"],
        "quantity": [1, 1],
        "selling_price": [100.0, 100.0],
        "discount_given": [0.0, 0.0],
        "net_selling_price": [100.0, 100.0],
        "cogs_total": [30.0, 80.0],
        "is_returned": [False, True],
        "refund_amount": [0.0, 100.0],
        "restocking_cost": [0.0, 10.0],
    })

    sku_df = compute_f10(df_orders, df_items)
    agg = aggregate_f10(sku_df)
    assert agg["total_skus_evaluated"] == 2
    assert agg["negative_contribution_skus"] == 1
    assert agg["negative_sku_pct"] == 50.0
    assert agg["total_product_contribution"] == pytest.approx(45.0 - 119.50)

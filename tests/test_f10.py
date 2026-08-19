"""tests/test_f10.py — Comprehensive Tests for F10 Product Contribution.

Validates the latest business specification:
    F10 calculates SKU-level Product Contribution:
    Gross Revenue − Discounts − COGS − Refunds − Restocking − Return Shipping − Allocated Outbound Shipping − Allocated Gateway

Tests verify:
    - High-grossing SKU with high return rate yields negative true contribution
    - Profitable SKU with low return rate yields healthy contribution
    - Full cost breakdown (discounts, COGS, returns, reverse shipping, allocated fulfillment)
    - Aggregation metrics
"""

import pandas as pd
import pytest
from src.scoring.f10 import compute_f10, aggregate_f10


def test_f10_high_revenue_sku_with_high_returns_yields_negative_contribution():
    """Business Example:
    SKU-HIGH-REV generates $10,000 top-line gross revenue across 100 units.
    Discount = $1,000 (Net revenue = $9,000).
    COGS = $4,000 ($40/unit).
    60 units are returned (60% return rate):
      - Refunded amount = $5,400 (60 * $90 net price)
      - Restocking costs = $600 ($10/unit)
      - Return shipping = $270 (60 * $4.50)
    Outbound shipping allocated = $500.
    Gateway fees allocated = $250.

    True Product Contribution:
      $9,000 (Net Revenue)
      - $4,000 (COGS)
      - $5,400 (Refunds)
      - $600 (Restocking)
      - $270 (Return Shipping)
      - $500 (Outbound Shipping)
      - $250 (Gateway Fee)
      = -$2,020.00 (NEGATIVE contribution despite $10K gross sales!).
    """
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1"],
        "actual_shipping_cost": [500.0],
        "gateway_fee": [250.0],
        "is_cancelled": [False],
    })
    # 40 non-returned items ($90 net each), 60 returned items ($90 net each)
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
    assert row["gross_revenue"] == 10000.0
    assert row["net_revenue"] == 9000.0
    assert row["total_discounts"] == 1000.0
    assert row["total_cogs"] == 4000.0
    assert row["total_refunds"] == 5400.0
    assert row["total_restocking"] == 600.0
    assert row["total_return_shipping"] == pytest.approx(270.0)
    assert row["total_allocated_shipping"] == pytest.approx(500.0)
    assert row["total_allocated_gateway"] == pytest.approx(250.0)
    assert row["product_contribution"] == pytest.approx(-2020.0)
    assert row["is_negative_contribution"] == True


def test_f10_healthy_profitable_sku():
    """Healthy SKU with zero returns:
    Selling $1,000, Discount $100 -> Net $900.
    COGS $300, Outbound shipping $50, Gateway $25, Returns $0.
    Contribution = 900 - 300 - 50 - 25 = $525.00.
    """
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
    """F10 aggregation across healthy and unhealthy SKUs."""
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

    # SKU-A: 100 - 30 - 20 - 5 = +45
    # SKU-B: 100 - 80 - 100 - 10 - 4.50 - 20 - 5 = -119.50
    sku_df = compute_f10(df_orders, df_items)
    agg = aggregate_f10(sku_df)
    assert agg["skus_evaluated"] == 2
    assert agg["negative_contribution_skus"] == 1
    assert agg["negative_sku_pct"] == 50.0
    assert agg["total_product_contribution"] == pytest.approx(45.0 - 119.50)

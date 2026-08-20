"""tests/test_return_edge_cases.py — Validation of multi-item return edge cases (F10, F11, F12)."""

import numpy as np
import pandas as pd
import pytest

from src.scoring.f10 import compute_f10
from src.scoring.f11 import compute_f11
from src.scoring.f12 import compute_f12


def _create_multi_item_order(return_item_key: str | None = None, all_returned: bool = False):
    """Creates standard 3-item order:
    Item A = 200 (COGS 100)
    Item B = 500 (COGS 250)
    Item C = 100 (COGS 50)
    Total Revenue = 800
    Order-level Shipping = 80, Gateway = 24
    """
    df_orders = pd.DataFrame({
        "order_id": ["ORD-MULTI"],
        "actual_shipping_cost": [80.0],
        "shipping_charged_to_customer": [0.0],
        "gateway_fee": [24.0],
        "is_cancelled": [False],
    })

    items_data = [
        {"product_id": "SKU-A", "selling_price": 200.0, "net_selling_price": 200.0, "cogs_total": 100.0, "key": "A"},
        {"product_id": "SKU-B", "selling_price": 500.0, "net_selling_price": 500.0, "cogs_total": 250.0, "key": "B"},
        {"product_id": "SKU-C", "selling_price": 100.0, "net_selling_price": 100.0, "cogs_total": 50.0, "key": "C"},
    ]

    for item in items_data:
        item["order_id"] = "ORD-MULTI"
        item["quantity"] = 1
        item["discount_given"] = 0.0
        item["category"] = "fashion"
        if all_returned or item["key"] == return_item_key:
            item["is_returned"] = True
            item["refund_amount"] = item["net_selling_price"]
            item["restocking_cost"] = item["net_selling_price"] * 0.05
        else:
            item["is_returned"] = False
            item["refund_amount"] = 0.0
            item["restocking_cost"] = 0.0

    df_line_items = pd.DataFrame(items_data)
    return df_orders, df_line_items


def test_return_edge_case_1_most_expensive_item_returned():
    """TEST 1 — Return Item B ($500), the most expensive item in an $800 order."""
    df_orders, df_line_items = _create_multi_item_order(return_item_key="B")

    # 1. Verification of return identification and flags
    assert bool(df_line_items.loc[df_line_items["product_id"] == "SKU-B", "is_returned"].iloc[0]) is True
    assert bool(df_line_items.loc[df_line_items["product_id"] == "SKU-A", "is_returned"].iloc[0]) is False
    assert bool(df_line_items.loc[df_line_items["product_id"] == "SKU-C", "is_returned"].iloc[0]) is False

    # 2. F10 Product Contribution
    sku_df = compute_f10(df_orders, df_line_items, return_shipping_flat=4.50)
    row_a = sku_df[sku_df["product_id"] == "SKU-A"].iloc[0]
    row_b = sku_df[sku_df["product_id"] == "SKU-B"].iloc[0]
    row_c = sku_df[sku_df["product_id"] == "SKU-C"].iloc[0]

    # Revenue-weighted cost allocations:
    # A (25%): ship = 80 * 0.25 = 20, gw = 24 * 0.25 = 6
    # B (62.5%): ship = 80 * 0.625 = 50, gw = 24 * 0.625 = 15
    # C (12.5%): ship = 80 * 0.125 = 10, gw = 24 * 0.125 = 3
    assert row_a["allocated_outbound_shipping"] == pytest.approx(20.0)
    assert row_a["allocated_gateway_fees"] == pytest.approx(6.0)
    assert row_b["allocated_outbound_shipping"] == pytest.approx(50.0)
    assert row_b["allocated_gateway_fees"] == pytest.approx(15.0)
    assert row_c["allocated_outbound_shipping"] == pytest.approx(10.0)
    assert row_c["allocated_gateway_fees"] == pytest.approx(3.0)

    # Allocations sum to 100% of order level costs
    assert (row_a["allocated_outbound_shipping"] + row_b["allocated_outbound_shipping"] + row_c["allocated_outbound_shipping"]) == pytest.approx(80.0)
    assert (row_a["allocated_gateway_fees"] + row_b["allocated_gateway_fees"] + row_c["allocated_gateway_fees"]) == pytest.approx(24.0)

    # Product contributions:
    # A: 200 - 100(cogs) - 20(ship) - 6(gw) = 74.0
    # B: 500 - 250(cogs) - 500(refund) - 25(restock) - 4.50(ret_ship) - 50(ship) - 15(gw) = -344.50
    # C: 100 - 50(cogs) - 10(ship) - 3(gw) = 37.0
    assert row_a["product_contribution"] == pytest.approx(74.0)
    assert row_b["product_contribution"] == pytest.approx(-344.50)
    assert row_c["product_contribution"] == pytest.approx(37.0)
    assert bool(row_b["is_negative_contribution"]) is True
    assert bool(row_a["is_negative_contribution"]) is False

    # 3. F11 Order Profitability
    f11_df = compute_f11(df_orders, df_line_items)
    # Net profit = Collected 800 - COGS 400 - Ship 80 - GW 24 - ExpRefund (500 + 25 = 525) = -229.0
    assert f11_df["order_net_profit"].iloc[0] == pytest.approx(-229.0)
    assert bool(f11_df["is_unprofitable_order"].iloc[0]) is True

    # 4. F12 Revenue Quality
    f12_res = compute_f12(df_orders, df_line_items)
    # Gross 800, leakage = 525(returns) + 80(ship deficit) + 24(gw) = 629.0
    # Net retained = 800 - 629 = 171.0 (21.375%)
    assert f12_res["gross_sales"] == pytest.approx(800.0)
    assert f12_res["total_leakage"] == pytest.approx(629.0)
    assert f12_res["net_retained_revenue"] == pytest.approx(171.0)
    assert f12_res["revenue_quality_score_pct"] == pytest.approx(21.375)


def test_return_edge_case_2_cheapest_item_returned():
    """TEST 2 — Return Item C ($100), the cheapest item in an $800 order."""
    df_orders, df_line_items = _create_multi_item_order(return_item_key="C")

    # 1. Verification of return flags
    assert bool(df_line_items.loc[df_line_items["product_id"] == "SKU-C", "is_returned"].iloc[0]) is True
    assert bool(df_line_items.loc[df_line_items["product_id"] == "SKU-A", "is_returned"].iloc[0]) is False
    assert bool(df_line_items.loc[df_line_items["product_id"] == "SKU-B", "is_returned"].iloc[0]) is False

    # 2. F10 Product Contribution
    sku_df = compute_f10(df_orders, df_line_items, return_shipping_flat=4.50)
    row_a = sku_df[sku_df["product_id"] == "SKU-A"].iloc[0]
    row_b = sku_df[sku_df["product_id"] == "SKU-B"].iloc[0]
    row_c = sku_df[sku_df["product_id"] == "SKU-C"].iloc[0]

    # Allocations
    assert row_a["allocated_outbound_shipping"] == pytest.approx(20.0)
    assert row_a["allocated_gateway_fees"] == pytest.approx(6.0)
    assert row_b["allocated_outbound_shipping"] == pytest.approx(50.0)
    assert row_b["allocated_gateway_fees"] == pytest.approx(15.0)
    assert row_c["allocated_outbound_shipping"] == pytest.approx(10.0)
    assert row_c["allocated_gateway_fees"] == pytest.approx(3.0)

    # Product contributions:
    # A: 200 - 100 - 20 - 6 = 74.0
    # B: 500 - 250 - 50 - 15 = 185.0
    # C: 100 - 50 - 100(refund) - 5(restock) - 4.50(ret_ship) - 10 - 3 = -72.50
    assert row_a["product_contribution"] == pytest.approx(74.0)
    assert row_b["product_contribution"] == pytest.approx(185.0)
    assert row_c["product_contribution"] == pytest.approx(-72.50)
    assert bool(row_c["is_negative_contribution"]) is True
    assert bool(row_b["is_negative_contribution"]) is False

    # 3. F11 Order Profitability
    f11_df = compute_f11(df_orders, df_line_items)
    # Net profit = Collected 800 - COGS 400 - Ship 80 - GW 24 - ExpRefund (100 + 5 = 105) = 191.0
    assert f11_df["order_net_profit"].iloc[0] == pytest.approx(191.0)
    assert bool(f11_df["is_profitable_order"].iloc[0]) is True

    # 4. F12 Revenue Quality
    f12_res = compute_f12(df_orders, df_line_items)
    # Gross 800, leakage = 105(returns) + 80(ship deficit) + 24(gw) = 209.0
    # Net retained = 800 - 209 = 591.0 (73.875%)
    assert f12_res["gross_sales"] == pytest.approx(800.0)
    assert f12_res["total_leakage"] == pytest.approx(209.0)
    assert f12_res["net_retained_revenue"] == pytest.approx(591.0)
    assert f12_res["revenue_quality_score_pct"] == pytest.approx(73.875)


def test_return_edge_case_3_all_items_returned():
    """TEST 3 — Return all items in the order."""
    df_orders, df_line_items = _create_multi_item_order(all_returned=True)

    # 1. Verify 100% of items marked as returned
    assert df_line_items["is_returned"].all() == True

    # 2. F10 Product Contribution
    sku_df = compute_f10(df_orders, df_line_items, return_shipping_flat=4.50)
    row_a = sku_df[sku_df["product_id"] == "SKU-A"].iloc[0]
    row_b = sku_df[sku_df["product_id"] == "SKU-B"].iloc[0]
    row_c = sku_df[sku_df["product_id"] == "SKU-C"].iloc[0]

    # Allocated costs sum exactly to order totals
    total_alloc_ship = sku_df["allocated_outbound_shipping"].sum()
    total_alloc_gw = sku_df["allocated_gateway_fees"].sum()
    assert total_alloc_ship == pytest.approx(80.0)
    assert total_alloc_gw == pytest.approx(24.0)

    # All SKUs produce negative contribution
    assert row_a["product_contribution"] == pytest.approx(200 - 100 - 200 - 10 - 4.50 - 20 - 6)  # -140.50
    assert row_b["product_contribution"] == pytest.approx(500 - 250 - 500 - 25 - 4.50 - 50 - 15) # -344.50
    assert row_c["product_contribution"] == pytest.approx(100 - 50 - 100 - 5 - 4.50 - 10 - 3)   # -72.50
    assert sku_df["is_negative_contribution"].all() == True

    # 3. F11 Order Profitability
    f11_df = compute_f11(df_orders, df_line_items)
    # Net profit = Collected 800 - COGS 400 - Ship 80 - GW 24 - ExpRefund (800 + 40 = 840) = -544.0
    assert f11_df["order_net_profit"].iloc[0] == pytest.approx(-544.0)
    assert bool(f11_df["is_unprofitable_order"].iloc[0]) is True

    # 4. F12 Revenue Quality
    f12_res = compute_f12(df_orders, df_line_items)
    # Gross 800, leakage = 840 + 80 + 24 = 944.0
    # Net retained = 800 - 944 = -144.0 (-18.0%)
    assert f12_res["gross_sales"] == pytest.approx(800.0)
    assert f12_res["total_leakage"] == pytest.approx(944.0)
    assert f12_res["net_retained_revenue"] == pytest.approx(-144.0)
    assert f12_res["revenue_quality_score_pct"] == pytest.approx(-18.0)

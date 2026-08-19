"""tests/test_v1_business_rules.py — Dedicated validation of Ajai's V1 business decisions."""

import numpy as np
import pandas as pd
import pytest

from src.data_clean import apply_cogs_policy, recompute_target_min_profit
from src.scoring.f01_f03 import compute_f01, compute_f03, aggregate_f01
from src.scoring.f02 import compute_f02
from src.scoring.f04 import compute_f04
from src.scoring.f05 import compute_f05
from src.scoring.f09 import compute_f09
from src.scoring.f10 import compute_f10
from src.scoring.f11 import compute_f11
from src.scoring.f12 import compute_f12
from src.config import TARGET_MARGINS


# ===========================================================================
# TEST 1 — F01 Net Selling Price
# ===========================================================================

def test_1_f01_target_profit_on_net_selling_price_core_example():
    """Selling $2000, Disc $500, Net $1500, Target 20% -> Target Profit = $300 (NOT $400)."""
    df = pd.DataFrame({
        "order_id": ["ORD-1"],
        "category": ["beauty"],  # beauty target = 20%
        "selling_price": [2000.0],
        "discount_given": [500.0],
        "net_selling_price": [1500.0],
        "is_discounted": [True],
        "cogs_total": [1000.0],
        "actual_shipping_cost": [50.0],
        "gateway_fee": [30.0],
    })
    res = compute_f01(df)
    assert res["target_min_profit"].iloc[0] == pytest.approx(300.0)
    assert res["target_min_profit"].iloc[0] != 400.0


def test_1_f01_net_selling_price_scenarios():
    """Test various discount depths on Net Selling Price target calculation."""
    # Scenario A: No discount ($100 selling, $100 net, 15% margin -> Target $15)
    df_no_disc = pd.DataFrame({
        "order_id": ["ORD-A"],
        "category": ["fashion"],
        "selling_price": [100.0],
        "discount_given": [0.0],
        "net_selling_price": [100.0],
        "is_discounted": [False],
        "cogs_total": [60.0],
        "actual_shipping_cost": [10.0],
        "gateway_fee": [5.0],
    })
    res_a = compute_f01(df_no_disc)
    assert res_a["target_min_profit"].iloc[0] == pytest.approx(15.0)

    # Scenario B: Small discount ($100 selling, $10 disc, $90 net, 15% margin -> Target $13.50)
    df_small = pd.DataFrame({
        "order_id": ["ORD-B"],
        "category": ["fashion"],
        "selling_price": [100.0],
        "discount_given": [10.0],
        "net_selling_price": [90.0],
        "is_discounted": [True],
        "cogs_total": [60.0],
        "actual_shipping_cost": [10.0],
        "gateway_fee": [5.0],
    })
    res_b = compute_f01(df_small)
    assert res_b["target_min_profit"].iloc[0] == pytest.approx(13.50)

    # Scenario C: Large discount ($100 selling, $60 disc, $40 net, 15% margin -> Target $6.00)
    df_large = pd.DataFrame({
        "order_id": ["ORD-C"],
        "category": ["fashion"],
        "selling_price": [100.0],
        "discount_given": [60.0],
        "net_selling_price": [40.0],
        "is_discounted": [True],
        "cogs_total": [20.0],
        "actual_shipping_cost": [5.0],
        "gateway_fee": [2.0],
    })
    res_c = compute_f01(df_large)
    assert res_c["target_min_profit"].iloc[0] == pytest.approx(6.0)

    # Scenario D: 100% discount ($100 selling, $100 disc, $0 net, 15% margin -> Target $0.00)
    df_100 = pd.DataFrame({
        "order_id": ["ORD-D"],
        "category": ["fashion"],
        "selling_price": [100.0],
        "discount_given": [100.0],
        "net_selling_price": [0.0],
        "is_discounted": [True],
        "cogs_total": [30.0],
        "actual_shipping_cost": [10.0],
        "gateway_fee": [0.0],
    })
    res_d = compute_f01(df_100)
    assert res_d["target_min_profit"].iloc[0] == pytest.approx(0.0)


# ===========================================================================
# TEST 2 — F01 Category Target Margins
# ===========================================================================

def test_2_f01_category_margins_and_boundaries():
    """Verify all 6 official categories from business spec and boundary conditions."""
    categories_expected = {
        "fashion": (0.15, 15.0),
        "beauty": (0.20, 20.0),
        "electronics": (0.08, 8.0),
        "home_goods": (0.12, 12.0),
        "luxury": (0.25, 25.0),
        "pet_care": (0.15, 15.0),
    }

    for cat, (margin, expected_target) in categories_expected.items():
        df = pd.DataFrame({
            "order_id": [f"ORD-{cat}"],
            "category": [cat],
            "selling_price": [120.0],
            "discount_given": [20.0],
            "net_selling_price": [100.0],
            "is_discounted": [True],
            "cogs_total": [50.0],
            "actual_shipping_cost": [5.0],
            "gateway_fee": [3.0],
        })
        res = compute_f01(df)
        assert res["target_min_profit"].iloc[0] == pytest.approx(expected_target)

    # Boundary tests for fashion (target = $15 on $100 net):
    # Case 1: Profit exactly equal to target ($15.00) -> Not flagged
    df_exact = pd.DataFrame({
        "order_id": ["ORD-EXACT"],
        "category": ["fashion"],
        "net_selling_price": [100.0],
        "is_discounted": [True],
        "cogs_total": [75.0],
        "actual_shipping_cost": [7.0],
        "gateway_fee": [3.0],  # Profit = 100 - 75 - 7 - 3 = 15.0
    })
    res_exact = compute_f01(df_exact)
    assert res_exact["f01_flagged"].iloc[0] == False

    # Case 2: Profit slightly below target ($14.99) -> Flagged
    df_below = pd.DataFrame({
        "order_id": ["ORD-BELOW"],
        "category": ["fashion"],
        "net_selling_price": [100.0],
        "is_discounted": [True],
        "cogs_total": [75.01],
        "actual_shipping_cost": [7.0],
        "gateway_fee": [3.0],  # Profit = 14.99
    })
    res_below = compute_f01(df_below)
    assert res_below["f01_flagged"].iloc[0] == True
    assert res_below["f01_loss"].iloc[0] == pytest.approx(0.01)

    # Case 3: Profit slightly above target ($15.01) -> Not flagged
    df_above = pd.DataFrame({
        "order_id": ["ORD-ABOVE"],
        "category": ["fashion"],
        "net_selling_price": [100.0],
        "is_discounted": [True],
        "cogs_total": [74.99],
        "actual_shipping_cost": [7.0],
        "gateway_fee": [3.0],  # Profit = 15.01
    })
    res_above = compute_f01(df_above)
    assert res_above["f01_flagged"].iloc[0] == False


# ===========================================================================
# TEST 3 & TEST 4 — Missing COGS Fallback & Estimated Flag
# ===========================================================================

def test_3_and_4_missing_cogs_fallback_cases():
    """Verify Cases A, B, C, D, E for COGS fallback and is_cogs_estimated flag."""
    # Case A: One item with actual COGS
    df_a = pd.DataFrame({
        "order_id": ["ORD-A"],
        "category": ["fashion"],
        "cogs_total": [40.0],
    })
    res_a = apply_cogs_policy(df_a, policy="impute_category_avg")
    assert res_a["cogs_total"].iloc[0] == 40.0
    assert res_a["is_cogs_estimated"].iloc[0] == False

    # Case B: One item with missing COGS (category avg = 40.0)
    df_b = pd.DataFrame({
        "order_id": ["ORD-REF", "ORD-B"],
        "category": ["fashion", "fashion"],
        "cogs_total": [40.0, np.nan],
    })
    res_b = apply_cogs_policy(df_b, policy="impute_category_avg")
    assert res_b.loc[res_b["order_id"] == "ORD-B", "cogs_total"].iloc[0] == pytest.approx(40.0)
    assert res_b.loc[res_b["order_id"] == "ORD-B", "is_cogs_estimated"].iloc[0] == True
    assert res_b.loc[res_b["order_id"] == "ORD-REF", "is_cogs_estimated"].iloc[0] == False

    # Case C: Three-item order (A actual, B missing, C actual)
    df_c = pd.DataFrame({
        "order_id": ["ORD-C", "ORD-C", "ORD-C"],
        "category": ["fashion", "fashion", "fashion"],
        "cogs_total": [30.0, np.nan, 50.0],
    })
    res_c = apply_cogs_policy(df_c, policy="impute_category_avg")
    # Category average of non-nulls (30 + 50)/2 = 40.0
    assert res_c["cogs_total"].iloc[0] == 30.0
    assert res_c["is_cogs_estimated"].iloc[0] == False
    assert res_c["cogs_total"].iloc[1] == pytest.approx(40.0)
    assert res_c["is_cogs_estimated"].iloc[1] == True
    assert res_c["cogs_total"].iloc[2] == 50.0
    assert res_c["is_cogs_estimated"].iloc[2] == False

    # Case D: All items missing COGS (falls back to global default or NaN if dataset empty)
    df_d = pd.DataFrame({
        "order_id": ["ORD-D1", "ORD-D2"],
        "category": ["fashion", "fashion"],
        "cogs_total": [np.nan, np.nan],
    })
    res_d = apply_cogs_policy(df_d, policy="impute_category_avg")
    assert res_d["is_cogs_estimated"].all() == True

    # Case E: Missing COGS + returned item
    df_e = pd.DataFrame({
        "order_id": ["ORD-REF", "ORD-E"],
        "category": ["fashion", "fashion"],
        "cogs_total": [50.0, np.nan],
        "is_returned": [False, True],
    })
    res_e = apply_cogs_policy(df_e, policy="impute_category_avg")
    assert res_e.loc[res_e["order_id"] == "ORD-E", "cogs_total"].iloc[0] == pytest.approx(50.0)
    assert res_e.loc[res_e["order_id"] == "ORD-E", "is_cogs_estimated"].iloc[0] == True


# ===========================================================================
# TEST 5 — F02 Boundary Testing
# ===========================================================================

@pytest.mark.parametrize("discounted_share,expected_status", [
    (0.00, "HEALTHY"),
    (0.1999, "HEALTHY"),
    (0.20, "HEALTHY"),
    (0.2001, "WARNING"),
    (0.2999, "WARNING"),
    (0.30, "WARNING"),
    (0.3001, "EXCESSIVE"),
    (1.00, "EXCESSIVE"),
])
def test_5_f02_boundary_buckets(discounted_share, expected_status):
    """Verify exact bucket classification for 0%, 20%, 30%, etc."""
    total_sales = 10000.0
    disc_sales = total_sales * discounted_share
    full_sales = total_sales - disc_sales

    order_ids = []
    selling_prices = []
    discounts = []
    is_disc_flags = []

    if disc_sales > 0:
        order_ids.append("ORD-DISC")
        selling_prices.append(disc_sales)
        discounts.append(disc_sales * 0.10)
        is_disc_flags.append(True)

    if full_sales > 0:
        order_ids.append("ORD-FULL")
        selling_prices.append(full_sales)
        discounts.append(0.0)
        is_disc_flags.append(False)

    df_orders = pd.DataFrame({"order_id": order_ids, "is_cancelled": [False] * len(order_ids)})
    df_items = pd.DataFrame({
        "order_id": order_ids,
        "selling_price": selling_prices,
        "discount_given": discounts,
        "is_discounted": is_disc_flags,
    })
    res = compute_f02(df_orders, df_items, healthy_share=0.20, warning_share=0.30)
    assert res["health_status"] == expected_status


# ===========================================================================
# TEST 6 — F02 Configurable Threshold
# ===========================================================================

def test_6_f02_configurable_threshold():
    """Verify that changing threshold dynamically alters breach and loss calculations."""
    df_orders = pd.DataFrame({"order_id": ["ORD-DISC", "ORD-FULL"], "is_cancelled": [False, False]})
    df_items = pd.DataFrame({
        "order_id": ["ORD-DISC", "ORD-FULL"],
        "selling_price": [250.0, 750.0],  # 25% discounted share
        "discount_given": [50.0, 0.0],    # 20% discount depth
        "is_discounted": [True, False],
    })
    # At 20% threshold: excess = 5%, breached = True, loss = 1000 * 0.05 * 0.20 = $10
    res_20 = compute_f02(df_orders, df_items, healthy_share=0.20)
    assert res_20["is_breached"] is True
    assert res_20["f02_loss"] == pytest.approx(10.0)

    # At 25% threshold: excess = 0%, breached = False, loss = $0
    res_25 = compute_f02(df_orders, df_items, healthy_share=0.25)
    assert res_25["is_breached"] is False
    assert res_25["f02_loss"] == 0.0

    # At 15% threshold: excess = 10%, breached = True, loss = 1000 * 0.10 * 0.20 = $20
    res_15 = compute_f02(df_orders, df_items, healthy_share=0.15)
    assert res_15["is_breached"] is True
    assert res_15["f02_loss"] == pytest.approx(20.0)


# ===========================================================================
# TEST 7 & TEST 8 — Partial Return Allocation by Item Revenue Percentage
# ===========================================================================

def test_7_and_8_partial_return_revenue_weighted_allocation():
    """Item A: ₹600 (60%), Item B: ₹400 (40%), Ship: ₹100, Gateway: ₹10.
    Item A allocated ship = ₹60, gateway = ₹6.
    Item B allocated ship = ₹40, gateway = ₹4.
    """
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1"],
        "actual_shipping_cost": [100.0],
        "gateway_fee": [10.0],
        "is_cancelled": [False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-1"],
        "product_id": ["SKU-A", "SKU-B"],
        "category": ["fashion", "fashion"],
        "quantity": [1, 1],
        "selling_price": [600.0, 400.0],
        "discount_given": [0.0, 0.0],
        "net_selling_price": [600.0, 400.0],
        "cogs_total": [200.0, 150.0],
        "is_returned": [True, False],  # Item A returned
        "refund_amount": [600.0, 0.0],
        "restocking_cost": [30.0, 0.0],
    })

    sku_df = compute_f10(df_orders, df_items, return_shipping_flat=4.50)
    row_a = sku_df[sku_df["product_id"] == "SKU-A"].iloc[0]
    row_b = sku_df[sku_df["product_id"] == "SKU-B"].iloc[0]

    # Verify exact 60% / 40% allocation
    assert row_a["allocated_outbound_shipping"] == pytest.approx(60.0)
    assert row_a["allocated_gateway_fees"] == pytest.approx(6.0)
    assert row_b["allocated_outbound_shipping"] == pytest.approx(40.0)
    assert row_b["allocated_gateway_fees"] == pytest.approx(4.0)

    # Item A return contribution:
    # Net 600 - COGS 200 - Refund 600 - Restock 30 - ReturnShip 4.50 - ShipAlloc 60 - GWAlloc 6 = -300.50
    assert row_a["product_contribution"] == pytest.approx(-300.50)

    # Item B contribution:
    # Net 400 - COGS 150 - ShipAlloc 40 - GWAlloc 4 = 206.00
    assert row_b["product_contribution"] == pytest.approx(206.00)


# ===========================================================================
# TEST 10 — V1 Shipment Assumption (1 order = 1 package)
# ===========================================================================

def test_10_v1_single_package_assumption():
    """Verify F04 and F05 operate strictly under 1 order = 1 package model."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "shipping_charged_to_customer": [0.0, 10.0],
        "actual_shipping_cost": [20.0, 8.0],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "selling_price": [50.0, 40.0],
        "net_selling_price": [50.0, 40.0],
        "cogs_total": [35.0, 20.0],
        "is_returned": [False, False],
    })
    f04_res = compute_f04(df_orders, df_items)
    # ORD-1: Uncovered $20 - Profit $15 = $5 leakage
    # ORD-2: Uncovered $0 - Profit $20 = $0 leakage
    assert f04_res.loc[f04_res["order_id"] == "ORD-1", "f04_leakage"].iloc[0] == pytest.approx(5.0)
    assert f04_res.loc[f04_res["order_id"] == "ORD-2", "f04_leakage"].iloc[0] == 0.0

    f05_res = compute_f05(df_orders)
    # ORD-1: 0 - 20 = -20 deficit; ORD-2: 10 - 8 = +2 surplus
    assert f05_res.loc[f05_res["order_id"] == "ORD-1", "shipping_delta"].iloc[0] == pytest.approx(-20.0)
    assert f05_res.loc[f05_res["order_id"] == "ORD-2", "shipping_delta"].iloc[0] == pytest.approx(2.0)

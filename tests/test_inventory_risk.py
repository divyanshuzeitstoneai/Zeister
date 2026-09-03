"""tests/test_inventory_risk.py — Comprehensive Test Suite for Inventory & Capital Risk (I03, I04, I05, I08).

Covers all 6 required case types per formula as specified in the testing matrix:
  1. Normal Case
  2. Boundary Case
  3. Missing Field with Approved Fallback
  4. Missing Field with NO Fallback (Unresolved / Trapped)
  5. Real-World Failure Mode
  6. Multi-Entity Case
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta

from src.scoring.inventory_risk import (
    compute_i03, aggregate_i03,
    compute_i04, aggregate_i04,
    compute_i05, aggregate_i05,
    compute_i08, aggregate_i08,
)


# =====================================================================
# I03: CAPITAL-AT-RISK TESTS
# =====================================================================

def test_i03_case1_normal_fresh_stock():
    """I03 Normal: Fresh stock with days_on_hand < 180 -> No capital at risk."""
    df = pd.DataFrame([{
        "sku": "SKU-FRESH-01",
        "current_inventory_qty": 50,
        "unit_wholesale_cost": 20.00,
        "days_on_hand": 45,
        "aging_threshold_days": 180,
    }])
    res = compute_i03(df)
    assert res.loc[0, "i03_status"] == "Normal"
    assert res.loc[0, "capital_at_risk"] == 0.0
    assert res.loc[0, "total_inventory_value"] == 1000.00


def test_i03_case2_boundary_exactly_180_days():
    """I03 Boundary: days_on_hand == 180 exactly (not > 180) -> Not at risk."""
    df = pd.DataFrame([{
        "sku": "SKU-BOUND-180",
        "current_inventory_qty": 100,
        "unit_wholesale_cost": 15.00,
        "days_on_hand": 180,
        "aging_threshold_days": 180,
    }])
    res = compute_i03(df)
    assert res.loc[0, "i03_status"] == "Normal"
    assert res.loc[0, "capital_at_risk"] == 0.0

    # 181 days -> at risk
    df_aged = pd.DataFrame([{
        "sku": "SKU-AGED-181",
        "current_inventory_qty": 100,
        "unit_wholesale_cost": 15.00,
        "days_on_hand": 181,
        "aging_threshold_days": 180,
    }])
    res_aged = compute_i03(df_aged)
    assert res_aged.loc[0, "i03_status"] == "AtRisk"
    assert res_aged.loc[0, "capital_at_risk"] == 1500.00


def test_i03_case3_missing_aging_threshold_fallback():
    """I03 Fallback: aging_threshold not configured -> defaults to 180 days with estimation flag."""
    df = pd.DataFrame([{
        "sku": "SKU-DEFAULT-THRESH",
        "current_inventory_qty": 30,
        "unit_wholesale_cost": 10.00,
        "days_on_hand": 200,
    }])
    res = compute_i03(df, aging_threshold_days=None)
    assert res.loc[0, "aging_threshold_days"] == 180
    assert bool(res.loc[0, "is_aging_threshold_estimated"]) is True
    assert res.loc[0, "i03_status"] == "AtRisk"
    assert res.loc[0, "capital_at_risk"] == 300.00


def test_i03_case4_missing_days_on_hand_unresolved():
    """I03 No Fallback: days_on_hand unresolvable (no receiving data) -> Unresolved (never 0 or 999)."""
    df = pd.DataFrame([{
        "sku": "SKU-NO-RECV-DATE",
        "current_inventory_qty": 100,
        "unit_wholesale_cost": 25.00,
        "days_on_hand": np.nan,
    }])
    res = compute_i03(df)
    assert res.loc[0, "i03_status"] == "Unresolved"
    assert pd.isna(res.loc[0, "capital_at_risk"])

    agg = aggregate_i03(res)
    assert agg["skus_unresolved"] == 1
    assert agg["skus_evaluated"] == 0
    assert agg["total_capital_at_risk"] == 0.0


def test_i03_case5_real_world_restock_miscounted_as_aged():
    """I03 Real-world failure mode: InventoryItem.createdAt shows SKU created 300 days ago,
    but batch was restocked 20 days ago. Without receiving-date tracking, SKU would be misclassified."""
    # Simulating data source where days_since_sku_created is used instead of real batch receiving date
    df = pd.DataFrame([
        {
            "sku": "SKU-RESTOCKED-RECENTLY",
            "current_inventory_qty": 200,
            "unit_wholesale_cost": 50.00,
            "days_on_hand": 20, # Real receiving date
            "aging_threshold_days": 180,
        },
        {
            "sku": "SKU-GENUINELY-STALE",
            "current_inventory_qty": 40,
            "unit_wholesale_cost": 50.00,
            "days_on_hand": 240,
            "aging_threshold_days": 180,
        }
    ])
    res = compute_i03(df)
    assert res.loc[0, "i03_status"] == "Normal"
    assert res.loc[0, "capital_at_risk"] == 0.0
    assert res.loc[1, "i03_status"] == "AtRisk"
    assert res.loc[1, "capital_at_risk"] == 2000.00


def test_i03_case6_multi_entity_different_ages_same_product():
    """I03 Multi-entity: Multiple variants/SKUs for the same parent product with differing ages."""
    df = pd.DataFrame([
        {"sku": "PROD-1-S", "current_inventory_qty": 50, "unit_wholesale_cost": 20.00, "days_on_hand": 90},
        {"sku": "PROD-1-M", "current_inventory_qty": 20, "unit_wholesale_cost": 20.00, "days_on_hand": 210},
        {"sku": "PROD-1-L", "current_inventory_qty": 10, "unit_wholesale_cost": 20.00, "days_on_hand": np.nan},
    ])
    res = compute_i03(df)
    agg = aggregate_i03(res)
    assert agg["skus_evaluated"] == 2
    assert agg["skus_unresolved"] == 1
    assert agg["skus_at_risk"] == 1
    assert agg["total_capital_at_risk"] == 400.00 # 20 * $20
    assert agg["total_inventory_value"] == 1600.00


# =====================================================================
# I04: STOCKOUT RISK TESTS
# =====================================================================

def test_i04_case1_normal_healthy_buffer():
    """I04 Normal: Current inventory exceeds lead time demand -> No blackout, 0 missed revenue."""
    # Inventory = 100, Velocity = 2 units/day -> Days of Supply = 50. Lead time = 14 days.
    df = pd.DataFrame([{
        "sku": "SKU-SAFE-01",
        "current_inventory_qty": 100,
        "daily_sales_velocity": 2.0,
        "supplier_lead_time_days": 14,
        "avg_unit_price": 50.00,
    }])
    res = compute_i04(df)
    assert res.loc[0, "days_of_supply"] == 50.0
    assert res.loc[0, "blackout_window_days"] == 0.0
    assert res.loc[0, "missed_revenue"] == 0.0
    assert res.loc[0, "i04_status"] == "Safe"


def test_i04_case2_boundary_days_of_supply_equals_lead_time():
    """I04 Boundary: Days of Supply exactly equals supplier lead time (blackout window = 0)."""
    # Inventory = 30, Velocity = 2/day -> Supply = 15 days. Lead time = 15 days.
    df = pd.DataFrame([{
        "sku": "SKU-BOUND-SUPPLY",
        "current_inventory_qty": 30,
        "daily_sales_velocity": 2.0,
        "supplier_lead_time_days": 15,
        "avg_unit_price": 40.00,
    }])
    res = compute_i04(df)
    assert res.loc[0, "days_of_supply"] == 15.0
    assert res.loc[0, "blackout_window_days"] == 0.0
    assert res.loc[0, "missed_revenue"] == 0.0
    assert res.loc[0, "i04_status"] == "Safe"


def test_i04_case3_blackout_and_missed_revenue_calculation():
    """I04 Calculation: Lead Time = 30d, Supply = 10d -> Blackout = 20d. Missed Revenue = 5 * 20 * $100 = $10,000."""
    df = pd.DataFrame([{
        "sku": "SKU-STOCKOUT-01",
        "current_inventory_qty": 50,
        "daily_sales_velocity": 5.0,
        "supplier_lead_time_days": 30,
        "avg_unit_price": 100.00,
    }])
    res = compute_i04(df)
    assert res.loc[0, "days_of_supply"] == 10.0
    assert res.loc[0, "blackout_window_days"] == 20.0
    assert res.loc[0, "missed_revenue"] == 10000.00
    assert res.loc[0, "i04_status"] == "AtRisk"


def test_i04_case4_missing_lead_time_unresolved():
    """I04 Fallback: If supplier_lead_time_days is missing -> Unresolved (no safe generic guess)."""
    df = pd.DataFrame([{
        "sku": "SKU-NO-LEADTIME",
        "current_inventory_qty": 20,
        "daily_sales_velocity": 2.0,
        "supplier_lead_time_days": np.nan,
        "avg_unit_price": 35.00,
    }])
    res = compute_i04(df)
    assert res.loc[0, "i04_status"] == "Unresolved"
    assert pd.isna(res.loc[0, "blackout_window_days"])
    assert pd.isna(res.loc[0, "missed_revenue"])

    agg = aggregate_i04(res)
    assert agg["skus_unresolved"] == 1
    assert agg["skus_evaluated"] == 0
    assert agg["total_missed_revenue"] == 0.0


def test_i04_case5_velocity_spike_sensitivity():
    """I04 Real-world failure mode: Velocity spike. 30-day trailing avg vs 7-day spike velocity."""
    # 30-day sales = 60 units (2/day). But last 7 days = 35 units (5/day spike!).
    df_sales_30d = pd.DataFrame([{"sku": "SKU-SPIKE", "quantity": 60}])
    df_sales_7d = pd.DataFrame([{"sku": "SKU-SPIKE", "quantity": 35}])

    df_base = pd.DataFrame([{
        "sku": "SKU-SPIKE",
        "current_inventory_qty": 40,
        "supplier_lead_time_days": 15,
        "avg_unit_price": 50.00,
    }])

    # Under 30-day window: velocity = 2.0/day -> Days of Supply = 20d > 15d lead time (FAILS to detect risk!)
    res_30 = compute_i04(df_base, df_sales=df_sales_30d, velocity_window_days=30)
    assert res_30.loc[0, "days_of_supply"] == 20.0
    assert res_30.loc[0, "i04_status"] == "Safe"

    # Under 7-day spike window: velocity = 5.0/day -> Days of Supply = 8d < 15d lead time (CORRECTLY flags risk!)
    res_7 = compute_i04(df_base, df_sales=df_sales_7d, velocity_window_days=7)
    assert res_7.loc[0, "days_of_supply"] == 8.0
    assert res_7.loc[0, "blackout_window_days"] == 7.0
    assert res_7.loc[0, "missed_revenue"] == 5.0 * 7.0 * 50.00 # $1,750
    assert res_7.loc[0, "i04_status"] == "AtRisk"


def test_i04_case6_multi_entity_multiple_vendors_lead_times():
    """I04 Multi-entity: Multiple SKUs with different lead times and price points."""
    df = pd.DataFrame([
        {"sku": "SKU-A", "current_inventory_qty": 10, "daily_sales_velocity": 1.0, "supplier_lead_time_days": 20, "avg_unit_price": 100.0},
        {"sku": "SKU-B", "current_inventory_qty": 50, "daily_sales_velocity": 1.0, "supplier_lead_time_days": 10, "avg_unit_price": 50.0},
        {"sku": "SKU-C", "current_inventory_qty": 5, "daily_sales_velocity": 0.0, "supplier_lead_time_days": 15, "avg_unit_price": 200.0},
    ])
    res = compute_i04(df)
    agg = aggregate_i04(res)
    assert agg["skus_evaluated"] == 3
    assert agg["skus_at_risk"] == 1 # Only SKU-A: supply 10d < lead time 20d
    assert agg["total_missed_revenue"] == 10.0 * 1.0 * 100.0 # 10d blackout * 1 vel * $100 = $1000


# =====================================================================
# I05: OVERSELL RISK TESTS
# =====================================================================

def test_i05_case1_normal_clean_order_no_oversell():
    """I05 Normal: Clean order fulfilled without cancellation -> 0 oversell loss."""
    df = pd.DataFrame([{
        "order_id": "ORD-CLEAN-01",
        "canceled_order_value": 150.00,
        "cancel_reason": None,
        "gateway_fee": 4.65,
    }])
    res = compute_i05(df)
    assert res.loc[0, "is_oversold_order"] == False
    assert res.loc[0, "oversell_loss"] == 0.0
    assert res.loc[0, "i05_status"] == "Normal"


def test_i05_case2_oversell_inventory_cancel_loss_calculation():
    """I05 Oversell Calculation: Canceled value ($200) + Gateway fee ($6.10) + Support cost ($15) = $221.10."""
    df = pd.DataFrame([{
        "order_id": "ORD-OVERSELL-01",
        "canceled_order_value": 200.00,
        "cancel_reason": "INVENTORY",
        "gateway_fee": 6.10,
        "support_cost": 15.00,
    }])
    res = compute_i05(df)
    assert res.loc[0, "is_oversold_order"] == True
    assert res.loc[0, "oversell_loss"] == 221.10
    assert res.loc[0, "i05_status"] == "OversoldLoss"


def test_i05_case3_missing_support_cost_fallback():
    """I05 Fallback: Missing support cost defaults to flat $15.00 with estimation flag."""
    df = pd.DataFrame([{
        "order_id": "ORD-OVERSELL-DEF-SUPPORT",
        "canceled_order_value": 100.00,
        "cancel_reason": "inventory",
        "gateway_fee": 3.20,
    }])
    res = compute_i05(df)
    assert res.loc[0, "support_cost_allocated"] == 15.00
    assert bool(res.loc[0, "is_support_cost_estimated"]) is True
    assert res.loc[0, "oversell_loss"] == 118.20 # 100 + 3.20 + 15


def test_i05_case4_non_inventory_cancel_excluded():
    """I05 Fallback Rule: Only cancel_reason == 'INVENTORY' is counted as oversell; customer request is excluded."""
    df = pd.DataFrame([
        {"order_id": "O-CUST", "canceled_order_value": 100.0, "cancel_reason": "CUSTOMER", "gateway_fee": 3.0},
        {"order_id": "O-FRAUD", "canceled_order_value": 200.0, "cancel_reason": "FRAUD", "gateway_fee": 6.0},
        {"order_id": "O-INV", "canceled_order_value": 150.0, "cancel_reason": "INVENTORY", "gateway_fee": 4.5},
    ])
    res = compute_i05(df)
    agg = aggregate_i05(res)
    assert agg["oversold_orders"] == 1
    assert agg["total_oversell_loss"] == 150.0 + 4.5 + 15.0 # $169.50


def test_i05_case5_real_world_late_fulfillment_undercount():
    """I05 Real-world failure mode: Orders accepted post-stockout that merchant fulfilled late
    instead of canceling have cancel_reason = None, causing false negatives in proxy detection."""
    df = pd.DataFrame([
        # Order cancelled due to stockout (caught)
        {"order_id": "O-CANC", "canceled_order_value": 100.0, "cancel_reason": "INVENTORY", "gateway_fee": 3.0},
        # Order accepted post-stockout, but merchant held customer for 3 weeks and fulfilled late (missed by cancelReason proxy)
        {"order_id": "O-LATE-FULFILL", "canceled_order_value": 100.0, "cancel_reason": None, "gateway_fee": 3.0},
    ])
    res = compute_i05(df)
    assert res.loc[0, "is_oversold_order"] == True
    assert res.loc[1, "is_oversold_order"] == False # Demonstrates the undercount fallacy


def test_i05_case6_multi_entity_multiple_oversold_orders_aggregation():
    """I05 Multi-entity: Aggregation across multiple oversold and non-oversold orders."""
    df = pd.DataFrame([
        {"order_id": "O1", "canceled_order_value": 100.0, "cancel_reason": "INVENTORY", "gateway_fee": 3.0},
        {"order_id": "O2", "canceled_order_value": 200.0, "cancel_reason": "INVENTORY", "gateway_fee": 6.0},
        {"order_id": "O3", "canceled_order_value": 50.0, "cancel_reason": None, "gateway_fee": 1.5},
    ])
    res = compute_i05(df)
    agg = aggregate_i05(res)
    assert agg["orders_evaluated"] == 3
    assert agg["oversold_orders"] == 2
    assert agg["oversell_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert agg["loss_breakdown"]["canceled_order_value"] == 300.0
    assert agg["loss_breakdown"]["gateway_fees"] == 9.0
    assert agg["loss_breakdown"]["support_costs"] == 30.0
    assert agg["total_oversell_loss"] == 339.0


# =====================================================================
# I08: RETURN-TO-INVENTORY RISK TESTS
# =====================================================================

def test_i08_case1_normal_prompt_restock_under_48h():
    """I08 Normal: Refund processed and restocked in warehouse within 24 hours -> Capital not trapped."""
    df = pd.DataFrame([{
        "refund_id": "REF-ONTIME-01",
        "retail_value": 120.00,
        "refund_processed_at": "2026-03-01 10:00:00",
        "restock_event_at": "2026-03-02 10:00:00", # 24 hrs delay <= 48 hrs
    }])
    res = compute_i08(df)
    assert res.loc[0, "restock_delay_hours"] == 24.0
    assert res.loc[0, "is_trapped_capital"] == False
    assert res.loc[0, "trapped_capital"] == 0.0
    assert res.loc[0, "i08_status"] == "OnTimeRestock"


def test_i08_case2_boundary_exactly_48_hours():
    """I08 Boundary: Delay exactly 48.0 hours (not > 48) -> Not trapped. 48.1 hours -> Trapped."""
    df = pd.DataFrame([
        {
            "refund_id": "REF-48H",
            "retail_value": 80.00,
            "refund_processed_at": "2026-03-01 10:00:00",
            "restock_event_at": "2026-03-03 10:00:00", # exactly 48.0 hrs
        },
        {
            "refund_id": "REF-49H",
            "retail_value": 80.00,
            "refund_processed_at": "2026-03-01 10:00:00",
            "restock_event_at": "2026-03-03 11:00:00", # 49.0 hrs > 48
        }
    ])
    res = compute_i08(df)
    assert res.loc[0, "is_trapped_capital"] == False
    assert res.loc[0, "trapped_capital"] == 0.0
    assert res.loc[1, "is_trapped_capital"] == True
    assert res.loc[1, "trapped_capital"] == 80.00


def test_i08_case3_never_restocked_treated_as_trapped():
    """I08 Fallback: If restock_event_at is null -> Stays Trapped (ongoing risk), NOT Unresolved."""
    df = pd.DataFrame([{
        "refund_id": "REF-NEVER-RESTOCKED",
        "retail_value": 250.00,
        "refund_processed_at": "2026-02-15 12:00:00",
        "restock_event_at": None, # Never scanned back into inventory
    }])
    res = compute_i08(df)
    assert res.loc[0, "is_trapped_capital"] == True
    assert res.loc[0, "trapped_capital"] == 250.00
    assert res.loc[0, "i08_status"] == "NeverRestocked"

    agg = aggregate_i08(res)
    assert agg["items_never_restocked"] == 1
    assert agg["total_trapped_capital"] == 250.00


def test_i08_case4_real_world_wrong_reason_code_discipline():
    """I08 Real-world failure mode: Warehouse staff logged restock under generic 'CORRECTION'
    rather than 'RESTOCK', obscuring restock timing."""
    # When warehouse tracking is missing or unlinked
    df = pd.DataFrame([{
        "refund_id": "REF-WRONG-CODE",
        "retail_value": 150.00,
        "refund_processed_at": "2026-03-01 10:00:00",
        "restock_event_at": None, # Missed match
    }])
    res = compute_i08(df)
    # The formula safely treats it as trapped capital
    assert res.loc[0, "trapped_capital"] == 150.00


def test_i08_case5_multi_entity_mixed_returns_portfolio():
    """I08 Multi-entity: Aggregation across on-time, delayed, and never-restocked returns."""
    df = pd.DataFrame([
        {"refund_id": "R1", "retail_value": 100.0, "refund_processed_at": "2026-03-01 10:00:00", "restock_event_at": "2026-03-02 10:00:00"}, # on-time (24h)
        {"refund_id": "R2", "retail_value": 200.0, "refund_processed_at": "2026-03-01 10:00:00", "restock_event_at": "2026-03-05 10:00:00"}, # delayed (96h)
        {"refund_id": "R3", "retail_value": 300.0, "refund_processed_at": "2026-03-01 10:00:00", "restock_event_at": None},                   # never
    ])
    res = compute_i08(df)
    agg = aggregate_i08(res)
    assert agg["refunds_evaluated"] == 3
    assert agg["items_on_time"] == 1
    assert agg["items_delayed"] == 1
    assert agg["items_never_restocked"] == 1
    assert agg["total_trapped_capital"] == 500.0 # 200 + 300
    assert agg["total_refunded_retail_value"] == 600.0
    assert agg["trapped_capital_pct"] == pytest.approx(83.33, abs=0.01)

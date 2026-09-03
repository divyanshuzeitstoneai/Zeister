"""tests/test_logistics_risk.py — Comprehensive Test Suite for Logistics & Fulfillment (L01, L07, L12).

Covers all 6 required case types per formula as specified in the testing matrix:
  1. Normal Case
  2. Boundary Case
  3. Missing Field with Approved Fallback
  4. Missing Field with NO Fallback (Unclassified / Support Cost Unavailable)
  5. Real-World Failure Mode
  6. Multi-Entity Case
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta

from src.scoring.logistics_risk import (
    compute_l01, aggregate_l01,
    compute_l07, aggregate_l07,
    compute_l12, aggregate_l12,
)


# =====================================================================
# L01: SHIPPING COST RECOVERY TESTS
# =====================================================================

def test_l01_case1_normal_full_recovery():
    """L01 Normal: Shipping charged roughly equals carrier cost ($10.00 charged vs $10.00 actual) -> Full recovery."""
    df = pd.DataFrame([{
        "order_id": "ORD-L01-NORM",
        "shipping_charged": 10.00,
        "actual_shipping_cost": 10.00,
    }])
    res = compute_l01(df)
    assert res.loc[0, "l01_status"] == "FullRecovery"
    assert res.loc[0, "under_recovery_loss"] == 0.00
    assert res.loc[0, "shipping_recovery_pct"] == pytest.approx(100.0)


def test_l01_case2_boundary_recovery_exactly_100_percent():
    """L01 Boundary: Recovery exactly 100.0% ($15.00 charged vs $15.00 actual)."""
    df = pd.DataFrame([{
        "order_id": "ORD-L01-BOUND",
        "shipping_charged": 15.00,
        "actual_shipping_cost": 15.00,
    }])
    res = compute_l01(df)
    assert res.loc[0, "under_recovery_loss"] == 0.00
    assert res.loc[0, "shipping_recovery_pct"] == pytest.approx(100.0)
    assert res.loc[0, "l01_status"] == "FullRecovery"

    # 1 penny under-recovery
    df_under = pd.DataFrame([{
        "order_id": "ORD-L01-UNDER",
        "shipping_charged": 14.99,
        "actual_shipping_cost": 15.00,
    }])
    res_under = compute_l01(df_under)
    assert res_under.loc[0, "l01_status"] == "UnderRecovered"
    assert res_under.loc[0, "under_recovery_loss"] == pytest.approx(0.01)


def test_l01_case3_missing_cost_period_average_fallback():
    """L01 Fallback: Per-order actual_shipping_cost missing -> Fallback to period average ($6.50),
    flagged is_shipping_cost_averaged = True. NEVER silently $0.00."""
    df = pd.DataFrame([{
        "order_id": "ORD-L01-AVG-COST",
        "shipping_charged": 5.00,
        "actual_shipping_cost": np.nan,  # Carrier invoice lacks itemized order cost
    }])
    res = compute_l01(df, period_avg_shipping_cost=6.50)
    assert res.loc[0, "actual_shipping_expense"] == 6.50
    assert bool(res.loc[0, "is_shipping_cost_averaged"]) is True
    assert res.loc[0, "under_recovery_loss"] == pytest.approx(1.50)  # 6.50 - 5.00
    assert res.loc[0, "shipping_recovery_pct"] == pytest.approx(5.00 / 6.50 * 100.0)
    assert res.loc[0, "l01_status"] == "UnderRecovered"


def test_l01_case4_silent_zero_prevention():
    """L01 Fallback Rule: Missing actual_shipping_cost must NEVER default to $0 (which would show 100%+ recovery)."""
    df = pd.DataFrame([{
        "order_id": "ORD-L01-FREE-SHIP",
        "shipping_charged": 0.00,
        "actual_shipping_cost": np.nan,
    }])
    res = compute_l01(df, period_avg_shipping_cost=7.00)
    # If it defaulted to 0, recovery would be 100% and loss $0.
    # With period-average fallback, it correctly reflects $7.00 loss!
    assert res.loc[0, "actual_shipping_expense"] == 7.00
    assert res.loc[0, "under_recovery_loss"] == 7.00
    assert res.loc[0, "shipping_recovery_pct"] == 0.0


def test_l01_case5_real_world_aggregate_carrier_invoice():
    """L01 Real-world failure mode: Courier bills in monthly aggregate lump-sum ($10,000 for 1,250 orders = $8.00/order).
    Cannot do individual order attribution, but period average allows store-level recovery scoring."""
    df = pd.DataFrame([
        {"order_id": f"ORD-{i}", "shipping_charged": 5.00, "actual_shipping_cost": np.nan}
        for i in range(10)
    ])
    # Period bill = $80 for 10 orders -> $8.00/order average
    res = compute_l01(df, period_avg_shipping_cost=8.00)
    agg = aggregate_l01(res)
    assert agg["orders_evaluated"] == 10
    assert agg["orders_with_averaged_cost"] == 10
    assert agg["total_shipping_expenses"] == 80.00
    assert agg["total_shipping_revenue"] == 50.00
    assert agg["net_under_recovery_loss"] == 30.00
    assert agg["overall_recovery_pct"] == pytest.approx(62.50)


def test_l01_case6_multi_entity_split_fulfillment_order():
    """L01 Multi-entity: Multi-shipment order with split fulfillment (e.g. 2 packages for 1 order)."""
    # Order charged $10.00 total shipping. Two packages shipped: $6.00 + $7.00 = $13.00 actual cost.
    df = pd.DataFrame([
        {"order_id": "ORD-SPLIT-1", "shipping_charged": 10.00, "actual_shipping_cost": 13.00},
        {"order_id": "ORD-SPLIT-2", "shipping_charged": 15.00, "actual_shipping_cost": 12.00},
    ])
    res = compute_l01(df)
    agg = aggregate_l01(res)
    assert agg["orders_under_recovered"] == 1
    assert agg["orders_surplus"] == 1
    assert agg["total_shipping_expenses"] == 25.00
    assert agg["total_shipping_revenue"] == 25.00
    assert agg["net_under_recovery_loss"] == 0.00


# =====================================================================
# L07: ZONE PROFITABILITY TESTS
# =====================================================================

def test_l07_case1_normal_metro_zone_surcharge_covered():
    """L07 Normal: Metro zone order with $3.00 surcharge collected vs $3.00 carrier surcharge paid -> 0 loss."""
    zone_map = {"10001": "Metro-Zone1"}
    df = pd.DataFrame([{
        "order_id": "ORD-L07-NORM",
        "customer_postal_code": "10001",
        "carrier_surcharge_amount": 3.00,
        "location_surcharge_collected": 3.00,
    }])
    res = compute_l07(df, zone_mapping=zone_map)
    assert res.loc[0, "zone_classification"] == "Metro-Zone1"
    assert bool(res.loc[0, "is_zone_unclassified"]) is False
    assert res.loc[0, "zone_loss"] == 0.00
    assert res.loc[0, "zone_leakage"] == 0.00
    assert res.loc[0, "l07_status"] == "ZoneProfitable"


def test_l07_case2_boundary_surcharge_exactly_equals_collected():
    """L07 Boundary: Regional surcharge exactly equals collected fee ($5.50 == $5.50)."""
    zone_map = {"90210": "Zone-2"}
    df = pd.DataFrame([{
        "order_id": "ORD-L07-BOUND",
        "customer_postal_code": "90210",
        "carrier_surcharge_amount": 5.50,
        "location_surcharge_collected": 5.50,
    }])
    res = compute_l07(df, zone_mapping=zone_map)
    assert res.loc[0, "zone_loss"] == 0.00
    assert res.loc[0, "zone_leakage"] == 0.00
    assert res.loc[0, "l07_status"] == "ZoneProfitable"


def test_l07_case3_remote_area_zone_loss_calculation():
    """L07 Remote Surcharge Loss: Carrier billed $14.00 remote surcharge, merchant collected $4.00 -> $10.00 loss."""
    zone_map = {"99501": "Remote-Alaska"}
    df = pd.DataFrame([{
        "order_id": "ORD-L07-REMOTE",
        "customer_postal_code": "99501",
        "carrier_surcharge_amount": 14.00,
        "location_surcharge_collected": 4.00,
    }])
    res = compute_l07(df, zone_mapping=zone_map)
    assert res.loc[0, "zone_classification"] == "Remote-Alaska"
    assert res.loc[0, "zone_loss"] == 10.00
    assert res.loc[0, "zone_leakage"] == 10.00
    assert res.loc[0, "l07_status"] == "ZoneLoss"


def test_l07_case4_unmapped_postal_code_unclassified_excluded_from_rollup():
    """L07 No Fallback: Postal code not in mapping table -> Tag 'Unclassified', exclude from zone rollups."""
    zone_map = {"10001": "Metro"}
    df = pd.DataFrame([{
        "order_id": "ORD-L07-UNMAPPED",
        "customer_postal_code": "88888",  # Not in zone map
        "carrier_surcharge_amount": 8.00,
        "location_surcharge_collected": 0.00,
    }])
    res = compute_l07(df, zone_mapping=zone_map)
    assert res.loc[0, "zone_classification"] == "Unclassified"
    assert bool(res.loc[0, "is_zone_unclassified"]) is True
    assert res.loc[0, "l07_status"] == "UnclassifiedReview"

    agg = aggregate_l07(res)
    assert agg["orders_unclassified"] == 1
    assert agg["orders_classified"] == 0
    assert agg["total_zone_loss"] == 0.00  # Excluded from confirmed zone loss rollup
    assert agg["unclassified_zone_loss"] == 8.00


def test_l07_case5_real_world_stale_zone_mapping():
    """L07 Real-world failure mode: Courier reclassifies region as extended area mid-year,
    causing unexpected surcharges on previously standard zip codes."""
    # Stale mapping classifies 33040 as Standard ($0 collected), but carrier invoiced $6.50 surcharge
    zone_map = {"33040": "Standard"}
    df = pd.DataFrame([{
        "order_id": "ORD-L07-STALE",
        "customer_postal_code": "33040",
        "carrier_surcharge_amount": 6.50,
        "location_surcharge_collected": 0.00,
    }])
    res = compute_l07(df, zone_mapping=zone_map)
    assert res.loc[0, "zone_classification"] == "Standard"
    assert res.loc[0, "zone_loss"] == 6.50
    assert res.loc[0, "l07_status"] == "ZoneLoss"


def test_l07_case6_multi_entity_multiple_zones_portfolio_aggregation():
    """L07 Multi-entity: Aggregation across Metro, Remote, Extended Area, and Unclassified zones."""
    zone_map = {"10001": "Metro", "99501": "Remote", "59001": "Extended"}
    df = pd.DataFrame([
        {"order_id": "O1", "customer_postal_code": "10001", "carrier_surcharge_amount": 2.0, "location_surcharge_collected": 2.0},
        {"order_id": "O2", "customer_postal_code": "99501", "carrier_surcharge_amount": 15.0, "location_surcharge_collected": 5.0},
        {"order_id": "O3", "customer_postal_code": "59001", "carrier_surcharge_amount": 7.0, "location_surcharge_collected": 3.0},
        {"order_id": "O4", "customer_postal_code": "00000", "carrier_surcharge_amount": 5.0, "location_surcharge_collected": 0.0},
    ])
    res = compute_l07(df, zone_mapping=zone_map)
    agg = aggregate_l07(res)
    assert agg["orders_evaluated"] == 4
    assert agg["orders_classified"] == 3
    assert agg["orders_unclassified"] == 1
    assert agg["total_zone_loss"] == (15.0 - 5.0) + (7.0 - 3.0)  # $10 + $4 = $14.00
    assert "Remote" in agg["zone_breakdown"]
    assert agg["zone_breakdown"]["Remote"]["zone_loss"] == 10.00


# =====================================================================
# L12: FULFILLMENT SLA RISK TESTS
# =====================================================================

def test_l12_case1_normal_fulfilled_within_sla():
    """L12 Normal: Order fulfilled within 24h (SLA = 48h) with 0 support tickets -> No breach."""
    df = pd.DataFrame([{
        "order_id": "ORD-L12-NORM",
        "order_created_at": "2026-03-01 10:00:00",
        "fulfillment_created_at": "2026-03-02 10:00:00",  # 24 hours
        "sla_threshold_hours": 48.0,
        "wismo_ticket_count": 0,
    }])
    res = compute_l12(df)
    assert res.loc[0, "fulfillment_delay_hours"] == 24.0
    assert bool(res.loc[0, "is_sla_breached"]) is False
    assert res.loc[0, "sla_delayed_order_loss"] == 0.00
    assert res.loc[0, "l12_status"] == "WithinSLA"


def test_l12_case2_boundary_exactly_at_sla_threshold():
    """L12 Boundary: Delay exactly 48.0 hours (not > 48.0) -> Within SLA. 48.1h -> Breached."""
    df = pd.DataFrame([
        {
            "order_id": "ORD-L12-BOUND-48H",
            "order_created_at": "2026-03-01 10:00:00",
            "fulfillment_created_at": "2026-03-03 10:00:00",  # exactly 48.0h
            "sla_threshold_hours": 48.0,
            "wismo_ticket_count": 0,
        },
        {
            "order_id": "ORD-L12-BOUND-49H",
            "order_created_at": "2026-03-01 10:00:00",
            "fulfillment_created_at": "2026-03-03 11:00:00",  # 49.0h
            "sla_threshold_hours": 48.0,
            "wismo_ticket_count": 1,
        }
    ])
    res = compute_l12(df, wismo_ticket_cost=12.00)
    assert bool(res.loc[0, "is_sla_breached"]) is False
    assert res.loc[0, "l12_status"] == "WithinSLA"

    assert bool(res.loc[1, "is_sla_breached"]) is True
    assert res.loc[1, "l12_status"] == "BreachedLoss"
    assert res.loc[1, "sla_delayed_order_loss"] == 12.00


def test_l12_case3_missing_sla_threshold_default_fallback():
    """L12 Fallback: sla_threshold_hours unset in metafields -> Defaults to 48.0h with estimation flag."""
    df = pd.DataFrame([{
        "order_id": "ORD-L12-DEF-SLA",
        "order_created_at": "2026-03-01 10:00:00",
        "fulfillment_created_at": "2026-03-03 12:00:00",  # 50.0h
        "wismo_ticket_count": 1,
    }])
    res = compute_l12(df, sla_threshold_hours=None, wismo_ticket_cost=12.00)
    assert res.loc[0, "sla_threshold_hours"] == 48.0
    assert bool(res.loc[0, "is_sla_threshold_estimated"]) is True
    assert bool(res.loc[0, "is_sla_breached"]) is True
    assert res.loc[0, "sla_delayed_order_loss"] == 12.00


def test_l12_case4_ticket_data_unavailable_sla_only_score():
    """L12 No Fallback: Support ticket linkage unavailable -> SLA-only score,
    support_cost_unavailable = True (NEVER assume 0 tickets)."""
    df = pd.DataFrame([{
        "order_id": "ORD-L12-NO-TICKETS",
        "order_created_at": "2026-03-01 10:00:00",
        "fulfillment_created_at": "2026-03-04 10:00:00",  # 72.0h
        "sla_threshold_hours": 48.0,
        "wismo_ticket_count": np.nan,  # Support tool unlinked
    }])
    res = compute_l12(df)
    assert bool(res.loc[0, "is_sla_breached"]) is True
    assert bool(res.loc[0, "support_cost_unavailable"]) is True
    assert res.loc[0, "l12_status"] == "BreachedSupportUnavail"

    agg = aggregate_l12(res)
    assert agg["fulfillments_breached"] == 1
    assert agg["orders_support_cost_unavailable"] == 1


def test_l12_case5_real_world_wasted_labor_fulfillment_after_cancellation():
    """L12 Real-world failure mode: Order was cancelled, but 3PL packed and fulfilled it anyway.
    Wasted labor cost applies."""
    df = pd.DataFrame([{
        "order_id": "ORD-L12-WASTED-LABOR",
        "order_created_at": "2026-03-01 10:00:00",
        "cancelled_at": "2026-03-01 14:00:00",        # Cancelled at 2pm
        "fulfillment_created_at": "2026-03-01 16:00:00",  # Packed at 4pm post-cancel!
        "sla_threshold_hours": 48.0,
        "wismo_ticket_count": 0,
    }])
    res = compute_l12(df, wasted_labor_cost=8.50)
    assert bool(res.loc[0, "is_wasted_labor"]) is True
    assert res.loc[0, "wasted_labor_loss"] == 8.50
    assert res.loc[0, "sla_delayed_order_loss"] == 8.50


def test_l12_case6_multi_entity_multiple_fulfillments_mixed_sla():
    """L12 Multi-entity: Multiple fulfillments per order with mixed SLA statuses."""
    df = pd.DataFrame([
        # Package 1: On-time (24h)
        {"order_id": "ORD-MULTI", "order_created_at": "2026-03-01 10:00:00", "fulfillment_created_at": "2026-03-02 10:00:00", "wismo_ticket_count": 0},
        # Package 2: Breached (72h) with 2 WISMO tickets ($24)
        {"order_id": "ORD-MULTI", "order_created_at": "2026-03-01 10:00:00", "fulfillment_created_at": "2026-03-04 10:00:00", "wismo_ticket_count": 2},
    ])
    res = compute_l12(df, sla_threshold_hours=48.0, wismo_ticket_cost=12.00)
    agg = aggregate_l12(res)
    assert agg["fulfillments_evaluated"] == 2
    assert agg["fulfillments_within_sla"] == 1
    assert agg["fulfillments_breached"] == 1
    assert agg["breach_rate_pct"] == 50.0
    assert agg["total_sla_delay_loss"] == 24.00

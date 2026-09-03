"""Comprehensive Synthetic test suite for C11 High-Value Customer Loss formula validation.

Covers all requested parameters:
- VIP Population reuse from C03
- Established VIP criteria: Orders >= 3 AND HistorySpan >= 90 days
- Dynamic Inactivity Threshold: MAX(90 days, 1.5 * Rhythm)
- Strict Lost VIP boundary: DaysSinceLastOrder > Threshold (<, ==, >)
- Individual Quarterly Spend: LifetimeSpend / (LifetimeDays / 90)
- Zero lifetime days division-by-zero avoidance
- Total VIP loss exposure aggregation across multiple lost VIPs
"""

from datetime import date, timedelta
import pytest
from src.scoring.c03 import (
    SyntheticOrder,
    evaluate_c03_population,
)
from src.scoring.c11 import (
    EstablishedVIPEvaluation,
    C11Result,
    evaluate_c11_high_value_loss,
)

EVAL_DATE = date(2026, 8, 1)


# -------------------------------------------------------------
# 1. ESTABLISHED VIP CRITERIA (Orders >= 3 AND History >= 90d)
# -------------------------------------------------------------

def test_c11_established_vip_criteria():
    """VIP must have >= 3 completed orders AND history spanning >= 90 days."""
    orders = [
        # Customer 1: 1 order -> Not Established
        SyntheticOrder("O1A", "VIP-1ORD", date(2026, 1, 1), "COMPLETED", 5000.0),

        # Customer 2: 2 orders over 100 days -> Not Established (Orders < 3)
        SyntheticOrder("O2A", "VIP-2ORD", date(2026, 1, 1), "COMPLETED", 2000.0),
        SyntheticOrder("O2B", "VIP-2ORD", date(2026, 4, 11), "COMPLETED", 2000.0), # 100 days

        # Customer 3: 3 orders over 60 days -> Not Established (Span < 90d)
        SyntheticOrder("O3A", "VIP-3ORD-60D", date(2026, 1, 1), "COMPLETED", 1000.0),
        SyntheticOrder("O3B", "VIP-3ORD-60D", date(2026, 2, 1), "COMPLETED", 1000.0),
        SyntheticOrder("O3C", "VIP-3ORD-60D", date(2026, 3, 2), "COMPLETED", 1000.0), # span = 60 days

        # Customer 4: 3 orders over exactly 90 days -> ESTABLISHED
        SyntheticOrder("O4A", "VIP-3ORD-90D", date(2026, 1, 1), "COMPLETED", 1000.0),
        SyntheticOrder("O4B", "VIP-3ORD-90D", date(2026, 2, 15), "COMPLETED", 1000.0),
        SyntheticOrder("O4C", "VIP-3ORD-90D", date(2026, 4, 1), "COMPLETED", 1000.0), # span = 90 days

        # Customer 5: 4 orders over 150 days -> ESTABLISHED
        SyntheticOrder("O5A", "VIP-4ORD-150D", date(2026, 1, 1), "COMPLETED", 1000.0),
        SyntheticOrder("O5B", "VIP-4ORD-150D", date(2026, 2, 20), "COMPLETED", 1000.0),
        SyntheticOrder("O5C", "VIP-4ORD-150D", date(2026, 4, 11), "COMPLETED", 1000.0),
        SyntheticOrder("O5D", "VIP-4ORD-150D", date(2026, 5, 31), "COMPLETED", 1000.0), # span = 150 days
    ]
    c03_res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    c11_res = evaluate_c11_high_value_loss(c03_res, EVAL_DATE)

    assert c11_res.vip_evaluations["VIP-1ORD"].is_established_vip is False
    assert c11_res.vip_evaluations["VIP-2ORD"].is_established_vip is False
    assert c11_res.vip_evaluations["VIP-3ORD-60D"].is_established_vip is False

    assert c11_res.vip_evaluations["VIP-3ORD-90D"].is_established_vip is True
    assert c11_res.vip_evaluations["VIP-4ORD-150D"].is_established_vip is True
    assert c11_res.established_vip_count == 2


# -------------------------------------------------------------
# 2. DYNAMIC INACTIVITY THRESHOLD (MAX(90, 1.5 * Rhythm))
# -------------------------------------------------------------

def test_c11_dynamic_inactivity_thresholds():
    """R = 30d -> MAX(90, 45) = 90d.
    R = 60d -> MAX(90, 90) = 90d.
    R = 100d -> MAX(90, 150) = 150d.
    """
    orders = [
        # Customer 1: 4 orders over 90 days -> Rhythm = 90/3 = 30.0d -> InactivityThreshold = 90.0d
        SyntheticOrder("O1A", "VIP-R30", date(2026, 1, 1), "COMPLETED", 500.0),
        SyntheticOrder("O1B", "VIP-R30", date(2026, 1, 31), "COMPLETED", 500.0),
        SyntheticOrder("O1C", "VIP-R30", date(2026, 3, 2), "COMPLETED", 500.0),
        SyntheticOrder("O1D", "VIP-R30", date(2026, 4, 1), "COMPLETED", 500.0), # last order 2026-04-01 (122d ago > 90d -> LOST)

        # Customer 2: 4 orders over 180 days -> Rhythm = 180/3 = 60.0d -> InactivityThreshold = 90.0d
        SyntheticOrder("O2A", "VIP-R60", date(2025, 10, 3), "COMPLETED", 500.0),
        SyntheticOrder("O2B", "VIP-R60", date(2025, 12, 2), "COMPLETED", 500.0),
        SyntheticOrder("O2C", "VIP-R60", date(2026, 1, 31), "COMPLETED", 500.0),
        SyntheticOrder("O2D", "VIP-R60", date(2026, 4, 1), "COMPLETED", 500.0), # last order 2026-04-01 (122d ago > 90d -> LOST)

        # Customer 3: 4 orders over 300 days -> Rhythm = 300/3 = 100.0d -> InactivityThreshold = 1.5 * 100 = 150.0d
        SyntheticOrder("O3A", "VIP-R100", date(2025, 6, 5), "COMPLETED", 500.0),
        SyntheticOrder("O3B", "VIP-R100", date(2025, 9, 13), "COMPLETED", 500.0),
        SyntheticOrder("O3C", "VIP-R100", date(2025, 12, 22), "COMPLETED", 500.0),
        SyntheticOrder("O3D", "VIP-R100", date(2026, 4, 1), "COMPLETED", 500.0), # last order 2026-04-01 (122d ago <= 150d -> NOT LOST)
    ]
    c03_res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    c11_res = evaluate_c11_high_value_loss(c03_res, EVAL_DATE)

    ev_r30 = c11_res.vip_evaluations["VIP-R30"]
    ev_r60 = c11_res.vip_evaluations["VIP-R60"]
    ev_r100 = c11_res.vip_evaluations["VIP-R100"]

    assert ev_r30.avg_days_between_orders == 30.0
    assert ev_r30.inactivity_threshold_days == 90.0
    assert ev_r30.is_lost_vip is True

    assert ev_r60.avg_days_between_orders == 60.0
    assert ev_r60.inactivity_threshold_days == 90.0
    assert ev_r60.is_lost_vip is True

    assert ev_r100.avg_days_between_orders == 100.0
    assert ev_r100.inactivity_threshold_days == 150.0
    assert ev_r100.is_lost_vip is False  # 122 <= 150.0 -> Safe!


# -------------------------------------------------------------
# 3. QUARTERLY SPEND & TOTAL RAW EXPOSURE AGGREGATION
# -------------------------------------------------------------

def test_c11_quarterly_spend_and_raw_exposure():
    """IndividualQuarterlySpend = Spend / (LifetimeDays / 90).
    Exposure = SUM(QuarterlySpend for lost VIPs).
    """
    orders = [
        # Lost VIP: Spend = $2000. First order = 2025-08-05, Last order = 2026-04-01 (122d ago > 90d).
        # Total lifetime days = (2026-08-01 - 2025-08-05) = 361 days.
        # Quarterly spend = 2000 / (361 / 90) = 2000 / 4.0111 = $498.61
        SyntheticOrder("O1A", "LOST-VIP", date(2025, 8, 5), "COMPLETED", 500.0),
        SyntheticOrder("O1B", "LOST-VIP", date(2025, 11, 3), "COMPLETED", 500.0),
        SyntheticOrder("O1C", "LOST-VIP", date(2026, 1, 2), "COMPLETED", 500.0),
        SyntheticOrder("O1D", "LOST-VIP", date(2026, 4, 1), "COMPLETED", 500.0),

        # Active VIP: Spend = $3000. Last order = 2026-07-15 (17d ago <= 90d) -> NOT LOST
        SyntheticOrder("O2A", "ACTIVE-VIP", date(2025, 8, 5), "COMPLETED", 750.0),
        SyntheticOrder("O2B", "ACTIVE-VIP", date(2025, 11, 3), "COMPLETED", 750.0),
        SyntheticOrder("O2C", "ACTIVE-VIP", date(2026, 1, 2), "COMPLETED", 750.0),
        SyntheticOrder("O2D", "ACTIVE-VIP", date(2026, 7, 15), "COMPLETED", 750.0),
    ]
    c03_res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    c11_res = evaluate_c11_high_value_loss(c03_res, EVAL_DATE)

    assert c11_res.established_vip_count == 2
    assert c11_res.lost_vip_count == 1

    ev_lost = c11_res.vip_evaluations["LOST-VIP"]
    ev_act = c11_res.vip_evaluations["ACTIVE-VIP"]

    expected_q_spend = 2000.0 / (361.0 / 90.0)
    assert pytest.approx(ev_lost.individual_quarterly_spend, 0.01) == expected_q_spend
    assert pytest.approx(ev_lost.c11_exposure_dollars, 0.01) == expected_q_spend
    assert ev_act.c11_exposure_dollars == 0.0

    assert pytest.approx(c11_res.raw_vip_loss_dollars, 0.01) == expected_q_spend

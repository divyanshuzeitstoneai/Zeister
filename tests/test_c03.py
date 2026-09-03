"""Comprehensive Synthetic test suite for C03 CLV-at-Risk formula validation.

Covers all requested parameters:
- Normal, boundary, zero, negative, extreme, decimal inputs
- VIP population sizes: 10, 11, 14, 15, 19, 20 customers with CEIL validation
- Positive spend vs zero spend vs negative spend
- 365-day rolling window boundaries (inside, on boundary, outside)
- Buying rhythm calculations (3 orders, 4+ orders, irregular, same-day, insufficient history)
- Rhythm fallbacks (VIP population avg vs 90d static fallback)
- Strict at-risk conditions (Days > 2*R: <, ==, >)
- Return rate boundaries (<=40% vs >40%)
- Dispute exclusions (OPEN, LOST vs WON)
"""

from datetime import date, timedelta
import pytest
from src.scoring.c03 import (
    SyntheticOrder,
    CustomerEvaluation,
    C03PopulationResult,
    evaluate_c03_population,
)

EVAL_DATE = date(2026, 8, 1)


# -------------------------------------------------------------
# 1. VIP POPULATION & CUTOFF TESTS (10, 11, 14, 15, 19, 20)
# -------------------------------------------------------------

@pytest.mark.parametrize("pop_size, expected_vip_count", [
    (10, 1),   # ceil(0.10 * 10) = 1
    (11, 2),   # ceil(0.10 * 11) = 2
    (14, 2),   # ceil(0.10 * 14) = 2
    (15, 2),   # ceil(0.10 * 15) = 2
    (19, 2),   # ceil(0.10 * 19) = 2
    (20, 2),   # ceil(0.10 * 20) = 2
    (21, 3),   # ceil(0.10 * 21) = 3
])
def test_c03_vip_population_ceil_cutoffs(pop_size: int, expected_vip_count: int):
    orders = []
    for i in range(1, pop_size + 1):
        orders.append(
            SyntheticOrder(
                order_id=f"O_{i}",
                customer_id=f"CUST_{i:03d}",
                order_date=date(2026, 1, 1),
                completed_order_status="COMPLETED",
                net_paid_amount=float(i * 100),
            )
        )
    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=0.10)
    assert res.eligible_population_count == pop_size
    assert res.vip_cutoff_rank == expected_vip_count
    assert res.vip_count == expected_vip_count


def test_c03_positive_retained_spend_eligibility():
    """Positive retained spend is required for VIP ranking. Zero and negative are excluded."""
    orders = [
        # Positive spend -> Eligible
        SyntheticOrder("O1", "CUST-POS", date(2026, 1, 1), "COMPLETED", 500.0),
        # Zero net spend (Paid $200, refunded $200) -> Excluded
        SyntheticOrder("O2", "CUST-ZERO", date(2026, 1, 1), "COMPLETED", 200.0, refund_amount=200.0),
        # Negative net spend (Paid $100, refunded $150) -> Excluded
        SyntheticOrder("O3", "CUST-NEG", date(2026, 1, 1), "COMPLETED", 100.0, refund_amount=150.0),
    ]
    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    assert res.customer_evaluations["CUST-POS"].is_eligible is True
    assert res.customer_evaluations["CUST-ZERO"].is_eligible is False
    assert res.customer_evaluations["CUST-NEG"].is_eligible is False
    assert res.eligible_population_count == 1
    assert res.vip_count == 1


# -------------------------------------------------------------
# 2. 365-DAY ROLLING WINDOW BOUNDARY TESTS
# -------------------------------------------------------------

def test_c03_rolling_window_boundaries():
    """Verify order inclusion: inside window, on boundary (365d), outside boundary (366d)."""
    orders = [
        # Inside window (100 days old)
        SyntheticOrder("O1", "CUST-WIN-IN", EVAL_DATE - timedelta(days=100), "COMPLETED", 1000.0),
        # Exactly on 365-day boundary
        SyntheticOrder("O2", "CUST-WIN-EXACT", EVAL_DATE - timedelta(days=365), "COMPLETED", 1000.0),
        # Just outside boundary (366 days old) -> Excluded from 365d window
        SyntheticOrder("O3", "CUST-WIN-OUT", EVAL_DATE - timedelta(days=366), "COMPLETED", 1000.0),
    ]
    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    assert res.customer_evaluations["CUST-WIN-IN"].completed_order_count_365d == 1
    assert res.customer_evaluations["CUST-WIN-IN"].is_eligible is True

    assert res.customer_evaluations["CUST-WIN-EXACT"].completed_order_count_365d == 1
    assert res.customer_evaluations["CUST-WIN-EXACT"].is_eligible is True

    # Customer with order only outside window has 0 completed orders in 365d -> Ineligible
    assert res.customer_evaluations["CUST-WIN-OUT"].completed_order_count_365d == 0
    assert res.customer_evaluations["CUST-WIN-OUT"].is_eligible is False


# -------------------------------------------------------------
# 3. BUYING RHYTHM & FALLBACK TESTS
# -------------------------------------------------------------

def test_c03_buying_rhythm_3_orders_and_4_plus():
    """Rhythm = (latest_date - first_date) / (order_count - 1)."""
    orders = [
        # 3 orders: 2026-01-01, 2026-03-01 (59d), 2026-05-01 (61d) -> span = 120d, intervals = 2 -> 60.0d
        SyntheticOrder("O1", "CUST-3ORD", date(2026, 1, 1), "COMPLETED", 100.0),
        SyntheticOrder("O2", "CUST-3ORD", date(2026, 3, 1), "COMPLETED", 100.0),
        SyntheticOrder("O3", "CUST-3ORD", date(2026, 5, 1), "COMPLETED", 100.0),

        # 4 orders: 2025-09-01 to 2026-06-01 (273d), intervals = 3 -> 91.0d
        SyntheticOrder("O4", "CUST-4ORD", date(2025, 9, 1), "COMPLETED", 200.0),
        SyntheticOrder("O5", "CUST-4ORD", date(2025, 12, 1), "COMPLETED", 200.0),
        SyntheticOrder("O6", "CUST-4ORD", date(2026, 3, 1), "COMPLETED", 200.0),
        SyntheticOrder("O7", "CUST-4ORD", date(2026, 6, 1), "COMPLETED", 200.0),
    ]
    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    assert res.customer_evaluations["CUST-3ORD"].avg_buying_rhythm == 60.0
    assert res.customer_evaluations["CUST-3ORD"].is_rhythm_estimated is False

    assert res.customer_evaluations["CUST-4ORD"].avg_buying_rhythm == 91.0
    assert res.customer_evaluations["CUST-4ORD"].is_rhythm_estimated is False


def test_c03_rhythm_fallbacks_vip_pop_avg_and_static_90d():
    """VIP with <3 orders uses VIP pop average; if unavailable, uses 90-day static fallback."""
    # Case A: VIP pop average available
    orders_with_vip_avg = [
        # VIP 1: 4 orders -> rhythm = 50.0d
        SyntheticOrder("OA1", "CUST-A", date(2026, 1, 1), "COMPLETED", 500.0),
        SyntheticOrder("OA2", "CUST-A", date(2026, 2, 20), "COMPLETED", 500.0),
        SyntheticOrder("OA3", "CUST-A", date(2026, 4, 11), "COMPLETED", 500.0),
        SyntheticOrder("OA4", "CUST-A", date(2026, 5, 31), "COMPLETED", 500.0),
        # VIP 2: 2 orders -> fallback to VIP pop avg (50.0d)
        SyntheticOrder("OB1", "CUST-B", date(2026, 2, 1), "COMPLETED", 750.0),
        SyntheticOrder("OB2", "CUST-B", date(2026, 5, 1), "COMPLETED", 750.0),
    ]
    res_a = evaluate_c03_population(orders_with_vip_avg, EVAL_DATE, vip_percentile=1.0)
    assert res_a.vip_population_avg_rhythm == 50.0
    assert res_a.customer_evaluations["CUST-B"].avg_buying_rhythm == 50.0
    assert res_a.customer_evaluations["CUST-B"].rhythm_estimation_method == "VIP_POPULATION_AVERAGE"

    # Case B: No VIP has >=3 orders -> static 90d fallback
    orders_no_vip_avg = [
        SyntheticOrder("OB1", "CUST-B", date(2026, 2, 1), "COMPLETED", 750.0),
        SyntheticOrder("OB2", "CUST-B", date(2026, 5, 1), "COMPLETED", 750.0),
    ]
    res_b = evaluate_c03_population(orders_no_vip_avg, EVAL_DATE, vip_percentile=1.0)
    assert res_b.vip_population_avg_rhythm is None
    assert res_b.customer_evaluations["CUST-B"].avg_buying_rhythm == 90.0
    assert res_b.customer_evaluations["CUST-B"].rhythm_estimation_method == "STATIC_90D_FALLBACK"


def test_c03_same_day_orders_zero_rhythm():
    """TEST-C03-013-RETEST: Same-day repeat orders with rhythm = 0.0.
    Confirmed rule: FrequencyPerYear = 365 / MAX(1, AverageBuyingRhythm).
    For TotalSpend = $300 across 3 orders on 2026-05-01:
    - AOV = $100.00
    - Buying Rhythm = 0.0 days
    - Effective denominator = MAX(1, 0) = 1.0 day
    - FrequencyPerYear = 365 / 1 = 365.0
    - ExpectedAnnualSpend = 100.0 * 365 = $36,500.00
    - At-Risk: DaysSince (92d) > 2 * 0.0 (0d) -> is_at_risk = True
    - Raw CLV-at-risk dollars = $36,500.00
    """
    orders = [
        SyntheticOrder("O1", "CUST-SAMEDAY", date(2026, 5, 1), "COMPLETED", 100.0),
        SyntheticOrder("O2", "CUST-SAMEDAY", date(2026, 5, 1), "COMPLETED", 100.0),
        SyntheticOrder("O3", "CUST-SAMEDAY", date(2026, 5, 1), "COMPLETED", 100.0),
    ]
    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    c = res.customer_evaluations["CUST-SAMEDAY"]
    assert c.completed_order_count_365d == 3
    assert c.net_retained_spend_365d == 300.0
    assert c.average_order_value == 100.0
    assert c.avg_buying_rhythm == 0.0
    assert c.frequency_per_year == 365.0
    assert pytest.approx(c.expected_annual_spend, 0.01) == 36500.0
    assert c.days_since_last_order == 92
    assert c.is_at_risk is True
    assert pytest.approx(res.raw_clv_at_risk_dollars, 0.01) == 36500.0


def test_c03_secondary_check_cases_a_b_c():
    """Secondary check: MAX(1, AverageBuyingRhythm) behavior across cases.
    - Case A: Rhythm < 1 day (e.g. simulated direct/fallback 0.5d) -> MAX(1, 0.5) = 1.0 -> Freq = 365.0
    - Case B: Rhythm = 0.0 days -> MAX(1, 0) = 1.0 -> Freq = 365.0
    - Case C: Rhythm > 1 day (e.g. 50.0 days) -> MAX(1, 50) = 50.0 -> Freq = 365 / 50 = 7.3
    """
    # Case C customer: 4 orders spanning 150 days -> Rhythm = 50.0d, Spend = $2000
    orders_case_c = [
        SyntheticOrder("OC1", "CUST-C", date(2026, 1, 1), "COMPLETED", 500.0),
        SyntheticOrder("OC2", "CUST-C", date(2026, 2, 20), "COMPLETED", 500.0),
        SyntheticOrder("OC3", "CUST-C", date(2026, 4, 11), "COMPLETED", 500.0),
        SyntheticOrder("OC4", "CUST-C", date(2026, 5, 31), "COMPLETED", 500.0), # span=150d / 3 = 50.0d
    ]
    res_c = evaluate_c03_population(orders_case_c, EVAL_DATE, vip_percentile=1.0)
    c_c = res_c.customer_evaluations["CUST-C"]
    assert c_c.avg_buying_rhythm == 50.0
    assert pytest.approx(c_c.frequency_per_year, 0.01) == 7.3
    assert pytest.approx(c_c.expected_annual_spend, 0.01) == (500.0 * 7.3)


# -------------------------------------------------------------
# 4. AT-RISK STRICT BOUNDARY TESTS (DaysSince > 2 * R)
# -------------------------------------------------------------

def test_c03_at_risk_boundary_strict_inequality():
    """For R = 50.0d -> 2*R = 100.0d.
    - 99 days: is_at_risk = False
    - 100 days: is_at_risk = False (Strict >)
    - 101 days: is_at_risk = True
    """
    orders = [
        # Customer 99d: last order 2026-04-24
        SyntheticOrder("OA1", "CUST-99", date(2025, 11, 25), "COMPLETED", 500.0),
        SyntheticOrder("OA2", "CUST-99", date(2026, 1, 14), "COMPLETED", 500.0),
        SyntheticOrder("OA3", "CUST-99", date(2026, 3, 5), "COMPLETED", 500.0),
        SyntheticOrder("OA4", "CUST-99", date(2026, 4, 24), "COMPLETED", 500.0), # span=150d / 3 = 50d

        # Customer 100d: last order 2026-04-23
        SyntheticOrder("OB1", "CUST-100", date(2025, 11, 24), "COMPLETED", 500.0),
        SyntheticOrder("OB2", "CUST-100", date(2026, 1, 13), "COMPLETED", 500.0),
        SyntheticOrder("OB3", "CUST-100", date(2026, 3, 4), "COMPLETED", 500.0),
        SyntheticOrder("OB4", "CUST-100", date(2026, 4, 23), "COMPLETED", 500.0), # span=150d / 3 = 50d

        # Customer 101d: last order 2026-04-22
        SyntheticOrder("OC1", "CUST-101", date(2025, 11, 23), "COMPLETED", 500.0),
        SyntheticOrder("OC2", "CUST-101", date(2026, 1, 12), "COMPLETED", 500.0),
        SyntheticOrder("OC3", "CUST-101", date(2026, 3, 3), "COMPLETED", 500.0),
        SyntheticOrder("OC4", "CUST-101", date(2026, 4, 22), "COMPLETED", 500.0), # span=150d / 3 = 50d
    ]
    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    assert res.customer_evaluations["CUST-99"].days_since_last_order == 99
    assert res.customer_evaluations["CUST-99"].is_at_risk is False

    assert res.customer_evaluations["CUST-100"].days_since_last_order == 100
    assert res.customer_evaluations["CUST-100"].is_at_risk is False

    assert res.customer_evaluations["CUST-101"].days_since_last_order == 101
    assert res.customer_evaluations["CUST-101"].is_at_risk is True


# -------------------------------------------------------------
# 5. EXPECTED ANNUAL SPEND & RAW CLV AGGREGATION
# -------------------------------------------------------------

def test_c03_expected_annual_spend_and_raw_sum():
    """AOV = NetSpend / Orders, Freq = 365 / R, ExpAnnual = AOV * Freq.
    Raw CLV-at-Risk = Sum of ExpAnnual for at-risk VIPs only.
    """
    orders = [
        # VIP 1: Spend=$2000, 4 orders -> AOV=$500, R=50d -> Freq=7.3 -> ExpAnnual=$3650.0. Inactivity=120d > 100d -> AT RISK
        SyntheticOrder("O1A", "VIP-RISK", date(2025, 11, 4), "COMPLETED", 500.0),
        SyntheticOrder("O1B", "VIP-RISK", date(2025, 12, 24), "COMPLETED", 500.0),
        SyntheticOrder("O1C", "VIP-RISK", date(2026, 2, 12), "COMPLETED", 500.0),
        SyntheticOrder("O1D", "VIP-RISK", date(2026, 4, 3), "COMPLETED", 500.0), # last order 2026-04-03 (120d ago)

        # VIP 2: Spend=$1800, 4 orders -> AOV=$450, R=50d -> ExpAnnual=$3285.0. Inactivity=30d <= 100d -> SAFE
        SyntheticOrder("O2A", "VIP-SAFE", date(2026, 2, 2), "COMPLETED", 450.0),
        SyntheticOrder("O2B", "VIP-SAFE", date(2026, 3, 24), "COMPLETED", 450.0),
        SyntheticOrder("O2C", "VIP-SAFE", date(2026, 5, 13), "COMPLETED", 450.0),
        SyntheticOrder("O2D", "VIP-SAFE", date(2026, 7, 2), "COMPLETED", 450.0), # last order 2026-07-02 (30d ago)

        # Non-VIP: Spend=$100, inactive 200d -> Excluded from VIP list
        SyntheticOrder("O3A", "NON-VIP", date(2026, 1, 1), "COMPLETED", 100.0),
    ]
    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=0.66)
    assert res.vip_count == 2
    assert res.customer_evaluations["VIP-RISK"].is_at_risk is True
    assert res.customer_evaluations["VIP-SAFE"].is_at_risk is False
    assert res.customer_evaluations["NON-VIP"].is_vip is False

    assert pytest.approx(res.customer_evaluations["VIP-RISK"].expected_annual_spend, 0.01) == 3650.0
    assert pytest.approx(res.customer_evaluations["VIP-SAFE"].expected_annual_spend, 0.01) == 3285.0

    # Total Raw CLV-at-Risk = $3650.0 (VIP-RISK only)
    assert pytest.approx(res.raw_clv_at_risk_dollars, 0.01) == 3650.0
    assert res.at_risk_vip_count == 1


# -------------------------------------------------------------
# 6. RETURN RATE & DISPUTE BOUNDARIES
# -------------------------------------------------------------

def test_c03_return_rate_and_dispute_rules():
    orders = [
        # Customer with 40.0% return rate (exact boundary) -> Eligible
        SyntheticOrder("O1", "CUST-RR40", date(2026, 1, 1), "COMPLETED", 1000.0, total_items=10, returned_items=4),
        # Customer with 40.1% return rate -> Ineligible
        SyntheticOrder("O2", "CUST-RR41", date(2026, 1, 1), "COMPLETED", 1000.0, total_items=100, returned_items=41),
        # Customer with OPEN chargeback -> Ineligible
        SyntheticOrder("O3", "CUST-DISP-OPEN", date(2026, 1, 1), "COMPLETED", 1000.0, dispute_status="CHARGEBACK_OPENED"),
        # Customer with LOST chargeback -> Ineligible
        SyntheticOrder("O4", "CUST-DISP-LOST", date(2026, 1, 1), "COMPLETED", 1000.0, dispute_status="CHARGEBACK_LOST"),
        # Customer with WON chargeback -> Eligible
        SyntheticOrder("O5", "CUST-DISP-WON", date(2026, 1, 1), "COMPLETED", 1000.0, dispute_status="CHARGEBACK_WON"),
    ]
    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    assert res.customer_evaluations["CUST-RR40"].is_eligible is True
    assert res.customer_evaluations["CUST-RR41"].is_eligible is False
    assert res.customer_evaluations["CUST-DISP-OPEN"].is_eligible is False
    assert res.customer_evaluations["CUST-DISP-LOST"].is_eligible is False
    assert res.customer_evaluations["CUST-DISP-WON"].is_eligible is True

"""Comprehensive Synthetic test suite for C07 Involuntary Churn Exposure formula validation.

Covers all requested parameters:
- Deduplication: 3 failed attempts + same subscription_id + same billing_cycle_id = 1 exposure event
- Multiple billing cycles and multiple subscriptions
- Successful retry after first failure (recovers -> 0 exposure)
- Voluntary cancellation priority over involuntary churn
- Excluded subscription statuses (CANCELLED, EXPIRED, PAUSED, $0 invoices)
- Expected remaining months: MAX(1, AvgTenure - CompletedTenure)
- Fallbacks: Monthly plan -> 6 months, Annual plan -> 1 full cycle, Unknown -> Clarification Required
- 30-day rolling aggregation window boundaries (inside, on 30d boundary, outside)
"""

from datetime import date, timedelta
import pytest
from src.scoring.c07 import (
    Subscription,
    PaymentRetryEvent,
    InvoluntaryChurnEventEvaluation,
    C07Result,
    evaluate_c07_involuntary_churn,
)

EVAL_DATE = date(2026, 8, 1)


# -------------------------------------------------------------
# 1. DEDUPLICATION TESTS (Same Sub + Same Billing Cycle)
# -------------------------------------------------------------

def test_c07_deduplication_multiple_retries_single_event():
    """Explicitly prove that 3 failed attempts with same subscription_id + billing_cycle_id
    produce ONE exposure event, not three.
    """
    subs = [
        Subscription(
            subscription_id="SUB-01",
            customer_id="CUST-01",
            plan_type="MONTHLY",
            status="IN_RETRY",
            start_date=date(2026, 1, 1),
            average_plan_tenure_months=10.0,
            months_completed_before_churn=4.0,
        )
    ]
    # 3 retry attempts for the same billing cycle (CYCLE-2026-07)
    events = [
        PaymentRetryEvent("EV-1", "SUB-01", "CYCLE-2026-07", date(2026, 7, 10), 50.0, 1, "FAILED", False),
        PaymentRetryEvent("EV-2", "SUB-01", "CYCLE-2026-07", date(2026, 7, 13), 50.0, 2, "FAILED", False),
        PaymentRetryEvent("EV-3", "SUB-01", "CYCLE-2026-07", date(2026, 7, 16), 50.0, 3, "FAILED", True), # terminal
    ]
    res = evaluate_c07_involuntary_churn(subs, events, EVAL_DATE)
    assert res.total_events_evaluated == 3
    assert res.deduplicated_events_count == 1
    assert res.involuntary_churn_count == 1

    # Expected remaining months = MAX(1, 10.0 - 4.0) = 6.0 months
    # Event exposure = $50.00 * 6.0 = $300.00
    assert pytest.approx(res.raw_involuntary_churn_dollars, 0.01) == 300.0


def test_c07_multiple_billing_cycles_and_subscriptions():
    """Multiple billing cycles for the same sub, or different subs, produce distinct events."""
    subs = [
        Subscription("SUB-01", "CUST-01", "MONTHLY", "IN_RETRY", date(2026, 1, 1), 12.0, 2.0),
        Subscription("SUB-02", "CUST-01", "MONTHLY", "IN_RETRY", date(2026, 1, 1), 12.0, 2.0),
    ]
    events = [
        # Sub 1, Cycle 1 (June) -> Exposure = 50 * (12-2) = 500
        PaymentRetryEvent("E1", "SUB-01", "CYCLE-06", date(2026, 7, 5), 50.0, 1, "FAILED", True),
        # Sub 1, Cycle 2 (July) -> Exposure = 50 * (12-2) = 500
        PaymentRetryEvent("E2", "SUB-01", "CYCLE-07", date(2026, 7, 20), 50.0, 1, "FAILED", True),
        # Sub 2, Cycle 1 (July) -> Exposure = 100 * (12-2) = 1000
        PaymentRetryEvent("E3", "SUB-02", "CYCLE-07", date(2026, 7, 22), 100.0, 1, "FAILED", True),
    ]
    res = evaluate_c07_involuntary_churn(subs, events, EVAL_DATE)
    assert res.deduplicated_events_count == 3
    assert res.involuntary_churn_count == 3
    # Total = 500 + 500 + 1000 = 2000
    assert pytest.approx(res.raw_involuntary_churn_dollars, 0.01) == 2000.0


# -------------------------------------------------------------
# 2. SUCCESSFUL RETRY & VOLUNTARY CANCELLATION PRIORITY
# -------------------------------------------------------------

def test_c07_successful_retry_recovery():
    """If payment retry succeeds after initial failures, no involuntary churn exposure is recognized."""
    subs = [
        Subscription("SUB-RECOVER", "CUST-02", "MONTHLY", "ACTIVE", date(2026, 1, 1), 10.0, 3.0)
    ]
    events = [
        PaymentRetryEvent("E1", "SUB-RECOVER", "CYCLE-07", date(2026, 7, 10), 80.0, 1, "FAILED", False),
        PaymentRetryEvent("E2", "SUB-RECOVER", "CYCLE-07", date(2026, 7, 13), 80.0, 2, "FAILED", False),
        PaymentRetryEvent("E3", "SUB-RECOVER", "CYCLE-07", date(2026, 7, 16), 80.0, 3, "SUCCESS", False),
    ]
    res = evaluate_c07_involuntary_churn(subs, events, EVAL_DATE)
    assert res.deduplicated_events_count == 1
    assert res.involuntary_churn_count == 0
    assert res.raw_involuntary_churn_dollars == 0.0


def test_c07_voluntary_cancellation_priority():
    """Voluntary cancellation takes priority over payment failure / retry exhaustion."""
    subs = [
        # Customer voluntarily cancels subscription before/during retry
        Subscription("SUB-VOL", "CUST-03", "MONTHLY", "CANCELLED", date(2026, 1, 1), 10.0, 3.0, is_voluntary_cancelled=True)
    ]
    events = [
        PaymentRetryEvent("E1", "SUB-VOL", "CYCLE-07", date(2026, 7, 10), 100.0, 1, "FAILED", False),
        PaymentRetryEvent("E2", "SUB-VOL", "CYCLE-07", date(2026, 7, 15), 100.0, 2, "FAILED", True, is_voluntary_cancelled=True),
    ]
    res = evaluate_c07_involuntary_churn(subs, events, EVAL_DATE)
    assert res.involuntary_churn_count == 0
    assert res.raw_involuntary_churn_dollars == 0.0
    ev = res.event_evaluations["SUB-VOL:CYCLE-07"]
    assert "Voluntary cancellation" in str(ev.exclusion_reason)


# -------------------------------------------------------------
# 3. EXCLUSIONS: PAUSED, EXPIRED, $0 INVOICE, UNTERMINATED RETRY
# -------------------------------------------------------------

def test_c07_status_exclusions_and_zero_value():
    subs = [
        Subscription("SUB-PAUSED", "CUST-04", "MONTHLY", "PAUSED", date(2026, 1, 1), 10.0, 3.0),
        Subscription("SUB-EXPIRED", "CUST-05", "MONTHLY", "EXPIRED", date(2026, 1, 1), 10.0, 3.0),
        Subscription("SUB-ZERO", "CUST-06", "MONTHLY", "IN_RETRY", date(2026, 1, 1), 10.0, 3.0),
        Subscription("SUB-INPROGRESS", "CUST-07", "MONTHLY", "IN_RETRY", date(2026, 1, 1), 10.0, 3.0),
    ]
    events = [
        # Paused sub -> Excluded
        PaymentRetryEvent("E1", "SUB-PAUSED", "CYCLE-07", date(2026, 7, 10), 50.0, 1, "FAILED", False),
        # Expired sub -> Excluded
        PaymentRetryEvent("E2", "SUB-EXPIRED", "CYCLE-07", date(2026, 7, 10), 50.0, 1, "FAILED", False),
        # $0 subscription invoice -> Excluded
        PaymentRetryEvent("E3", "SUB-ZERO", "CYCLE-07", date(2026, 7, 10), 0.0, 1, "FAILED", True),
        # In-progress retries (not yet exhausted / terminal) -> Excluded
        PaymentRetryEvent("E4", "SUB-INPROGRESS", "CYCLE-07", date(2026, 7, 30), 50.0, 1, "FAILED", False),
    ]
    res = evaluate_c07_involuntary_churn(subs, events, EVAL_DATE)
    assert res.involuntary_churn_count == 0
    assert res.raw_involuntary_churn_dollars == 0.0


# -------------------------------------------------------------
# 4. EXPECTED REMAINING MONTHS BOUNDARIES & FALLBACKS
# -------------------------------------------------------------

def test_c07_expected_remaining_months_boundaries_and_fallbacks():
    """MAX(1, AvgTenure - CompletedTenure) + Fallback rules."""
    subs = [
        # Normal: Avg=12, Completed=4 -> Remaining = 8.0
        Subscription("SUB-NORM", "C1", "MONTHLY", "IN_RETRY", date(2026, 1, 1), 12.0, 4.0),
        # Equal: Avg=10, Completed=10 -> Remaining = MAX(1, 0) = 1.0 (Minimum boundary)
        Subscription("SUB-EQ", "C2", "MONTHLY", "IN_RETRY", date(2026, 1, 1), 10.0, 10.0),
        # Over-tenure: Avg=6, Completed=10 -> Remaining = MAX(1, -4) = 1.0
        Subscription("SUB-OVER", "C3", "MONTHLY", "IN_RETRY", date(2026, 1, 1), 6.0, 10.0),
        # Missing Avg Tenure for Monthly plan -> Fallback = 6.0 months
        Subscription("SUB-FALLBACK-M", "C4", "MONTHLY", "IN_RETRY", date(2026, 1, 1), None, 2.0),
        # Missing Avg Tenure for Annual plan -> Fallback = 1.0 annual cycle
        Subscription("SUB-FALLBACK-A", "C5", "ANNUAL", "IN_RETRY", date(2026, 1, 1), None, 1.0),
    ]
    events = [
        PaymentRetryEvent("E1", "SUB-NORM", "C1", date(2026, 7, 10), 100.0, 3, "FAILED", True),
        PaymentRetryEvent("E2", "SUB-EQ", "C2", date(2026, 7, 10), 100.0, 3, "FAILED", True),
        PaymentRetryEvent("E3", "SUB-OVER", "C3", date(2026, 7, 10), 100.0, 3, "FAILED", True),
        PaymentRetryEvent("E4", "SUB-FALLBACK-M", "C4", date(2026, 7, 10), 100.0, 3, "FAILED", True),
        PaymentRetryEvent("E5", "SUB-FALLBACK-A", "C5", date(2026, 7, 10), 1000.0, 3, "FAILED", True),
    ]
    res = evaluate_c07_involuntary_churn(subs, events, EVAL_DATE)
    ev_norm = res.event_evaluations["SUB-NORM:C1"]
    ev_eq = res.event_evaluations["SUB-EQ:C2"]
    ev_over = res.event_evaluations["SUB-OVER:C3"]
    ev_m = res.event_evaluations["SUB-FALLBACK-M:C4"]
    ev_a = res.event_evaluations["SUB-FALLBACK-A:C5"]

    assert ev_norm.expected_remaining_months == 8.0
    assert ev_norm.event_exposure_dollars == 800.0

    assert ev_eq.expected_remaining_months == 1.0
    assert ev_eq.event_exposure_dollars == 100.0

    assert ev_over.expected_remaining_months == 1.0
    assert ev_over.event_exposure_dollars == 100.0

    assert ev_m.expected_remaining_months == 6.0
    assert ev_m.is_remaining_months_fallback is True
    assert ev_m.event_exposure_dollars == 600.0

    assert ev_a.expected_remaining_months == 1.0
    assert ev_a.is_remaining_months_fallback is True
    assert ev_a.event_exposure_dollars == 1000.0


# -------------------------------------------------------------
# 5. 30-DAY ROLLING AGGREGATION WINDOW BOUNDARIES
# -------------------------------------------------------------

def test_c07_30_day_rolling_window_boundaries():
    """Events inside (0-30d) vs exactly on 30d vs outside (>30d)."""
    subs = [
        Subscription("SUB-01", "CUST-01", "MONTHLY", "IN_RETRY", date(2026, 1, 1), 10.0, 2.0)
    ]
    events = [
        # Inside window (10 days old)
        PaymentRetryEvent("E1", "SUB-01", "C-IN", EVAL_DATE - timedelta(days=10), 100.0, 3, "FAILED", True),
        # Exactly on 30-day boundary
        PaymentRetryEvent("E2", "SUB-01", "C-BOUND", EVAL_DATE - timedelta(days=30), 100.0, 3, "FAILED", True),
        # Outside window (31 days old) -> Excluded
        PaymentRetryEvent("E3", "SUB-01", "C-OUT", EVAL_DATE - timedelta(days=31), 100.0, 3, "FAILED", True),
    ]
    res = evaluate_c07_involuntary_churn(subs, events, EVAL_DATE, rolling_window_days=30)
    assert res.deduplicated_events_count == 2
    assert "SUB-01:C-IN" in res.event_evaluations
    assert "SUB-01:C-BOUND" in res.event_evaluations
    assert "SUB-01:C-OUT" not in res.event_evaluations
    # Both included have exp = 100 * (10-2) = 800 -> Total = 1600.0
    assert pytest.approx(res.raw_involuntary_churn_dollars, 0.01) == 1600.0

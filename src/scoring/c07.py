"""C07: Involuntary Churn Exposure (Formula Engine).

Business: Zeitster
Category: Category 3 — Customer & Retention Health
Formula: C07 — Involuntary Churn Exposure

Mathematical Formulation:
EventExposure = FailedSubscriptionOrderValue * ExpectedRemainingMonths
ExpectedRemainingMonths = MAX(1, AveragePlanTenureMonths - MonthsCompletedBeforeChurn)
Rolling 30-day exposure aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class Subscription:
    subscription_id: str
    customer_id: str
    plan_type: str  # 'MONTHLY', 'ANNUAL', 'QUARTERLY', etc.
    status: str  # 'ACTIVE', 'PAST_DUE', 'IN_RETRY', 'CANCELLED', 'PAUSED', 'EXPIRED', 'TERMINATED_PAYMENT_FAILED'
    start_date: date
    average_plan_tenure_months: Optional[float] = None
    months_completed_before_churn: float = 0.0
    is_voluntary_cancelled: bool = False


@dataclass
class PaymentRetryEvent:
    event_id: str
    subscription_id: str
    billing_cycle_id: str
    event_date: date
    invoice_amount: float
    retry_number: int
    payment_status: str  # 'FAILED', 'SUCCESS'
    is_terminal_failure: bool = False  # True when retries are exhausted
    is_voluntary_cancelled: bool = False


@dataclass
class InvoluntaryChurnEventEvaluation:
    event_key: str  # f"{subscription_id}:{billing_cycle_id}"
    subscription_id: str
    billing_cycle_id: str
    customer_id: str
    plan_type: str
    event_date: date
    failed_invoice_amount: float
    months_completed: float
    average_plan_tenure: Optional[float]
    expected_remaining_months: float
    is_remaining_months_fallback: bool
    remaining_months_fallback_reason: Optional[str]
    is_eligible_subscription: bool
    is_involuntary_churn: bool
    exclusion_reason: Optional[str]
    event_exposure_dollars: float
    business_clarifications: List[str] = field(default_factory=list)


@dataclass
class C07Result:
    evaluation_date: date
    rolling_window_days: int
    total_events_evaluated: int
    deduplicated_events_count: int
    involuntary_churn_count: int
    raw_involuntary_churn_dollars: float
    c07_involuntary_churn_score: Optional[float] = None  # BUSINESS PENDING
    event_evaluations: Dict[str, InvoluntaryChurnEventEvaluation] = field(default_factory=dict)
    business_clarifications: List[str] = field(default_factory=list)


def evaluate_c07_involuntary_churn(
    subscriptions: List[Subscription],
    events: List[PaymentRetryEvent],
    evaluation_date: date,
    rolling_window_days: int = 30,
) -> C07Result:
    """Evaluates C07 Involuntary Churn Exposure strictly per specification."""
    clarifications: List[str] = []
    sub_map: Dict[str, Subscription] = {s.subscription_id: s for s in subscriptions}
    
    # 1. Filter events by rolling 30-day window
    # Window: 0 <= (evaluation_date - event_date).days <= 30
    window_events = [
        e for e in events
        if 0 <= (evaluation_date - e.event_date).days <= rolling_window_days
    ]
    
    # 2. Group events by (subscription_id, billing_cycle_id) for deduplication
    grouped_events: Dict[Tuple[str, str], List[PaymentRetryEvent]] = {}
    for e in window_events:
        grouped_events.setdefault((e.subscription_id, e.billing_cycle_id), []).append(e)
        
    event_evals: Dict[str, InvoluntaryChurnEventEvaluation] = {}
    raw_involuntary_churn_dollars = 0.0
    involuntary_churn_count = 0
    
    for (sub_id, cycle_id), cycle_events in grouped_events.items():
        event_key = f"{sub_id}:{cycle_id}"
        sub = sub_map.get(sub_id)
        
        # Sort events by retry_number / event_date
        cycle_events.sort(key=lambda x: (x.event_date, x.retry_number))
        latest_event = cycle_events[-1]
        
        # Determine if any payment succeeded
        has_success = any(e.payment_status.upper() == "SUCCESS" for e in cycle_events)
        
        # Determine if any voluntary cancellation occurred
        is_voluntary = (
            (sub and sub.is_voluntary_cancelled) or
            any(e.is_voluntary_cancelled for e in cycle_events) or
            (sub and sub.status.upper() in {"CANCELLED", "PAUSED", "EXPIRED"} and not any(e.is_terminal_failure for e in cycle_events))
        )
        
        # Determine terminal failure
        # Involuntary churn occurs ONLY after payment retries are exhausted (is_terminal_failure=True)
        # or subscription is formally classified as terminated due to payment failure
        is_terminal = any(e.is_terminal_failure for e in cycle_events) or (sub is not None and sub.status.upper() in {"TERMINATED_PAYMENT_FAILED", "PAYMENT_FAILED_TERMINATED"})
        
        # Check subscription eligibility
        # Eligible during retry: ACTIVE / PAST_DUE / IN_RETRY
        # Exclude: Cancelled, Expired, Paused, $0 subscriptions
        is_eligible = True
        exclusion_reason = None
        
        if sub is None:
            is_eligible = False
            exclusion_reason = "Subscription record not found"
        elif sub.status.upper() in {"CANCELLED", "PAUSED", "EXPIRED"} and not is_terminal:
            is_eligible = False
            exclusion_reason = f"Subscription status '{sub.status}' is excluded"
        elif latest_event.invoice_amount <= 0:
            is_eligible = False
            exclusion_reason = f"Invoice amount ${latest_event.invoice_amount:.2f} is <= 0 ($0 subscriptions excluded)"
        elif is_voluntary:
            is_eligible = False
            exclusion_reason = "Voluntary cancellation takes priority over involuntary churn"
        elif has_success:
            is_eligible = False
            exclusion_reason = "Payment retry succeeded; no involuntary churn"
        elif not is_terminal:
            is_eligible = False
            exclusion_reason = "Payment retries not yet exhausted; subscription not formally terminated"
            
        is_involuntary = is_eligible and is_terminal and not is_voluntary and not has_success and (latest_event.invoice_amount > 0)
        
        # Calculate Expected Remaining Months
        plan_type = sub.plan_type.upper() if sub else "UNKNOWN"
        months_completed = sub.months_completed_before_churn if sub else 0.0
        avg_tenure = sub.average_plan_tenure_months if sub else None
        
        is_fallback = False
        fallback_reason = None
        event_clarifications: List[str] = []
        
        if avg_tenure is not None:
            # ExpectedRemainingMonths = MAX(1, AveragePlanTenureMonths - MonthsCompletedBeforeChurn)
            exp_remaining = max(1.0, avg_tenure - months_completed)
        else:
            is_fallback = True
            if "MONTH" in plan_type:
                exp_remaining = 6.0
                fallback_reason = "Fallback: Monthly plan default of 6 months applied (average tenure unavailable)"
            elif "ANNUAL" in plan_type or "YEAR" in plan_type:
                exp_remaining = 1.0  # 1 full annual cycle
                fallback_reason = "Fallback: Annual plan default of 1 full annual cycle applied"
            else:
                exp_remaining = 1.0
                fallback_reason = f"BUSINESS CLARIFICATION REQUIRED: Unknown plan type '{plan_type}' with missing average tenure"
                event_clarifications.append(fallback_reason)
                
        # Calculate Event Exposure
        if is_involuntary:
            event_exposure = latest_event.invoice_amount * exp_remaining
            raw_involuntary_churn_dollars += event_exposure
            involuntary_churn_count += 1
        else:
            event_exposure = 0.0
            
        eval_item = InvoluntaryChurnEventEvaluation(
            event_key=event_key,
            subscription_id=sub_id,
            billing_cycle_id=cycle_id,
            customer_id=sub.customer_id if sub else "UNKNOWN",
            plan_type=plan_type,
            event_date=latest_event.event_date,
            failed_invoice_amount=latest_event.invoice_amount,
            months_completed=months_completed,
            average_plan_tenure=avg_tenure,
            expected_remaining_months=exp_remaining,
            is_remaining_months_fallback=is_fallback,
            remaining_months_fallback_reason=fallback_reason,
            is_eligible_subscription=is_eligible,
            is_involuntary_churn=is_involuntary,
            exclusion_reason=exclusion_reason,
            event_exposure_dollars=event_exposure,
            business_clarifications=event_clarifications,
        )
        event_evals[event_key] = eval_item
        
    return C07Result(
        evaluation_date=evaluation_date,
        rolling_window_days=rolling_window_days,
        total_events_evaluated=len(events),
        deduplicated_events_count=len(grouped_events),
        involuntary_churn_count=involuntary_churn_count,
        raw_involuntary_churn_dollars=raw_involuntary_churn_dollars,
        c07_involuntary_churn_score=None,  # BUSINESS PENDING
        event_evaluations=event_evals,
        business_clarifications=clarifications,
    )

"""C03: CLV-at-Risk (Raw Formula Engine).

Business: Zeitster
Category: Category 3 — Customer & Retention Health
Formula: C03 — CLV-at-Risk

This module implements the literal mathematical formulation for C03 as defined
in the business specification, strictly isolating unresolved business clarifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import math
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SyntheticOrder:
    order_id: str
    customer_id: str
    order_date: date
    completed_order_status: str  # 'COMPLETED', 'CANCELLED', 'PENDING', etc.
    net_paid_amount: float
    refund_amount: float = 0.0
    return_amount: float = 0.0
    dispute_status: Optional[str] = None  # None, 'NONE', 'OPEN', 'LOST', 'WON', 'CHARGEBACK_OPENED', etc.
    total_items: int = 1
    returned_items: int = 0


@dataclass
class CustomerEvaluation:
    customer_id: str
    total_paid_365d: float
    total_refunds_returns_365d: float
    net_retained_spend_365d: float
    completed_order_count_365d: int
    first_order_date: Optional[date]
    last_order_date: Optional[date]
    has_disqualifying_dispute: bool
    return_rate: float
    is_eligible: bool
    eligibility_exclusion_reason: Optional[str]
    vip_rank: Optional[int] = None
    is_vip: bool = False
    avg_buying_rhythm: Optional[float] = None
    is_rhythm_estimated: bool = False
    rhythm_estimation_method: Optional[str] = None
    days_since_last_order: Optional[int] = None
    is_at_risk: bool = False
    average_order_value: Optional[float] = None
    frequency_per_year: Optional[float] = None
    expected_annual_spend: Optional[float] = None
    business_clarifications: List[str] = field(default_factory=list)


@dataclass
class C03PopulationResult:
    evaluation_date: date
    total_customers_count: int
    eligible_population_count: int
    vip_cutoff_rank: int
    vip_count: int
    vip_population_avg_rhythm: Optional[float]
    at_risk_vip_count: int
    raw_clv_at_risk_dollars: float
    customer_evaluations: Dict[str, CustomerEvaluation] = field(default_factory=dict)
    business_clarifications: List[str] = field(default_factory=list)


def evaluate_c03_population(
    orders: List[SyntheticOrder],
    evaluation_date: date,
    rolling_window_days: int = 365,
    vip_percentile: float = 0.10,
    vip_rhythm_fallback_days: float = 90.0,
) -> C03PopulationResult:
    """Evaluates C03 CLV-at-Risk across a customer population strictly per specification."""
    clarifications: List[str] = []
    
    # 1. Group orders by customer
    cust_orders: Dict[str, List[SyntheticOrder]] = {}
    for o in orders:
        cust_orders.setdefault(o.customer_id, []).append(o)
    
    evaluations: Dict[str, CustomerEvaluation] = {}
    
    for cid, o_list in cust_orders.items():
        # Filter rolling 365-day window
        window_orders = [
            o for o in o_list
            if 0 <= (evaluation_date - o.order_date).days <= rolling_window_days
        ]
        
        # Spend calculations
        total_paid = sum(o.net_paid_amount for o in window_orders)
        total_refunds_returns = sum(o.refund_amount + o.return_amount for o in window_orders)
        net_retained_spend = total_paid - total_refunds_returns
        
        # Completed orders
        completed_orders = [
            o for o in window_orders
            if o.completed_order_status.upper() in {"COMPLETED", "DELIVERED", "FULFILLED", "SHIPPED"}
        ]
        completed_orders.sort(key=lambda x: x.order_date)
        completed_count = len(completed_orders)
        
        first_date = completed_orders[0].order_date if completed_count > 0 else None
        last_date = completed_orders[-1].order_date if completed_count > 0 else None
        
        # Dispute check (across all history or window - check open/lost dispute)
        has_dispute = any(
            o.dispute_status and o.dispute_status.upper() in {"OPEN", "LOST", "CHARGEBACK_OPENED", "CHARGEBACK_LOST", "NEEDS_RESPONSE"}
            for o in o_list
        )
        
        # Return rate calculation (Items returned / total items or return spend / paid spend)
        total_items = sum(o.total_items for o in window_orders)
        returned_items = sum(o.returned_items for o in window_orders)
        if total_items > 0:
            return_rate = returned_items / total_items
        elif total_paid > 0:
            return_rate = total_refunds_returns / total_paid
        else:
            return_rate = 0.0
            
        # Eligibility
        is_eligible = True
        exclusion_reason = None
        
        if completed_count == 0:
            is_eligible = False
            exclusion_reason = "No completed orders in rolling window"
        elif has_dispute:
            is_eligible = False
            exclusion_reason = "Customer has open or lost dispute history"
        elif return_rate > 0.40:
            is_eligible = False
            exclusion_reason = f"Return rate {return_rate:.1%} exceeds 40% threshold"
        elif net_retained_spend <= 0:
            is_eligible = False
            exclusion_reason = f"Net retained spend ${net_retained_spend:.2f} is not positive"
            
        cust_eval = CustomerEvaluation(
            customer_id=cid,
            total_paid_365d=total_paid,
            total_refunds_returns_365d=total_refunds_returns,
            net_retained_spend_365d=net_retained_spend,
            completed_order_count_365d=completed_count,
            first_order_date=first_date,
            last_order_date=last_date,
            has_disqualifying_dispute=has_dispute,
            return_rate=return_rate,
            is_eligible=is_eligible,
            eligibility_exclusion_reason=exclusion_reason,
        )
        evaluations[cid] = cust_eval

    # 2. Rank eligible customers by Net Retained Spend
    eligible_custs = [e for e in evaluations.values() if e.is_eligible]
    eligible_count = len(eligible_custs)
    
    # Sort descending by Net Retained Spend
    eligible_custs.sort(key=lambda x: x.net_retained_spend_365d, reverse=True)
    
    # VIP Cutoff: CEILING(0.10 * EligiblePopulationCount)
    if eligible_count > 0:
        vip_cutoff_rank = math.ceil(vip_percentile * eligible_count)
    else:
        vip_cutoff_rank = 0
        
    for rank_idx, cust in enumerate(eligible_custs, start=1):
        cust.vip_rank = rank_idx
        if rank_idx <= vip_cutoff_rank:
            cust.is_vip = True
            
    vips = [c for c in eligible_custs if c.is_vip]
    
    # 3. Calculate Direct Customer Buying Rhythm for VIPs with >= 3 completed orders
    vip_rhythms_for_avg: List[float] = []
    for v in vips:
        if v.completed_order_count_365d >= 3 and v.first_order_date and v.last_order_date:
            days_span = (v.last_order_date - v.first_order_date).days
            rhythm = days_span / (v.completed_order_count_365d - 1)
            v.avg_buying_rhythm = rhythm
            v.is_rhythm_estimated = False
            vip_rhythms_for_avg.append(rhythm)
            
    # Calculate VIP Population Average Rhythm
    if vip_rhythms_for_avg:
        vip_pop_avg_rhythm = sum(vip_rhythms_for_avg) / len(vip_rhythms_for_avg)
    else:
        vip_pop_avg_rhythm = None
        
    # 4. Apply Rhythm Fallback for VIPs with < 3 completed orders
    for v in vips:
        if v.completed_order_count_365d < 3 or v.avg_buying_rhythm is None:
            if vip_pop_avg_rhythm is not None:
                v.avg_buying_rhythm = vip_pop_avg_rhythm
                v.is_rhythm_estimated = True
                v.rhythm_estimation_method = "VIP_POPULATION_AVERAGE"
            else:
                # 90-day fallback when VIP population average is unavailable
                v.avg_buying_rhythm = vip_rhythm_fallback_days
                v.is_rhythm_estimated = True
                v.rhythm_estimation_method = "STATIC_90D_FALLBACK"
                v.business_clarifications.append(
                    "Applied 90-day static fallback because VIP population rhythm average was unavailable"
                )

    # 5. Inactivity, Risk, and Expected Annual Spend for VIPs
    raw_clv_at_risk_dollars = 0.0
    at_risk_vip_count = 0
    
    for v in vips:
        if v.last_order_date:
            days_since = (evaluation_date - v.last_order_date).days
            v.days_since_last_order = days_since
            
            # Risk condition: DaysSinceLastOrder > 2 * AvgBuyingRhythm (Strict >)
            if v.avg_buying_rhythm is not None and v.avg_buying_rhythm > 0:
                v.is_at_risk = days_since > (2.0 * v.avg_buying_rhythm)
            elif v.avg_buying_rhythm == 0.0:
                # Zero rhythm boundary
                v.is_at_risk = days_since > 0
                v.business_clarifications.append("Zero buying rhythm encountered (same-day orders)")
                
            # Expected Annual Spend:
            # AverageOrderValue = TotalSpend / TotalOrders
            # FrequencyPerYear = 365 / AverageDaysBetweenOrders
            # ExpectedAnnualSpend = AverageOrderValue * FrequencyPerYear
            if v.completed_order_count_365d > 0:
                v.average_order_value = v.net_retained_spend_365d / v.completed_order_count_365d
            else:
                v.average_order_value = 0.0
                
            if v.avg_buying_rhythm is not None:
                # Confirmed rule: FrequencyPerYear = 365 / MAX(1, AverageBuyingRhythm)
                effective_denominator = max(1.0, v.avg_buying_rhythm)
                v.frequency_per_year = 365.0 / effective_denominator
                v.expected_annual_spend = v.average_order_value * v.frequency_per_year
                if v.avg_buying_rhythm == 0.0:
                    v.business_clarifications.append(
                        "Same-day orders (rhythm=0) clamped to effective denominator of 1 day for frequency calculation"
                    )
            else:
                v.frequency_per_year = 0.0
                v.expected_annual_spend = 0.0
                
            if v.is_at_risk and v.expected_annual_spend:
                raw_clv_at_risk_dollars += v.expected_annual_spend
                at_risk_vip_count += 1

    return C03PopulationResult(
        evaluation_date=evaluation_date,
        total_customers_count=len(evaluations),
        eligible_population_count=eligible_count,
        vip_cutoff_rank=vip_cutoff_rank,
        vip_count=len(vips),
        vip_population_avg_rhythm=vip_pop_avg_rhythm,
        at_risk_vip_count=at_risk_vip_count,
        raw_clv_at_risk_dollars=raw_clv_at_risk_dollars,
        customer_evaluations=evaluations,
        business_clarifications=clarifications,
    )

"""C11: High-Value Customer Loss (Formula Engine).

Business: Zeitster
Category: Category 3 — Customer & Retention Health
Formula: C11 — High-Value Customer Loss

Mathematical Formulation:
VIP population: Reuses C03 VIP population definition strictly.
Established VIP: CompletedOrders >= 3 AND LifetimeDaysSpan >= 90.
InactivityThreshold = MAX(90 days, 1.5 * CustomerAverageDaysBetweenOrders)
Lost VIP: DaysSinceLastOrder > InactivityThreshold
IndividualQuarterlySpend = CustomerTotalNetLifetimeSpend / (CustomerTotalLifetimeDays / 90)
TotalVIPLossExposure = SUM(IndividualQuarterlySpend for every lost VIP)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
from typing import Any, Dict, List, Optional

from src.scoring.c03 import (
    CustomerEvaluation,
    C03PopulationResult,
    SyntheticOrder,
    evaluate_c03_population,
)


@dataclass
class EstablishedVIPEvaluation:
    customer_id: str
    is_vip: bool
    completed_order_count: int
    first_order_date: Optional[date]
    last_order_date: Optional[date]
    history_span_days: int
    is_established_vip: bool
    non_established_reason: Optional[str]
    avg_days_between_orders: Optional[float]
    inactivity_threshold_days: Optional[float]
    days_since_last_order: Optional[int]
    is_lost_vip: bool
    total_net_lifetime_spend: float
    total_lifetime_days: int
    individual_quarterly_spend: Optional[float]
    c11_exposure_dollars: float
    business_clarifications: List[str] = field(default_factory=list)


@dataclass
class C11Result:
    evaluation_date: date
    total_vip_count: int
    established_vip_count: int
    lost_vip_count: int
    raw_vip_loss_dollars: float
    c11_high_value_loss_score: Optional[float] = None  # BUSINESS PENDING
    vip_evaluations: Dict[str, EstablishedVIPEvaluation] = field(default_factory=dict)
    business_clarifications: List[str] = field(default_factory=list)


def evaluate_c11_high_value_loss(
    c03_result: C03PopulationResult,
    evaluation_date: date,
) -> C11Result:
    """Evaluates C11 High-Value Customer Loss reusing C03 VIP population strictly."""
    clarifications: List[str] = []
    
    # 1. Identify VIPs from C03
    vips = [c for c in c03_result.customer_evaluations.values() if c.is_vip]
    
    vip_evals: Dict[str, EstablishedVIPEvaluation] = {}
    established_count = 0
    lost_count = 0
    raw_vip_loss_dollars = 0.0
    
    for v in vips:
        cust_clarifications: List[str] = []
        
        # Check Established VIP condition:
        # Minimum: 3 completed orders AND history spanning at least 90 days
        completed_count = v.completed_order_count_365d
        first_date = v.first_order_date
        last_date = v.last_order_date
        
        if first_date and last_date:
            history_span = (last_date - first_date).days
        else:
            history_span = 0
            
        is_established = True
        non_est_reason = None
        
        if completed_count < 3 and history_span < 90:
            is_established = False
            non_est_reason = f"Orders ({completed_count} < 3) and history span ({history_span}d < 90d) below threshold"
        elif completed_count < 3:
            is_established = False
            non_est_reason = f"Orders ({completed_count} < 3) below threshold of 3 orders"
        elif history_span < 90:
            is_established = False
            non_est_reason = f"History span ({history_span}d < 90d) below threshold of 90 days"
            
        if is_established:
            established_count += 1
            
            # Buying rhythm: CustomerAverageDaysBetweenOrders
            avg_days_between = history_span / (completed_count - 1) if completed_count > 1 else 0.0
            
            # Dynamic Inactivity Threshold: MAX(90 days, 1.5 * CustomerAverageDaysBetweenOrders)
            inactivity_threshold = max(90.0, 1.5 * avg_days_between)
            
            # Lost VIP condition: DaysSinceLastOrder > InactivityThreshold (Strict >)
            days_since = (evaluation_date - last_date).days if last_date else 0
            is_lost = days_since > inactivity_threshold
            
            # Individual Quarterly Spend:
            # CustomerTotalNetLifetimeSpend / (CustomerTotalLifetimeDays / 90)
            net_spend = v.net_retained_spend_365d
            
            # Total Lifetime Days (evaluation_date - first_order_date)
            total_lifetime_days = (evaluation_date - first_date).days if first_date else 0
            
            if total_lifetime_days > 0:
                quarterly_spend = net_spend / (total_lifetime_days / 90.0)
            else:
                quarterly_spend = 0.0
                cust_clarifications.append("Division-by-zero avoided: Total lifetime days is 0")
                
            if is_lost:
                lost_count += 1
                exposure = quarterly_spend
                raw_vip_loss_dollars += exposure
            else:
                exposure = 0.0
        else:
            avg_days_between = None
            inactivity_threshold = None
            days_since = (evaluation_date - last_date).days if last_date else None
            is_lost = False
            net_spend = v.net_retained_spend_365d
            total_lifetime_days = (evaluation_date - first_date).days if first_date else 0
            quarterly_spend = None
            exposure = 0.0
            
        eval_item = EstablishedVIPEvaluation(
            customer_id=v.customer_id,
            is_vip=v.is_vip,
            completed_order_count=completed_count,
            first_order_date=first_date,
            last_order_date=last_date,
            history_span_days=history_span,
            is_established_vip=is_established,
            non_established_reason=non_est_reason,
            avg_days_between_orders=avg_days_between,
            inactivity_threshold_days=inactivity_threshold,
            days_since_last_order=days_since,
            is_lost_vip=is_lost,
            total_net_lifetime_spend=net_spend,
            total_lifetime_days=total_lifetime_days,
            individual_quarterly_spend=quarterly_spend,
            c11_exposure_dollars=exposure,
            business_clarifications=cust_clarifications,
        )
        vip_evals[v.customer_id] = eval_item
        
    return C11Result(
        evaluation_date=evaluation_date,
        total_vip_count=len(vips),
        established_vip_count=established_count,
        lost_vip_count=lost_count,
        raw_vip_loss_dollars=raw_vip_loss_dollars,
        c11_high_value_loss_score=None,  # BUSINESS PENDING
        vip_evaluations=vip_evals,
        business_clarifications=clarifications,
    )

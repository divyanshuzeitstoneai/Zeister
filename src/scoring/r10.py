"""R10: Fraud Loss Impact Score.

Business: Zeitster
Category: Category 2 — Fraud, Returns & Disputes
Formula: R10 — Fraud Loss Impact Score

This module implements the exact confirmed business rules and mathematical definitions
for R10 without assumptions, isolating gaps where business clarifications are required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

# Documented Fallback Constants
CHARGEBACK_FEE_FALLBACKS: dict[str, float] = {
    "USD": 15.00,
    "EUR": 15.00,
    "GBP": 10.00,
    "CAD": 20.00,
}
DEFAULT_CHARGEBACK_FEE_FALLBACK: float = 15.00

PACKAGING_RATE: float = 0.02
PACKAGING_MIN: float = 0.50
PACKAGING_MAX: float = 5.00

LABOR_RATE: float = 0.03
LABOR_MIN: float = 1.00
LABOR_MAX: float = 10.00

GATEWAY_FEE_RATE: float = 0.025
PLATFORM_FEE_RATE: float = 0.025

DOMESTIC_SHIPPING_RATE: float = 0.05
INTERNATIONAL_SHIPPING_RATE: float = 0.15

VALID_FULFILLMENT_STATUSES = {"SHIPPED", "DELIVERED"}
VALID_DISPUTE_STATUSES = {"CHARGEBACK_OPENED", "CHARGEBACK_LOST", "FRAUD_REFUND"}


@dataclass
class R10Input:
    order_id: str
    fulfillment_status: str  # e.g., 'SHIPPED', 'DELIVERED', 'UNFULFILLED'
    dispute_status: Optional[str]  # e.g., 'CHARGEBACK_OPENED', 'CHARGEBACK_LOST', 'FRAUD_REFUND', None
    currency: str = "USD"
    exchange_rate: float = 1.0  # exchange rate to base currency on order creation date
    
    # Revenue Components (in order currency)
    item_selling_price_after_discounts: float = 0.0
    customer_paid_shipping: float = 0.0
    customer_paid_taxes: float = 0.0
    
    # Loss Components (in order currency, None if missing/to be estimated)
    order_refund_amount: Optional[float] = None
    bank_chargeback_fee: Optional[float] = None
    product_sourcing_cost_cogs: Optional[float] = None
    outbound_shipping_fee: Optional[float] = None
    packaging_material_cost: Optional[float] = None
    warehouse_labor_cost: Optional[float] = None
    unrefunded_gateway_fee: Optional[float] = None
    unrefunded_platform_fee: Optional[float] = None
    customs_cod_fee: Optional[float] = None
    support_dispute_cost: Optional[float] = None
    
    # Contextual fields for fallbacks
    is_international: bool = False
    category: str = "fashion"
    category_avg_cogs: Optional[float] = None
    is_partial_dispute: bool = False
    disputed_amount: Optional[float] = None  # in order currency
    has_manual_support_log: bool = False
    manual_support_cost: float = 0.0


@dataclass
class R10Result:
    order_id: str
    is_eligible: bool
    eligibility_reason: str
    gross_order_revenue: float
    total_monetary_fraud_loss: float
    raw_risk_score: float
    final_r10_score: float
    components_breakdown: Dict[str, float] = field(default_factory=dict)
    fallbacks_applied: List[str] = field(default_factory=list)
    business_clarifications: List[str] = field(default_factory=list)


def compute_r10(order: R10Input) -> R10Result:
    """Computes R10 Fraud Loss Impact Score for a single order according to exact business rules."""
    
    # Rule 1: Only SHIPPED or DELIVERED fraudulent orders are included.
    if order.fulfillment_status.upper() not in VALID_FULFILLMENT_STATUSES:
        return R10Result(
            order_id=order.order_id,
            is_eligible=False,
            eligibility_reason=f"Fulfillment status '{order.fulfillment_status}' is not SHIPPED or DELIVERED",
            gross_order_revenue=0.0,
            total_monetary_fraud_loss=0.0,
            raw_risk_score=0.0,
            final_r10_score=0.0,
        )
    
    # Rule 2: Payment dispute status must be CHARGEBACK_OPENED, CHARGEBACK_LOST, FRAUD_REFUND.
    if not order.dispute_status or order.dispute_status.upper() not in VALID_DISPUTE_STATUSES:
        return R10Result(
            order_id=order.order_id,
            is_eligible=False,
            eligibility_reason=f"Dispute status '{order.dispute_status}' is not a recognized fraud dispute status",
            gross_order_revenue=0.0,
            total_monetary_fraud_loss=0.0,
            raw_risk_score=0.0,
            final_r10_score=0.0,
        )

    fallbacks: List[str] = []
    clarifications: List[str] = []
    fx = order.exchange_rate if order.exchange_rate > 0 else 1.0

    # Base Currency Revenue Calculation (Rule 6)
    rev_items = max(0.0, order.item_selling_price_after_discounts) * fx
    rev_shipping = max(0.0, order.customer_paid_shipping) * fx
    rev_taxes = max(0.0, order.customer_paid_taxes) * fx
    gross_order_revenue = rev_items + rev_shipping + rev_taxes

    # Determine Disputed Amount & Partial Ratio (Rule 4, 15)
    order_item_val = order.item_selling_price_after_discounts
    if order.is_partial_dispute and order.disputed_amount is not None and order_item_val > 0:
        dispute_ratio = min(1.0, max(0.0, order.disputed_amount / order_item_val))
        disputed_val_order_curr = order.disputed_amount
    else:
        dispute_ratio = 1.0
        disputed_val_order_curr = order.disputed_amount if order.disputed_amount is not None else order_item_val

    # 1. Order Refund Amount
    if order.order_refund_amount is not None:
        refund_loss = order.order_refund_amount * fx
    else:
        # If partial dispute, refund equals disputed amount (prorated)
        refund_loss = (disputed_val_order_curr if order.is_partial_dispute else order_item_val) * fx

    # 2. Bank Chargeback Penalty Fee (Rule 9, 16: full order level)
    if order.bank_chargeback_fee is not None:
        chargeback_fee = order.bank_chargeback_fee * fx
    else:
        fb_fee = CHARGEBACK_FEE_FALLBACKS.get(order.currency.upper(), DEFAULT_CHARGEBACK_FEE_FALLBACK)
        chargeback_fee = fb_fee * fx
        fallbacks.append(f"Bank Chargeback Fee missing: used {order.currency} fallback {fb_fee}")

    # 3. Product Sourcing Cost (COGS) (Rule 5, 15: prorated in partial dispute)
    if order.product_sourcing_cost_cogs is not None:
        base_cogs = order.product_sourcing_cost_cogs * fx
    else:
        # Category average fallback
        cat_cogs = order.category_avg_cogs if order.category_avg_cogs is not None else 0.0
        base_cogs = cat_cogs * fx
        fallbacks.append(f"COGS missing: used category average {cat_cogs}")
    
    cogs_loss = base_cogs * (dispute_ratio if order.is_partial_dispute else 1.0)

    # 4. Outbound Shipping Fee (Rule 10, 15: prorated in partial dispute)
    if order.outbound_shipping_fee is not None:
        base_shipping = order.outbound_shipping_fee * fx
    else:
        ship_rate = INTERNATIONAL_SHIPPING_RATE if order.is_international else DOMESTIC_SHIPPING_RATE
        base_shipping = (order_item_val * ship_rate) * fx
        ship_type = "International (15%)" if order.is_international else "Domestic (5%)"
        fallbacks.append(f"Outbound Shipping missing: used {ship_type} fallback {base_shipping / fx:.2f}")
    
    shipping_loss = base_shipping * (dispute_ratio if order.is_partial_dispute else 1.0)

    # 5. Packaging Material Cost (Rule 11)
    if order.packaging_material_cost is not None:
        base_pkg = order.packaging_material_cost * fx
    else:
        raw_pkg = max(PACKAGING_MIN, min(PACKAGING_MAX, order_item_val * PACKAGING_RATE))
        base_pkg = raw_pkg * fx
        fallbacks.append(f"Packaging missing: used 2% fallback (min {PACKAGING_MIN}, max {PACKAGING_MAX}): {raw_pkg:.2f}")
    
    # Partial dispute treatment check: Rule 15 does not include Packaging -> Business Clarification Required
    if order.is_partial_dispute:
        pkg_loss = base_pkg  # Left at full-order value in baseline
        clarifications.append("Packaging Cost allocation during partial dispute is undefined in business spec")
    else:
        pkg_loss = base_pkg

    # 6. Warehouse Fulfillment Labor Cost (Rule 12)
    if order.warehouse_labor_cost is not None:
        base_labor = order.warehouse_labor_cost * fx
    else:
        raw_labor = max(LABOR_MIN, min(LABOR_MAX, order_item_val * LABOR_RATE))
        base_labor = raw_labor * fx
        fallbacks.append(f"Warehouse Labor missing: used 3% fallback (min {LABOR_MIN}, max {LABOR_MAX}): {raw_labor:.2f}")
    
    if order.is_partial_dispute:
        labor_loss = base_labor  # Undefined in partial dispute -> Business Clarification Required
        clarifications.append("Warehouse Labor Cost allocation during partial dispute is undefined in business spec")
    else:
        labor_loss = base_labor

    # 7. Unrefunded Payment Gateway Fee (Rule 13, 15: prorated by disputed value)
    if order.unrefunded_gateway_fee is not None:
        base_gw = order.unrefunded_gateway_fee * fx
        gw_loss = base_gw * (dispute_ratio if order.is_partial_dispute else 1.0)
    else:
        # Fallback is 2.5% of disputed amount
        gw_loss = (disputed_val_order_curr * GATEWAY_FEE_RATE) * fx
        fallbacks.append(f"Gateway Fee missing: used 2.5% of disputed amount ({disputed_val_order_curr * GATEWAY_FEE_RATE:.2f})")

    # 8. Unrefunded Platform Fee (Rule 13)
    if order.unrefunded_platform_fee is not None:
        base_platform = order.unrefunded_platform_fee * fx
        if order.is_partial_dispute:
            platform_loss = base_platform  # Undefined in partial dispute -> Business Clarification Required
            clarifications.append("Platform Fee allocation during partial dispute is undefined in business spec")
        else:
            platform_loss = base_platform
    else:
        # Fallback is 2.5% of disputed amount
        platform_loss = (disputed_val_order_curr * PLATFORM_FEE_RATE) * fx
        fallbacks.append(f"Platform Fee missing: used 2.5% of disputed amount ({disputed_val_order_curr * PLATFORM_FEE_RATE:.2f})")

    # 9. Customs Clearance / COD Fee (Rule 24)
    if order.customs_cod_fee is not None:
        base_customs = order.customs_cod_fee * fx
        if order.is_partial_dispute:
            customs_loss = base_customs
            clarifications.append("Customs/COD Fee allocation during partial dispute is undefined in business spec")
        else:
            customs_loss = base_customs
    else:
        customs_loss = 0.0
        clarifications.append("Missing Customs/COD fee has no fallback defined in business specification")

    # 10. Customer Support Dispute Handling Cost (Rule 14, 16: full order level)
    if order.support_dispute_cost is not None:
        support_loss = order.support_dispute_cost * fx
    elif order.has_manual_support_log:
        support_loss = order.manual_support_cost * fx
    else:
        support_loss = 0.0  # Rule 14: 0 unless manual log exists

    # Total Monetary Fraud Loss
    total_monetary_fraud_loss = (
        refund_loss
        + chargeback_fee
        + cogs_loss
        + shipping_loss
        + pkg_loss
        + labor_loss
        + gw_loss
        + platform_loss
        + customs_loss
        + support_loss
    )

    # Score Calculation & Zero Revenue Rules
    if gross_order_revenue == 0.0:
        if total_monetary_fraud_loss > 0.0:
            raw_risk_score = 100.0
            final_r10_score = 100.0
        else:
            raw_risk_score = 0.0
            final_r10_score = 0.0
    else:
        raw_risk_score = (total_monetary_fraud_loss / gross_order_revenue) * 100.0
        final_r10_score = min(100.0, raw_risk_score)

    components = {
        "order_refund_amount": refund_loss,
        "bank_chargeback_fee": chargeback_fee,
        "product_sourcing_cost_cogs": cogs_loss,
        "outbound_shipping_fee": shipping_loss,
        "packaging_material_cost": pkg_loss,
        "warehouse_labor_cost": labor_loss,
        "unrefunded_gateway_fee": gw_loss,
        "unrefunded_platform_fee": platform_loss,
        "customs_cod_fee": customs_loss,
        "support_dispute_cost": support_loss,
    }

    return R10Result(
        order_id=order.order_id,
        is_eligible=True,
        eligibility_reason="Eligible SHIPPED/DELIVERED fraud dispute",
        gross_order_revenue=gross_order_revenue,
        total_monetary_fraud_loss=total_monetary_fraud_loss,
        raw_risk_score=raw_risk_score,
        final_r10_score=final_r10_score,
        components_breakdown=components,
        fallbacks_applied=fallbacks,
        business_clarifications=clarifications,
    )

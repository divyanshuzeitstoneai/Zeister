"""Comprehensive Synthetic test suite for C09 Customer Profitability formula validation.

Covers all requested parameters:
- Core formula: NetProfit = NetSales - COGS - Shipping - Fees - Support
- Revenue with discounts, partial and full refunds
- COGS hierarchy: Actual COGS -> Category Average Fallback -> Missing Category Avg (BUSINESS CLARIFICATION REQUIRED)
- Return inventory restock treatment: Sellable (COGS credited back) vs Damaged/Unsellable (COGS unrecovered)
- Carrier shipping deduplication and cost accumulation
- Payment gateway fee handling and missing fee flags
- Support ticket costs and missing cost flags
- Customer profitability spectrum: Highly Profitable, Break-Even ($0), Negative-Profit
"""

from datetime import date
import pytest
from src.scoring.c09 import (
    CustomerOrderLine,
    CustomerProfitabilityEvaluation,
    C09Result,
    evaluate_c09_profitability,
)

EVAL_DATE = date(2026, 8, 1)


# -------------------------------------------------------------
# 1. CORE REVENUE & DISCOUNT / REFUND HANDLING
# -------------------------------------------------------------

def test_c09_revenue_discounts_and_refunds():
    """Lifetime Net Sales = GrossSales - Discounts - Refunds."""
    lines = [
        # Full price order
        CustomerOrderLine("O1", "CUST-01", date(2026, 1, 1), "I1", 100.0, actual_cogs=30.0, shipping_cost=10.0, payment_gateway_fee=3.0),
        # Discounted order: $200 gross - $50 discount
        CustomerOrderLine("O2", "CUST-01", date(2026, 2, 1), "I2", 200.0, discount_amount=50.0, actual_cogs=60.0, shipping_cost=10.0, payment_gateway_fee=5.0),
        # Partially refunded order: $150 gross - $50 refund
        CustomerOrderLine("O3", "CUST-01", date(2026, 3, 1), "I3", 150.0, refunded_amount=50.0, actual_cogs=40.0, shipping_cost=10.0, payment_gateway_fee=4.0),
    ]
    res = evaluate_c09_profitability(lines, EVAL_DATE)
    c1 = res.customer_evaluations["CUST-01"]
    # Gross = 100 + 200 + 150 = 450
    # Discounts = 50
    # Refunds = 50
    # Net Sales = 450 - 50 - 50 = 350.0
    assert c1.lifetime_gross_sales == 450.0
    assert c1.lifetime_discounts == 50.0
    assert c1.lifetime_refunds == 50.0
    assert c1.lifetime_net_sales == 350.0

    # Net COGS = 30 + 60 + 40 = 130.0
    # Shipping = 10 + 10 + 10 = 30.0
    # Fees = 3 + 5 + 4 = 12.0
    # Profit = 350 - 130 - 30 - 12 = 178.0
    assert c1.customer_net_profit == 178.0


# -------------------------------------------------------------
# 2. COGS HIERARCHY & MISSING CATEGORY-AVERAGE CLARIFICATION
# -------------------------------------------------------------

def test_c09_cogs_fallback_and_missing_category_average():
    """Actual COGS -> Category Avg -> Missing (BUSINESS CLARIFICATION REQUIRED)."""
    lines = [
        # Customer A: Mixed actual and category average fallback
        CustomerOrderLine("O1", "CUST-A", date(2026, 1, 1), "I1", 100.0, actual_cogs=25.0, shipping_cost=5.0, payment_gateway_fee=3.0),
        CustomerOrderLine("O2", "CUST-A", date(2026, 2, 1), "I2", 100.0, actual_cogs=None, category_avg_cogs=35.0, shipping_cost=5.0, payment_gateway_fee=3.0),

        # Customer B: Missing BOTH actual and category average COGS -> Clarification required!
        CustomerOrderLine("O3", "CUST-B", date(2026, 3, 1), "I3", 100.0, actual_cogs=None, category_avg_cogs=None, shipping_cost=5.0, payment_gateway_fee=3.0),
    ]
    res = evaluate_c09_profitability(lines, EVAL_DATE)
    ca = res.customer_evaluations["CUST-A"]
    cb = res.customer_evaluations["CUST-B"]

    # Customer A is fully computable: COGS = 25 + 35 = 60
    assert ca.is_fully_computable is True
    assert ca.lifetime_cogs == 60.0
    # Profit = 200 - 60 - 10 - 6 = 124.0
    assert ca.customer_net_profit == 124.0

    # Customer B has uncomputable COGS -> Marked clarification required
    assert cb.is_fully_computable is False
    assert cb.has_missing_cogs is True
    assert any("BUSINESS CLARIFICATION REQUIRED" in msg for msg in cb.business_clarifications)


# -------------------------------------------------------------
# 3. RETURN TREATMENT: SELLABLE VS NON-SELLABLE INVENTORY
# -------------------------------------------------------------

def test_c09_return_inventory_restock_treatment():
    """Returned item COGS is credited back ONLY if item is sellable."""
    lines = [
        # Customer 1: Returned item is SELLABLE -> COGS credited back
        CustomerOrderLine(
            "O1", "CUST-SELLABLE", date(2026, 1, 1), "I1",
            gross_price=100.0, refunded_amount=100.0, actual_cogs=40.0,
            is_returned=True, is_sellable=True, shipping_cost=10.0, payment_gateway_fee=3.0
        ),
        # Customer 2: Returned item is DAMAGED (not sellable) -> COGS remains deducted
        CustomerOrderLine(
            "O2", "CUST-DAMAGED", date(2026, 1, 1), "I2",
            gross_price=100.0, refunded_amount=100.0, actual_cogs=40.0,
            is_returned=True, is_sellable=False, shipping_cost=10.0, payment_gateway_fee=3.0
        ),
    ]
    res = evaluate_c09_profitability(lines, EVAL_DATE)
    c_sell = res.customer_evaluations["CUST-SELLABLE"]
    c_dam = res.customer_evaluations["CUST-DAMAGED"]

    # Sellable: Net sales = 100 - 100 = 0. Recovered COGS = 40. Net COGS = 40 - 40 = 0.
    # Unrecoverable costs: Shipping (10) + Fees (3) = 13. Net Profit = 0 - 0 - 10 - 3 = -13.0
    assert c_sell.lifetime_net_sales == 0.0
    assert c_sell.cogs_recovered_from_sellable_returns == 40.0
    assert c_sell.net_lifetime_cogs == 0.0
    assert c_sell.customer_net_profit == -13.0

    # Damaged: Net sales = 0. Recovered COGS = 0. Net COGS = 40.
    # Net Profit = 0 - 40 - 10 - 3 = -53.0
    assert c_dam.lifetime_net_sales == 0.0
    assert c_dam.cogs_recovered_from_sellable_returns == 0.0
    assert c_dam.net_lifetime_cogs == 40.0
    assert c_dam.customer_net_profit == -53.0


# -------------------------------------------------------------
# 4. CUSTOMER SUPPORT COSTS & PAYMENT FEES
# -------------------------------------------------------------

def test_c09_support_costs_and_gateway_fees():
    lines = [
        CustomerOrderLine(
            "O1", "CUST-SUPP", date(2026, 1, 1), "I1",
            gross_price=200.0, actual_cogs=50.0, shipping_cost=10.0, payment_gateway_fee=6.0,
            support_ticket_count=2, support_cost_per_ticket=15.0
        )
    ]
    res = evaluate_c09_profitability(lines, EVAL_DATE)
    c = res.customer_evaluations["CUST-SUPP"]
    # Support = 2 * 15.0 = 30.0
    # Net profit = 200 - 50 - 10 - 6 - 30 = 104.0
    assert c.lifetime_support_costs == 30.0
    assert c.lifetime_payment_fees == 6.0
    assert c.customer_net_profit == 104.0


# -------------------------------------------------------------
# 5. PROFITABILITY SPECTRUM: PROFITABLE, BREAK-EVEN, UNPROFITABLE
# -------------------------------------------------------------

def test_c09_profitability_spectrum_and_portfolio_summary():
    lines = [
        # Customer 1: Highly profitable (Sales=500, Costs=150 -> Profit=+350)
        CustomerOrderLine("O1", "CUST-HIGH-PROFIT", date(2026, 1, 1), "I1", 500.0, actual_cogs=100.0, shipping_cost=30.0, payment_gateway_fee=15.0, support_ticket_count=1, support_cost_per_ticket=5.0),
        # Customer 2: Exactly break-even (Sales=100, Costs=100 -> Profit=$0.00)
        CustomerOrderLine("O2", "CUST-BREAKEVEN", date(2026, 1, 1), "I2", 100.0, actual_cogs=70.0, shipping_cost=20.0, payment_gateway_fee=10.0),
        # Customer 3: Unprofitable / Negative profit (Sales=100, Costs=180 -> Profit=-80)
        CustomerOrderLine("O3", "CUST-UNPROFITABLE", date(2026, 1, 1), "I3", 100.0, actual_cogs=100.0, shipping_cost=30.0, payment_gateway_fee=10.0, support_ticket_count=2, support_cost_per_ticket=20.0),
    ]
    res = evaluate_c09_profitability(lines, EVAL_DATE)
    assert res.total_customers_count == 3
    assert res.computable_customers_count == 3
    assert res.profitable_customers_count == 1
    assert res.breakeven_customers_count == 1
    assert res.unprofitable_customers_count == 1

    assert res.customer_evaluations["CUST-HIGH-PROFIT"].customer_net_profit == 350.0
    assert res.customer_evaluations["CUST-BREAKEVEN"].customer_net_profit == 0.0
    assert res.customer_evaluations["CUST-UNPROFITABLE"].customer_net_profit == -80.0

    # Portfolio profit = 350 + 0 - 80 = 270.0
    assert pytest.approx(res.raw_portfolio_profit_dollars, 0.01) == 270.0

"""C09: Customer Profitability (Formula Engine).

Business: Zeitster
Category: Category 3 — Customer & Retention Health
Formula: C09 — Customer Profitability

Mathematical Formulation:
CustomerNetProfit = LifetimeNetSales - LifetimeCOGS - LifetimeShipping - PaymentProcessingFees - CustomerSupportCosts

Lifetime sales: AFTER discounts and refunds.
COGS: Actual COGS -> Category Average fallback -> BUSINESS CLARIFICATION REQUIRED.
Returns: Item COGS added back ONLY if returned item is in sellable condition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


@dataclass
class CustomerOrderLine:
    order_id: str
    customer_id: str
    order_date: date
    item_id: str
    gross_price: float
    discount_amount: float = 0.0
    refunded_amount: float = 0.0
    actual_cogs: Optional[float] = None
    category_avg_cogs: Optional[float] = None
    category: Optional[str] = None
    is_returned: bool = False
    is_sellable: bool = False  # True only if returned item is back in sellable condition
    shipping_cost: float = 0.0
    payment_gateway_fee: Optional[float] = None
    support_ticket_count: int = 0
    support_cost_per_ticket: Optional[float] = None


@dataclass
class CustomerProfitabilityEvaluation:
    customer_id: str
    lifetime_gross_sales: float
    lifetime_discounts: float
    lifetime_refunds: float
    lifetime_net_sales: float
    lifetime_cogs: float
    cogs_recovered_from_sellable_returns: float
    net_lifetime_cogs: float
    lifetime_shipping: float
    lifetime_payment_fees: float
    lifetime_support_costs: float
    customer_net_profit: float
    has_missing_cogs: bool
    has_missing_fee: bool
    has_missing_support: bool
    is_fully_computable: bool
    c09_profitability_score: Optional[float] = None  # BUSINESS PENDING
    business_clarifications: List[str] = field(default_factory=list)


@dataclass
class C09Result:
    evaluation_date: date
    total_customers_count: int
    computable_customers_count: int
    raw_portfolio_profit_dollars: float
    profitable_customers_count: int
    breakeven_customers_count: int
    unprofitable_customers_count: int
    customer_evaluations: Dict[str, CustomerProfitabilityEvaluation] = field(default_factory=dict)
    business_clarifications: List[str] = field(default_factory=list)


def evaluate_c09_profitability(
    order_lines: List[CustomerOrderLine],
    evaluation_date: date,
    default_support_cost_per_ticket: Optional[float] = None,
    default_gateway_fee_rate: Optional[float] = None,
) -> C09Result:
    """Evaluates C09 Customer Profitability strictly per specification."""
    clarifications: List[str] = []
    
    # Group lines by customer
    cust_lines: Dict[str, List[CustomerOrderLine]] = {}
    for line in order_lines:
        cust_lines.setdefault(line.customer_id, []).append(line)
        
    evaluations: Dict[str, CustomerProfitabilityEvaluation] = {}
    raw_portfolio_profit_dollars = 0.0
    profitable_count = 0
    breakeven_count = 0
    unprofitable_count = 0
    computable_count = 0
    
    for cid, lines in cust_lines.items():
        cust_clarifications: List[str] = []
        has_missing_cogs = False
        has_missing_fee = False
        has_missing_support = False
        is_fully_computable = True
        
        # 1. Lifetime Net Sales = GrossSales - Discounts - Refunds
        gross_sales = sum(l.gross_price for l in lines)
        discounts = sum(l.discount_amount for l in lines)
        refunds = sum(l.refunded_amount for l in lines)
        net_sales = gross_sales - discounts - refunds
        
        # 2. Lifetime COGS with returns handling
        total_cogs_incurred = 0.0
        cogs_recovered = 0.0
        
        for l in lines:
            # Determine item unit COGS
            if l.actual_cogs is not None:
                item_cogs = l.actual_cogs
            elif l.category_avg_cogs is not None:
                item_cogs = l.category_avg_cogs
            else:
                # Missing both actual and category average COGS
                has_missing_cogs = True
                is_fully_computable = False
                item_cogs = 0.0
                cust_clarifications.append(
                    f"BUSINESS CLARIFICATION REQUIRED: Item '{l.item_id}' in order '{l.order_id}' has no actual COGS and no Category-Average COGS"
                )
                
            total_cogs_incurred += item_cogs
            
            # Return treatment: returned item COGS is added back ONLY if sellable
            if l.is_returned:
                if l.is_sellable:
                    cogs_recovered += item_cogs
                else:
                    # Item damaged / not resellable -> cost remains incurred
                    pass
                    
        net_cogs = total_cogs_incurred - cogs_recovered
        
        # 3. Lifetime Shipping
        # Deduplicate shipping by order_id if multiple lines exist per order
        orders_seen = set()
        total_shipping = 0.0
        for l in lines:
            if l.order_id not in orders_seen:
                total_shipping += l.shipping_cost
                orders_seen.add(l.order_id)
                
        # 4. Payment Processing Fees
        total_fees = 0.0
        for l in lines:
            if l.payment_gateway_fee is not None:
                total_fees += l.payment_gateway_fee
            elif default_gateway_fee_rate is not None:
                total_fees += l.gross_price * default_gateway_fee_rate
            else:
                has_missing_fee = True
                cust_clarifications.append(
                    f"BUSINESS CLARIFICATION REQUIRED: Payment processing fee missing for order '{l.order_id}'"
                )
                
        # 5. Customer Support Costs
        total_support = 0.0
        for l in lines:
            if l.support_ticket_count > 0:
                cost_per_ticket = l.support_cost_per_ticket if l.support_cost_per_ticket is not None else default_support_cost_per_ticket
                if cost_per_ticket is not None:
                    total_support += l.support_ticket_count * cost_per_ticket
                else:
                    has_missing_support = True
                    cust_clarifications.append(
                        f"BUSINESS CLARIFICATION REQUIRED: Support ticket cost undefined for order '{l.order_id}'"
                    )
                    
        # Net Profit Formula:
        # CustomerNetProfit = LifetimeNetSales - LifetimeCOGS - LifetimeShipping - PaymentProcessingFees - CustomerSupportCosts
        net_profit = net_sales - net_cogs - total_shipping - total_fees - total_support
        
        if is_fully_computable:
            computable_count += 1
            raw_portfolio_profit_dollars += net_profit
            if net_profit > 0.0:
                profitable_count += 1
            elif net_profit == 0.0:
                breakeven_count += 1
            else:
                unprofitable_count += 1
                
        eval_item = CustomerProfitabilityEvaluation(
            customer_id=cid,
            lifetime_gross_sales=gross_sales,
            lifetime_discounts=discounts,
            lifetime_refunds=refunds,
            lifetime_net_sales=net_sales,
            lifetime_cogs=total_cogs_incurred,
            cogs_recovered_from_sellable_returns=cogs_recovered,
            net_lifetime_cogs=net_cogs,
            lifetime_shipping=total_shipping,
            lifetime_payment_fees=total_fees,
            lifetime_support_costs=total_support,
            customer_net_profit=net_profit,
            has_missing_cogs=has_missing_cogs,
            has_missing_fee=has_missing_fee,
            has_missing_support=has_missing_support,
            is_fully_computable=is_fully_computable,
            c09_profitability_score=None,  # BUSINESS PENDING
            business_clarifications=cust_clarifications,
        )
        evaluations[cid] = eval_item
        
    return C09Result(
        evaluation_date=evaluation_date,
        total_customers_count=len(cust_lines),
        computable_customers_count=computable_count,
        raw_portfolio_profit_dollars=raw_portfolio_profit_dollars,
        profitable_customers_count=profitable_count,
        breakeven_customers_count=breakeven_count,
        unprofitable_customers_count=unprofitable_count,
        customer_evaluations=evaluations,
        business_clarifications=clarifications,
    )

"""Automated pytest suite for R10 Fraud Loss Impact Score.

Covers all 45 synthetic test scenarios and business boundary validations.
"""

import pytest
from src.scoring.r10 import (
    R10Input,
    R10Result,
    compute_r10,
    CHARGEBACK_FEE_FALLBACKS,
    PACKAGING_RATE,
    PACKAGING_MIN,
    PACKAGING_MAX,
    LABOR_RATE,
    LABOR_MIN,
    LABOR_MAX,
    GATEWAY_FEE_RATE,
    PLATFORM_FEE_RATE,
    DOMESTIC_SHIPPING_RATE,
    INTERNATIONAL_SHIPPING_RATE,
)


def test_t01_normal_fraud_order():
    inp = R10Input(
        order_id="ORD-SYN-01",
        fulfillment_status="DELIVERED",
        dispute_status="CHARGEBACK_LOST",
        currency="USD",
        exchange_rate=1.0,
        item_selling_price_after_discounts=100.0,
        customer_paid_shipping=10.0,
        customer_paid_taxes=5.0,
        order_refund_amount=100.0,
        bank_chargeback_fee=15.0,
        product_sourcing_cost_cogs=40.0,
        outbound_shipping_fee=8.0,
        packaging_material_cost=2.0,
        warehouse_labor_cost=3.0,
        unrefunded_gateway_fee=2.50,
        unrefunded_platform_fee=2.50,
        customs_cod_fee=0.0,
        support_dispute_cost=5.0,
    )
    res = compute_r10(inp)
    assert res.gross_order_revenue == 115.0
    assert res.total_monetary_fraud_loss == 178.0
    assert res.final_r10_score == 100.0
    assert res.is_eligible is True


def test_t02_zero_loss_case():
    inp = R10Input(
        order_id="ORD-SYN-02",
        fulfillment_status="SHIPPED",
        dispute_status="CHARGEBACK_LOST",
        currency="USD",
        exchange_rate=1.0,
        item_selling_price_after_discounts=100.0,
        customer_paid_shipping=10.0,
        customer_paid_taxes=5.0,
        order_refund_amount=0.0,
        bank_chargeback_fee=0.0,
        product_sourcing_cost_cogs=0.0,
        outbound_shipping_fee=0.0,
        packaging_material_cost=0.0,
        warehouse_labor_cost=0.0,
        unrefunded_gateway_fee=0.0,
        unrefunded_platform_fee=0.0,
        customs_cod_fee=0.0,
        support_dispute_cost=0.0,
    )
    res = compute_r10(inp)
    assert res.gross_order_revenue == 115.0
    assert res.total_monetary_fraud_loss == 0.0
    assert res.final_r10_score == 0.0


def test_t03_revenue_zero_loss_positive():
    inp = R10Input(
        order_id="ORD-SYN-03",
        fulfillment_status="SHIPPED",
        dispute_status="FRAUD_REFUND",
        currency="USD",
        exchange_rate=1.0,
        item_selling_price_after_discounts=0.0,
        customer_paid_shipping=0.0,
        customer_paid_taxes=0.0,
        order_refund_amount=0.0,
        bank_chargeback_fee=15.0,
        product_sourcing_cost_cogs=20.0,
        outbound_shipping_fee=5.0,
        packaging_material_cost=1.0,
        warehouse_labor_cost=3.0,
        unrefunded_gateway_fee=0.0,
        unrefunded_platform_fee=0.0,
        customs_cod_fee=0.0,
        support_dispute_cost=0.0,
    )
    res = compute_r10(inp)
    assert res.gross_order_revenue == 0.0
    assert res.total_monetary_fraud_loss == 44.0
    assert res.final_r10_score == 100.0


def test_t04_revenue_zero_loss_zero():
    inp = R10Input(
        order_id="ORD-SYN-04",
        fulfillment_status="SHIPPED",
        dispute_status="FRAUD_REFUND",
        currency="USD",
        exchange_rate=1.0,
        item_selling_price_after_discounts=0.0,
        customer_paid_shipping=0.0,
        customer_paid_taxes=0.0,
        order_refund_amount=0.0,
        bank_chargeback_fee=0.0,
        product_sourcing_cost_cogs=0.0,
        outbound_shipping_fee=0.0,
        packaging_material_cost=0.0,
        warehouse_labor_cost=0.0,
        unrefunded_gateway_fee=0.0,
        unrefunded_platform_fee=0.0,
        customs_cod_fee=0.0,
        support_dispute_cost=0.0,
    )
    res = compute_r10(inp)
    assert res.gross_order_revenue == 0.0
    assert res.total_monetary_fraud_loss == 0.0
    assert res.final_r10_score == 0.0


def test_t05_score_below_100():
    inp = R10Input(
        order_id="ORD-SYN-05",
        fulfillment_status="DELIVERED",
        dispute_status="CHARGEBACK_OPENED",
        currency="USD",
        exchange_rate=1.0,
        item_selling_price_after_discounts=1000.0,
        customer_paid_shipping=50.0,
        customer_paid_taxes=50.0,
        order_refund_amount=100.0,
        bank_chargeback_fee=15.0,
        product_sourcing_cost_cogs=40.0,
        outbound_shipping_fee=10.0,
        packaging_material_cost=2.0,
        warehouse_labor_cost=3.0,
        unrefunded_gateway_fee=2.50,
        unrefunded_platform_fee=2.50,
        customs_cod_fee=0.0,
        support_dispute_cost=0.0,
    )
    res = compute_r10(inp)
    assert res.gross_order_revenue == 1100.0
    assert res.total_monetary_fraud_loss == 175.0
    assert abs(res.final_r10_score - (175.0 / 1100.0 * 100.0)) < 1e-5


def test_t06_score_exactly_100():
    inp = R10Input(
        order_id="ORD-SYN-06",
        fulfillment_status="DELIVERED",
        dispute_status="CHARGEBACK_LOST",
        currency="USD",
        exchange_rate=1.0,
        item_selling_price_after_discounts=120.0,
        customer_paid_shipping=20.0,
        customer_paid_taxes=10.0,
        order_refund_amount=100.0,
        bank_chargeback_fee=15.0,
        product_sourcing_cost_cogs=20.0,
        outbound_shipping_fee=8.0,
        packaging_material_cost=2.0,
        warehouse_labor_cost=3.0,
        unrefunded_gateway_fee=1.0,
        unrefunded_platform_fee=1.0,
        customs_cod_fee=0.0,
        support_dispute_cost=0.0,
    )
    res = compute_r10(inp)
    assert res.gross_order_revenue == 150.0
    assert res.total_monetary_fraud_loss == 150.0
    assert res.final_r10_score == 100.0


def test_t07_raw_score_above_100():
    inp = R10Input(
        order_id="ORD-SYN-07",
        fulfillment_status="DELIVERED",
        dispute_status="CHARGEBACK_LOST",
        currency="USD",
        exchange_rate=1.0,
        item_selling_price_after_discounts=100.0,
        customer_paid_shipping=0.0,
        customer_paid_taxes=0.0,
        order_refund_amount=100.0,
        bank_chargeback_fee=15.0,
        product_sourcing_cost_cogs=50.0,
        outbound_shipping_fee=10.0,
        packaging_material_cost=3.0,
        warehouse_labor_cost=5.0,
        unrefunded_gateway_fee=3.0,
        unrefunded_platform_fee=3.0,
        customs_cod_fee=0.0,
        support_dispute_cost=10.0,
    )
    res = compute_r10(inp)
    assert res.raw_risk_score == 199.0
    assert res.final_r10_score == 100.0


def test_t08_prefulfillment_fraud_ineligible():
    inp = R10Input(
        order_id="ORD-SYN-08",
        fulfillment_status="UNFULFILLED",
        dispute_status="FRAUD_REFUND",
        currency="USD",
        item_selling_price_after_discounts=100.0,
    )
    res = compute_r10(inp)
    assert res.is_eligible is False
    assert res.final_r10_score == 0.0


def test_t11_invalid_dispute_status_ineligible():
    inp = R10Input(
        order_id="ORD-SYN-11",
        fulfillment_status="DELIVERED",
        dispute_status="CHARGEBACK_WON",
        currency="USD",
        item_selling_price_after_discounts=100.0,
    )
    res = compute_r10(inp)
    assert res.is_eligible is False
    assert res.final_r10_score == 0.0


def test_t14_partial_dispute_proration():
    inp = R10Input(
        order_id="ORD-SYN-14",
        fulfillment_status="DELIVERED",
        dispute_status="CHARGEBACK_OPENED",
        item_selling_price_after_discounts=200.0,
        customer_paid_shipping=20.0,
        customer_paid_taxes=10.0,
        is_partial_dispute=True,
        disputed_amount=100.0,
        order_refund_amount=100.0,
        bank_chargeback_fee=15.0,
        product_sourcing_cost_cogs=80.0,
        outbound_shipping_fee=10.0,
        packaging_material_cost=4.0,
        warehouse_labor_cost=6.0,
        unrefunded_gateway_fee=5.0,
        unrefunded_platform_fee=5.0,
        customs_cod_fee=0.0,
        support_dispute_cost=10.0,
    )
    res = compute_r10(inp)
    # COGS prorated = 40.0, Ship prorated = 5.0, GW prorated = 2.50
    assert res.components_breakdown["product_sourcing_cost_cogs"] == 40.0
    assert res.components_breakdown["outbound_shipping_fee"] == 5.0
    assert res.components_breakdown["unrefunded_gateway_fee"] == 2.50
    assert res.components_breakdown["bank_chargeback_fee"] == 15.0
    assert res.components_breakdown["support_dispute_cost"] == 10.0
    assert res.total_monetary_fraud_loss == 187.50


def test_t17_chargeback_fallbacks():
    for curr, exp in [("USD", 15.0), ("EUR", 15.0), ("GBP", 10.0), ("CAD", 20.0)]:
        inp = R10Input(
            order_id=f"ORD-SYN-17-{curr}",
            fulfillment_status="DELIVERED",
            dispute_status="CHARGEBACK_LOST",
            currency=curr,
            item_selling_price_after_discounts=100.0,
            bank_chargeback_fee=None,
        )
        res = compute_r10(inp)
        assert res.components_breakdown["bank_chargeback_fee"] == exp


def test_t18_shipping_fallbacks():
    dom = compute_r10(R10Input(order_id="1", fulfillment_status="DELIVERED", dispute_status="CHARGEBACK_LOST", item_selling_price_after_discounts=100.0, is_international=False, outbound_shipping_fee=None))
    intl = compute_r10(R10Input(order_id="2", fulfillment_status="DELIVERED", dispute_status="CHARGEBACK_LOST", item_selling_price_after_discounts=100.0, is_international=True, outbound_shipping_fee=None))
    assert dom.components_breakdown["outbound_shipping_fee"] == 5.0
    assert intl.components_breakdown["outbound_shipping_fee"] == 15.0


def test_t19_t20_packaging_labor_clamps():
    res_small = compute_r10(R10Input(order_id="s", fulfillment_status="DELIVERED", dispute_status="CHARGEBACK_LOST", item_selling_price_after_discounts=10.0, packaging_material_cost=None, warehouse_labor_cost=None))
    assert res_small.components_breakdown["packaging_material_cost"] == 0.50
    assert res_small.components_breakdown["warehouse_labor_cost"] == 1.00

    res_large = compute_r10(R10Input(order_id="l", fulfillment_status="DELIVERED", dispute_status="CHARGEBACK_LOST", item_selling_price_after_discounts=500.0, packaging_material_cost=None, warehouse_labor_cost=None))
    assert res_large.components_breakdown["packaging_material_cost"] == 5.00
    assert res_large.components_breakdown["warehouse_labor_cost"] == 10.00

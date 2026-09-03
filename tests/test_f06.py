"""tests/test_f06.py — Comprehensive Test Suite for F06 Payment Fee Leakage Score.

Covers all 6 required edge-case types from the specification:
  1. Normal Case (Standard Card): Clean baseline, fee ≈ benchmark, near-zero leakage
  2. Boundary Case: Fee exactly equal to benchmark (0 leakage, not negative)
  3. Missing actual_gateway_fee (no fallback allowed): Must resolve Unresolved, NEVER silently 0
  4. Missing benchmark metafield: Falls back to industry default (2.9% + $0.30), flagged is_benchmark_estimated
  5. BNPL / High-Cost Method: Real leakage case, exactly matches worked calculation trace ($50 order, $3.30 fee -> $1.55 leakage, 53.0% efficiency)
  6. Unclassifiable Payment Method: Leakage still computed, payment_method = "Unknown", attribution flagged separately

Additional tests:
  7. Negative variance (savings): Fee below benchmark -> variance < 0, leakage clamped to 0.0
  8. International Card: High-cost intl card handling
  9. Transaction join: paymentDetails & gateway joined from transactions table
  10. Aggregation & Portfolio Breakdown: storewide rollup, leakage by method, unresolved exclusion
"""

import numpy as np
import pandas as pd
import pytest

from src.scoring.f06 import compute_f06, aggregate_f06, classify_payment_method, get_standard_benchmark_fee


# =====================================================================
# 1. NORMAL CASE (Standard Card)
# =====================================================================
def test_f06_case1_normal_standard_card():
    """Clean baseline order with standard credit card. Fee matches standard 2.9% + $0.30."""
    # Order: $100.00, Standard Card fee = 100 * 0.029 + 0.30 = $3.20
    df_orders = pd.DataFrame([{
        "order_id": "ORD-NORM-01",
        "net_sales": 100.00,
        "gateway_fee": 3.20,
        "payment_method_name": "Visa",
        "gateway_name": "shopify_payments",
    }])

    res = compute_f06(df_orders, standard_fee_pct=0.029, standard_fixed_fee=0.30)
    
    assert res.loc[0, "f06_status"] == "Efficient"
    assert res.loc[0, "payment_method_category"] == "Card"
    assert bool(res.loc[0, "is_method_known"]) is True
    assert res.loc[0, "standard_benchmark_fee"] == 3.20
    assert res.loc[0, "fee_variance"] == pytest.approx(0.0, abs=0.01)
    assert res.loc[0, "f06_leakage"] == 0.0
    assert res.loc[0, "fee_efficiency_pct"] == pytest.approx(100.0, abs=0.1)


# =====================================================================
# 2. BOUNDARY CASE (Fee exactly equals benchmark)
# =====================================================================
def test_f06_case2_boundary_exact_match():
    """Boundary condition: Actual gateway fee matches benchmark to the exact penny."""
    # Order: $200.00, Benchmark: 200 * 0.029 + 0.30 = $6.10
    df_orders = pd.DataFrame([{
        "order_id": "ORD-BOUND-01",
        "net_sales": 200.00,
        "gateway_fee": 6.10,
        "payment_method_name": "Mastercard",
        "gateway_name": "shopify_payments",
    }])

    res = compute_f06(df_orders, standard_fee_pct=0.029, standard_fixed_fee=0.30)

    assert res.loc[0, "f06_status"] == "Efficient"
    assert res.loc[0, "standard_benchmark_fee"] == 6.10
    assert res.loc[0, "fee_variance"] == 0.0
    assert res.loc[0, "f06_leakage"] == 0.0
    assert res.loc[0, "fee_efficiency_pct"] == pytest.approx(100.0)


# =====================================================================
# 3. MISSING actual_gateway_fee (Must resolve Unresolved, NEVER 0)
# =====================================================================
def test_f06_case3_missing_actual_gateway_fee_unresolved():
    """Critical rule: Missing actual fee must resolve to 'Unresolved', NOT silently 0."""
    df_orders = pd.DataFrame([
        {
            "order_id": "ORD-NULL-01",
            "net_sales": 150.00,
            "gateway_fee": np.nan,  # Offline/manual order or missing fee
            "payment_method_name": "Cash on Delivery",
            "gateway_name": "manual",
        },
        {
            "order_id": "ORD-NULL-02",
            "net_sales": 75.00,
            "gateway_fee": None,
            "payment_method_name": None,
            "gateway_name": None,
        }
    ])

    res = compute_f06(df_orders)

    assert res.loc[0, "f06_status"] == "Unresolved"
    assert pd.isna(res.loc[0, "fee_variance"])
    assert pd.isna(res.loc[0, "f06_leakage"])
    assert pd.isna(res.loc[0, "fee_efficiency_pct"])

    assert res.loc[1, "f06_status"] == "Unresolved"
    assert pd.isna(res.loc[1, "f06_leakage"])

    # Aggregation must exclude unresolved orders from leakage sums
    agg = aggregate_f06(res)
    assert agg["orders_evaluated"] == 0
    assert agg["orders_unresolved"] == 2
    assert agg["total_leakage"] == 0.0


# =====================================================================
# 4. MISSING BENCHMARK METAFIELD (Fallback with estimation flag)
# =====================================================================
def test_f06_case4_missing_benchmark_metafield_fallback():
    """When merchant has no custom benchmark metafield, fall back to 2.9% + $0.30 and flag."""
    df_orders = pd.DataFrame([{
        "order_id": "ORD-FB-01",
        "net_sales": 100.00,
        "gateway_fee": 4.00,
        "payment_method_name": "Visa",
    }])

    # No standard_fee_pct or standard_fixed_fee passed -> triggers default fallback
    res = compute_f06(df_orders, standard_fee_pct=None, standard_fixed_fee=None)

    assert res.loc[0, "standard_benchmark_fee"] == 3.20  # (100 * 0.029) + 0.30
    assert bool(res.loc[0, "is_benchmark_estimated"]) is True
    assert bool(res.loc[0, "is_fee_estimated"]) is True
    assert res.loc[0, "fee_variance"] == pytest.approx(0.80)
    assert res.loc[0, "f06_leakage"] == pytest.approx(0.80)


# =====================================================================
# 5. BNPL / HIGH-COST METHOD (Matches worked calculation trace)
# =====================================================================
def test_f06_case5_bnpl_worked_example_calculation_trace():
    """Worked example from specification:
    Order Amount = $50.00, Actual Fee (BNPL) = $3.30
    Standard Benchmark Fee = ($50.00 × 0.029) + $0.30 = $1.75
    Fee Variance = $3.30 − $1.75 = +$1.55 (Leakage)
    Normalized Fee Efficiency = ($1.75 / $3.30) × 100 = 53.0% (Overpaying ~47%)
    """
    df_orders = pd.DataFrame([{
        "order_id": "ORD-BNPL-TRACE",
        "net_sales": 50.00,
        "gateway_fee": 3.30,
        "payment_method_name": "Shop Pay Installments",
        "gateway_name": "shop_pay_installments",
    }])

    res = compute_f06(df_orders, standard_fee_pct=0.029, standard_fixed_fee=0.30)

    assert res.loc[0, "payment_method_category"] == "BNPL"
    assert res.loc[0, "standard_benchmark_fee"] == 1.75
    assert res.loc[0, "fee_variance"] == pytest.approx(1.55, abs=0.01)
    assert res.loc[0, "f06_leakage"] == pytest.approx(1.55, abs=0.01)
    # Fee Efficiency Score = 1.75 / 3.30 * 100 = 53.03%
    assert res.loc[0, "fee_efficiency_pct"] == pytest.approx(53.03, abs=0.1)
    assert res.loc[0, "f06_status"] == "Leaking"


# =====================================================================
# 6. UNCLASSIFIABLE PAYMENT METHOD (Unknown attribution)
# =====================================================================
def test_f06_case6_unclassifiable_payment_method():
    """Unclassifiable payment details: Leakage still computed against standard benchmark,
    tagged as payment_method = 'Unknown' and is_method_known = False."""
    df_orders = pd.DataFrame([{
        "order_id": "ORD-UNK-01",
        "net_sales": 100.00,
        "gateway_fee": 5.00,
        "payment_method_name": None,
        "gateway_name": "unrecognized_custom_gateway_xyz",
    }])

    res = compute_f06(df_orders, standard_fee_pct=0.029, standard_fixed_fee=0.30)

    assert res.loc[0, "payment_method_category"] == "Unknown"
    assert bool(res.loc[0, "is_method_known"]) is False
    assert res.loc[0, "standard_benchmark_fee"] == 3.20
    assert res.loc[0, "fee_variance"] == pytest.approx(1.80)
    assert res.loc[0, "f06_leakage"] == pytest.approx(1.80)
    assert res.loc[0, "f06_status"] == "Leaking"


# =====================================================================
# 7. NEGATIVE VARIANCE / SAVINGS (Fee below benchmark)
# =====================================================================
def test_f06_savings_negative_variance_not_counted_as_leakage():
    """Fee below benchmark: Fee variance is negative (savings), but leakage must be max(0, var) = 0.0."""
    # Order: $100.00, Benchmark = $3.20. Negotiated actual fee = $2.50
    df_orders = pd.DataFrame([{
        "order_id": "ORD-SAVE-01",
        "net_sales": 100.00,
        "gateway_fee": 2.50,
        "payment_method_name": "Visa",
    }])

    res = compute_f06(df_orders, standard_fee_pct=0.029, standard_fixed_fee=0.30)

    assert res.loc[0, "fee_variance"] == pytest.approx(-0.70)
    assert res.loc[0, "f06_leakage"] == 0.0  # max(0, -0.70)
    assert res.loc[0, "f06_status"] == "Efficient"
    # Efficiency is 3.20 / 2.50 * 100 = 128.0% (better than baseline)
    assert res.loc[0, "fee_efficiency_pct"] == pytest.approx(128.0)


# =====================================================================
# 8. INTERNATIONAL CARD DETECTION
# =====================================================================
def test_f06_international_card_detection():
    """Flag is_international_card sets category to IntlCard."""
    df_orders = pd.DataFrame([{
        "order_id": "ORD-INTL-01",
        "net_sales": 100.00,
        "gateway_fee": 4.80,
        "payment_method_name": "Visa",
        "is_international_card": True,
    }])

    res = compute_f06(df_orders, standard_fee_pct=0.029, standard_fixed_fee=0.30)

    assert res.loc[0, "payment_method_category"] == "IntlCard"
    assert res.loc[0, "standard_benchmark_fee"] == 3.20
    assert res.loc[0, "f06_leakage"] == pytest.approx(1.60)


# =====================================================================
# 9. TRANSACTIONS TABLE JOIN
# =====================================================================
def test_f06_join_with_transactions_table():
    """Verify join when payment details come from separate df_transactions table."""
    df_orders = pd.DataFrame([{
        "order_id": "ORD-JOIN-01",
        "net_sales": 80.00,
        "gateway_fee": 5.10,
    }])
    df_tx = pd.DataFrame([{
        "transaction_id": "TX-01",
        "order_id": "ORD-JOIN-01",
        "payment_method_name": "Klarna",
        "gateway_name": "klarna",
    }])

    res = compute_f06(df_orders, df_transactions=df_tx, standard_fee_pct=0.029, standard_fixed_fee=0.30)

    assert res.loc[0, "payment_method_category"] == "BNPL"
    # Benchmark: 80 * 0.029 + 0.30 = 2.62
    assert res.loc[0, "standard_benchmark_fee"] == 2.62
    assert res.loc[0, "f06_leakage"] == pytest.approx(5.10 - 2.62)


# =====================================================================
# 10. STOREWIDE AGGREGATION & BREAKDOWN
# =====================================================================
def test_f06_aggregation_and_breakdown():
    """Test full storewide aggregation across mixed payment methods and statuses."""
    df_orders = pd.DataFrame([
        # 1. Normal Visa: $100, fee $3.20, bm $3.20 -> 0 leakage
        {"order_id": "O1", "net_sales": 100.0, "gateway_fee": 3.20, "payment_method_name": "Visa"},
        # 2. BNPL: $50, fee $3.30, bm $1.75 -> $1.55 leakage
        {"order_id": "O2", "net_sales": 50.0, "gateway_fee": 3.30, "payment_method_name": "Afterpay"},
        # 3. Savings: $100, fee $2.50, bm $3.20 -> -$0.70 variance, 0 leakage
        {"order_id": "O3", "net_sales": 100.0, "gateway_fee": 2.50, "payment_method_name": "Visa"},
        # 4. Unresolved: $100, fee null -> excluded
        {"order_id": "O4", "net_sales": 100.0, "gateway_fee": np.nan, "payment_method_name": "Manual"},
    ])

    scored = compute_f06(df_orders, standard_fee_pct=0.029, standard_fixed_fee=0.30)
    agg = aggregate_f06(scored)

    assert agg["orders_evaluated"] == 3
    assert agg["orders_unresolved"] == 1
    assert agg["orders_leaking"] == 1
    assert agg["orders_efficient"] == 2
    assert agg["total_leakage"] == pytest.approx(1.55, abs=0.01)
    assert agg["total_savings"] == pytest.approx(-0.70, abs=0.01)
    assert agg["net_fee_position"] == pytest.approx(1.55 - 0.70, abs=0.01)
    assert "BNPL" in agg["leakage_by_method"]
    assert agg["leakage_by_method"]["BNPL"]["orders_leaking"] == 1
    assert agg["leakage_by_method"]["BNPL"]["total_leakage"] == pytest.approx(1.55, abs=0.01)

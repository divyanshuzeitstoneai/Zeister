"""tests/test_normalization_rules.py — Validation of F05, F09, F10 normalization and direction invariants."""

import numpy as np
import pandas as pd
import pytest

from src.scoring.f05 import compute_f05, compute_f05_normalized_score
from src.scoring.f09 import compute_f09, compute_f09_normalized_score
from src.scoring.f10 import compute_f10, compute_f10_normalized_score


# ===========================================================================
# PART 1 — F05 NORMALIZATION TESTS
# ===========================================================================

def test_f05_reference_examples():
    """Reference cases from business specification:
    1. Customer pays 10, courier = 10 -> score = 100
    2. Customer pays 5, courier = 10 -> score = 50
    3. Customer pays 0, courier = 10 -> score = 0
    """
    assert compute_f05_normalized_score(10.0, 10.0) == pytest.approx(100.0)
    assert compute_f05_normalized_score(5.0, 10.0) == pytest.approx(50.0)
    assert compute_f05_normalized_score(0.0, 10.0) == pytest.approx(0.0)


def test_f05_edge_cases():
    """F05 Edge cases:
    - F05-A: Customer = 15, Courier = 10 -> Raw produces 150.0 (uncapped)
    - F05-B: Customer = 0, Courier = 0 -> Safe division-by-zero handling produces 100.0
    - F05-C: Customer = 2, Courier = 10 -> 20.0
    - F05-D: Customer = 0, Courier = 25 -> 0.0
    """
    # F05-A
    assert compute_f05_normalized_score(15.0, 10.0) == pytest.approx(150.0)
    # F05-B
    assert compute_f05_normalized_score(0.0, 0.0) == pytest.approx(100.0)
    # F05-C
    assert compute_f05_normalized_score(2.0, 10.0) == pytest.approx(20.0)
    # F05-D
    assert compute_f05_normalized_score(0.0, 25.0) == pytest.approx(0.0)


def test_f05_dataframe_vectorized_normalization():
    """Verify compute_f05 returns shipping_recovery_score_pct across a dataframe."""
    df = pd.DataFrame({
        "order_id": ["O1", "O2", "O3", "O4", "O5"],
        "shipping_charged_to_customer": [10.0, 5.0, 0.0, 15.0, 0.0],
        "actual_shipping_cost": [10.0, 10.0, 10.0, 10.0, 0.0],
    })
    res = compute_f05(df)
    assert res["shipping_recovery_score_pct"].tolist() == pytest.approx([100.0, 50.0, 0.0, 150.0, 100.0])


# ===========================================================================
# PART 2 — F09 NORMALIZATION TESTS
# ===========================================================================

def test_f09_reference_examples():
    """Reference cases from business specification:
    1. Marketplace = 20, Website = 20 -> 100
    2. Marketplace = 10, Website = 20 -> 50
    3. Marketplace = 0, Website = 20 -> 0
    """
    assert compute_f09_normalized_score(20.0, 20.0) == pytest.approx(100.0)
    assert compute_f09_normalized_score(10.0, 20.0) == pytest.approx(50.0)
    assert compute_f09_normalized_score(0.0, 20.0) == pytest.approx(0.0)


def test_f09_edge_cases():
    """F09 Edge cases:
    - F09-A: Marketplace = 25, Website = 20 -> 125.0
    - F09-B: Marketplace = 10, Website = 0 -> 0.0 (safe fallback)
    - F09-C: Marketplace = 0, Website = 0 -> 100.0 (equal parity at zero profit)
    - F09-D: Marketplace = -5, Website = 20 -> -25.0
    - F09-E: Marketplace = 5, Website = -10 -> -50.0
    """
    # F09-A
    assert compute_f09_normalized_score(25.0, 20.0) == pytest.approx(125.0)
    # F09-B
    assert compute_f09_normalized_score(10.0, 0.0) == pytest.approx(0.0)
    # F09-C
    assert compute_f09_normalized_score(0.0, 0.0) == pytest.approx(100.0)
    # F09-D
    assert compute_f09_normalized_score(-5.0, 20.0) == pytest.approx(-25.0)
    # F09-E
    assert compute_f09_normalized_score(5.0, -10.0) == pytest.approx(-50.0)


def test_f09_compute_integration_normalized_score():
    """Verify compute_f09 populates normalized_score in channel breakdown."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-AMZ"],
        "channel": ["web", "amazon"],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-WEB", "ORD-AMZ"],
        "quantity": [1, 1],
        "net_selling_price": [100.0, 100.0],
        "cogs_total": [50.0, 50.0],
        "channel_fee_pct": [0.0, 0.20],  # Web unit profit = 50, Amazon unit profit = 30
        "is_returned": [False, False],
    })
    res = compute_f09(df_orders, df_items, primary_channel="web")
    # Amazon score = 30 / 50 * 100 = 60.0
    assert res["channel_breakdown"]["AMAZON"]["normalized_score"] == pytest.approx(60.0)


# ===========================================================================
# PART 3 — F10 NORMALIZATION TESTS
# ===========================================================================

def test_f10_normalization_cases():
    """F10 Normalization tests:
    - F10-A: 30% net profit (Net = 30, Price = 100) -> 30.0
    - F10-B: 10% net profit (Net = 10, Price = 100) -> 10.0
    - F10-C: Break-even (Net = 0, Price = 100) -> 0.0
    - F10-D: Loss-making product (Net = -5, Price = 100) -> Capped at 0.0
    - F10-E: Price paid = 0 subcases (Case A: 0/0, Case B: -10/0, Case C: 10/0) -> 0.0
    - F10-F: Net profit > price paid (Net = 120, Price = 100) -> 120.0 (uncapped)
    - F10-G: Negative net profit (Net = -20, Price = 200) -> Capped at 0.0
    """
    # F10-A
    assert compute_f10_normalized_score(30.0, 100.0) == pytest.approx(30.0)
    # F10-B
    assert compute_f10_normalized_score(10.0, 100.0) == pytest.approx(10.0)
    # F10-C
    assert compute_f10_normalized_score(0.0, 100.0) == pytest.approx(0.0)
    # F10-D
    assert compute_f10_normalized_score(-5.0, 100.0) == pytest.approx(0.0)
    # F10-E: Price paid = 0 subcases (Case A: 0/0, Case B: -10/0, Case C: 10/0)
    assert compute_f10_normalized_score(0.0, 0.0) == pytest.approx(0.0)
    assert compute_f10_normalized_score(-10.0, 0.0) == pytest.approx(0.0)
    assert compute_f10_normalized_score(10.0, 0.0) == pytest.approx(0.0)
    # F10-F
    assert compute_f10_normalized_score(120.0, 100.0) == pytest.approx(120.0)
    # F10-G
    assert compute_f10_normalized_score(-20.0, 200.0) == pytest.approx(0.0)


def test_f10_dataframe_normalized_score_column():
    """Verify compute_f10 creates normalized_contribution_score capped at 0."""
    df_orders = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "actual_shipping_cost": [10.0, 10.0],
        "gateway_fee": [2.0, 2.0],
        "is_cancelled": [False, False],
    })
    df_items = pd.DataFrame({
        "order_id": ["ORD-1", "ORD-2"],
        "product_id": ["SKU-PROFIT", "SKU-LOSS"],
        "quantity": [1, 1],
        "selling_price": [100.0, 100.0],
        "net_selling_price": [100.0, 100.0],
        "cogs_total": [50.0, 120.0],  # SKU-PROFIT contrib = 38 (38%), SKU-LOSS contrib = -32 (-32%)
        "is_returned": [False, False],
    })
    sku_df = compute_f10(df_orders, df_items)
    profit_row = sku_df[sku_df["product_id"] == "SKU-PROFIT"].iloc[0]
    loss_row = sku_df[sku_df["product_id"] == "SKU-LOSS"].iloc[0]

    assert profit_row["contribution_margin_pct"] == pytest.approx(38.0)
    assert profit_row["normalized_contribution_score"] == pytest.approx(38.0)

    assert loss_row["contribution_margin_pct"] == pytest.approx(-32.0)
    assert loss_row["normalized_contribution_score"] == pytest.approx(0.0)  # Capped at 0


# ===========================================================================
# PART 4 — SCORE DIRECTION CHECKS
# ===========================================================================

def test_score_direction_invariants():
    """Verify score direction:
    F05: 100 (full recovery) > 50 (partial) > 0 (none)
    F09: 100 (parity) > 50 (half profit) > 0 (no profit)
    F10: 100 (100% margin) > 30 (30% margin) > 0 (break-even/loss)
    """
    # F05 direction
    s_f05_full = compute_f05_normalized_score(10.0, 10.0)
    s_f05_half = compute_f05_normalized_score(5.0, 10.0)
    s_f05_zero = compute_f05_normalized_score(0.0, 10.0)
    assert s_f05_full > s_f05_half > s_f05_zero
    assert (s_f05_full, s_f05_half, s_f05_zero) == (100.0, 50.0, 0.0)

    # F09 direction
    s_f09_parity = compute_f09_normalized_score(20.0, 20.0)
    s_f09_half = compute_f09_normalized_score(10.0, 20.0)
    s_f09_zero = compute_f09_normalized_score(0.0, 20.0)
    assert s_f09_parity > s_f09_half > s_f09_zero
    assert (s_f09_parity, s_f09_half, s_f09_zero) == (100.0, 50.0, 0.0)

    # F10 direction
    s_f10_100 = compute_f10_normalized_score(100.0, 100.0)
    s_f10_30 = compute_f10_normalized_score(30.0, 100.0)
    s_f10_0 = compute_f10_normalized_score(0.0, 100.0)
    s_f10_loss = compute_f10_normalized_score(-20.0, 100.0)
    assert s_f10_100 > s_f10_30 > s_f10_0 == s_f10_loss
    assert (s_f10_100, s_f10_30, s_f10_0, s_f10_loss) == (100.0, 30.0, 0.0, 0.0)

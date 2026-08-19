"""tests/test_f01_f03.py — run with: pytest tests/test_f01_f03.py -v

Tests cover:
  - F03 formula correctness (single-item and multi-item orders)
  - F01 formula correctness (depends on F03 margin)
  - Aggregation dedup behavior
  - Edge cases: missing COGS, 100% discount, partial returns, mixed COGS
"""

import pandas as pd
import numpy as np
import pytest

from src.scoring.f01_f03 import (
    compute_line_item_margin,
    compute_order_profit,
    compute_f03,
    compute_f01,
    aggregate_losses,
)


# ---- Helpers ----

def _single_item_df(**overrides):
    """One-row-per-order DataFrame for simple formula tests."""
    base = {
        "order_id": ["ORD-001"],
        "net_selling_price": [100.0],
        "cogs_total": [40.0],
        "actual_shipping_cost": [5.0],
        "gateway_fee": [3.0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


# ================================================================
# F03: formula correctness on hand-computed cases (single-item)
# ================================================================

def test_f03_flags_negative_margin():
    df = _single_item_df(net_selling_price=[100.0], cogs_total=[80.0],
                         actual_shipping_cost=[15.0], gateway_fee=[10.0])
    # order_profit = (100 - 80) - 15 - 10 = -5
    result = compute_f03(df)
    assert result["net_contribution_margin"].iloc[0] == -5.0
    assert result["f03_breach"].iloc[0] == True


def test_f03_does_not_flag_positive_margin():
    df = _single_item_df(net_selling_price=[100.0], cogs_total=[40.0],
                         actual_shipping_cost=[5.0], gateway_fee=[3.0])
    # order_profit = (100 - 40) - 5 - 3 = 52
    result = compute_f03(df)
    assert result["net_contribution_margin"].iloc[0] == 52.0
    assert result["f03_breach"].iloc[0] == False


def test_f03_missing_cogs_stays_nan_not_zeroed():
    """The single most important behavior in this whole pipeline."""
    df = _single_item_df(cogs_total=[np.nan])
    result = compute_f03(df)
    assert pd.isna(result["net_contribution_margin"].iloc[0])
    assert result["f03_breach"].iloc[0] == False  # NaN < 0 is False, not a silent flag


def test_f03_hundred_percent_discount_flags_correctly():
    df = _single_item_df(net_selling_price=[0.0], cogs_total=[20.0],
                         actual_shipping_cost=[5.0], gateway_fee=[3.0])
    # order_profit = (0 - 20) - 5 - 3 = -28
    result = compute_f03(df)
    assert result["f03_breach"].iloc[0] == True
    assert result["f03_loss"].iloc[0] == 28.0


# ================================================================
# F01: formula correctness, depends on F03's margin
# ================================================================

def test_f01_flags_when_below_target():
    df = _single_item_df(target_min_profit=[20.0])
    # order_profit = (100 - 40) - 5 - 3 = 52... wait, that's above 20.
    # Use tighter numbers:
    df = _single_item_df(net_selling_price=[100.0], cogs_total=[80.0],
                         actual_shipping_cost=[5.0], gateway_fee=[3.0],
                         target_min_profit=[20.0])
    # order_profit = (100-80) - 5 - 3 = 12.  Target = 20 → loss = 8
    df = compute_f03(df)
    result = compute_f01(df)
    assert result["f01_flagged"].iloc[0] == True
    assert result["f01_loss"].iloc[0] == 8.0  # 20 - 12


def test_f01_does_not_flag_when_above_target():
    df = _single_item_df(net_selling_price=[100.0], cogs_total=[40.0],
                         actual_shipping_cost=[5.0], gateway_fee=[3.0],
                         target_min_profit=[20.0])
    # order_profit = (100-40) - 5 - 3 = 52.  Target = 20 → no flag
    df = compute_f03(df)
    result = compute_f01(df)
    assert result["f01_flagged"].iloc[0] == False
    assert result["f01_loss"].iloc[0] == 0.0


# ================================================================
# Aggregation: the dedup behavior, written as a test
# ================================================================

def test_duplicate_order_ids_are_not_double_counted():
    df = pd.DataFrame({
        "order_id": ["A", "A"],
        "net_selling_price": [100.0, 100.0], "cogs_total": [150.0, 150.0],
        "actual_shipping_cost": [5.0, 5.0], "gateway_fee": [3.0, 3.0],
    })
    df = compute_f03(df)
    result = aggregate_losses(df, loss_col="f03_loss", flag_col="f03_breach")
    assert result["orders_evaluated"] == 1     # not 2
    # order_profit = (100 - 150) + (100 - 150) - 5 - 3 = -100 - 8 = -108
    # Wait — both items are in the same order, so:
    #   line_gross_profit per item = 100 - 150 = -50
    #   order_gross_profit = -50 + -50 = -100
    #   order_profit = -100 - 5 - 3 = -108
    #   f03_loss = 108
    assert result["total_loss"] == pytest.approx(108.0)


# ================================================================
# NEW: Multi-item order — shipping/gateway counted once (Bug 1.2)
# ================================================================

class TestMultiItemOrder:

    def test_shipping_counted_once_for_3_item_order(self):
        """3 line items in one order — shipping & gateway must not triple-count."""
        df = pd.DataFrame({
            "order_id": ["ORD-X", "ORD-X", "ORD-X"],
            "net_selling_price": [50.0, 30.0, 20.0],
            "cogs_total": [20.0, 15.0, 10.0],
            "actual_shipping_cost": [12.0, 12.0, 12.0],  # same order-level cost
            "gateway_fee": [3.0, 3.0, 3.0],              # same order-level cost
        })
        result = compute_order_profit(df)
        # line_gross_profit: 30, 15, 10 = sum 55
        # order_profit = 55 - 12 - 3 = 40
        assert result["order_profit"].iloc[0] == pytest.approx(40.0)
        # All 3 rows should have the same order_profit
        assert result["order_profit"].nunique() == 1

    def test_multi_item_f03_flags_correctly(self):
        """Multi-item order that's overall unprofitable."""
        df = pd.DataFrame({
            "order_id": ["ORD-Y", "ORD-Y"],
            "net_selling_price": [10.0, 10.0],
            "cogs_total": [15.0, 15.0],
            "actual_shipping_cost": [8.0, 8.0],
            "gateway_fee": [2.0, 2.0],
        })
        result = compute_f03(df)
        # line_gross_profit: -5, -5 = sum -10
        # order_profit = -10 - 8 - 2 = -20
        assert result["f03_breach"].iloc[0] == True
        assert result["f03_loss"].iloc[0] == pytest.approx(20.0)

    def test_multi_item_aggregation_counts_order_once(self):
        """Two orders, one with 3 items, one with 1 item — aggregation correct."""
        df = pd.DataFrame({
            "order_id": ["ORD-A", "ORD-A", "ORD-A", "ORD-B"],
            "net_selling_price": [100.0, 50.0, 50.0, 30.0],
            "cogs_total": [40.0, 20.0, 20.0, 25.0],
            "actual_shipping_cost": [10.0, 10.0, 10.0, 8.0],
            "gateway_fee": [5.0, 5.0, 5.0, 2.0],
        })
        result = compute_f03(df)
        agg = aggregate_losses(result, loss_col="f03_loss", flag_col="f03_breach")
        assert agg["orders_evaluated"] == 2  # not 4


# ================================================================
# NEW: Partial returns (Bug 1.2 — returned items shouldn't count)
# ================================================================

class TestPartialReturns:

    def test_partial_return_excludes_returned_item_revenue(self):
        """2 of 3 items returned — only non-returned item contributes margin."""
        df = pd.DataFrame({
            "order_id": ["ORD-R", "ORD-R", "ORD-R"],
            "net_selling_price": [100.0, 50.0, 50.0],
            "cogs_total": [40.0, 20.0, 20.0],
            "actual_shipping_cost": [10.0, 10.0, 10.0],
            "gateway_fee": [5.0, 5.0, 5.0],
            "is_returned": [False, True, True],  # items 2 and 3 returned
        })
        result = compute_order_profit(df)
        # Active line_gross_profit: 60 (item 1), 0 (returned), 0 (returned) = 60
        # order_profit = 60 - 10 - 5 = 45
        assert result["order_profit"].iloc[0] == pytest.approx(45.0)

    def test_all_items_returned_shows_pure_shipping_loss(self):
        """All items returned — order profit = -shipping - gateway (no revenue)."""
        df = pd.DataFrame({
            "order_id": ["ORD-R2", "ORD-R2"],
            "net_selling_price": [100.0, 50.0],
            "cogs_total": [40.0, 20.0],
            "actual_shipping_cost": [10.0, 10.0],
            "gateway_fee": [5.0, 5.0],
            "is_returned": [True, True],
        })
        result = compute_order_profit(df)
        # All returned → active margin = 0
        # order_profit = 0 - 10 - 5 = -15
        assert result["order_profit"].iloc[0] == pytest.approx(-15.0)


# ================================================================
# NEW: Mixed COGS within one order
# ================================================================

class TestMixedCOGS:

    def test_nan_cogs_propagates_nan_to_order_profit(self):
        """If any item in an order has NaN COGS, order_profit should be NaN."""
        df = pd.DataFrame({
            "order_id": ["ORD-M", "ORD-M"],
            "net_selling_price": [100.0, 50.0],
            "cogs_total": [40.0, np.nan],  # second item missing COGS
            "actual_shipping_cost": [10.0, 10.0],
            "gateway_fee": [5.0, 5.0],
        })
        result = compute_order_profit(df)
        # line_gross_profit: 60, NaN → sum = NaN
        assert pd.isna(result["order_profit"].iloc[0])


# ================================================================
# NEW: Null gateway fee handling (non-Shopify-Payments stores)
# ================================================================

class TestNullGatewayFee:

    def test_null_gateway_fee_treated_as_zero(self):
        """Non-Shopify-Payments stores have null gateway_fee — should compute, not crash."""
        df = _single_item_df(gateway_fee=[np.nan])
        result = compute_order_profit(df)
        # order_profit = (100 - 40) - 5 - 0 = 55
        assert result["order_profit"].iloc[0] == pytest.approx(55.0)
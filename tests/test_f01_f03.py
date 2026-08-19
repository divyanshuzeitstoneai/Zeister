"""tests/test_f01_f03.py — Tests for F01 (Promotion Margin Leakage) & F03 (Margin Floor Breach).

Comprehensive test coverage covering:
  - F03: Negative profit, exact zero profit, positive profit, missing COGS, missing gateway fee, multi-item, partial returns
  - F01: Discounted vs non-discounted, above/below/exact floor, category floors, order % score, zero orders
  - Aggregation deduplication & metrics
"""

import numpy as np
import pandas as pd
import pytest

from src.scoring.f01_f03 import (
    compute_line_item_margin,
    compute_order_profit,
    compute_f03,
    aggregate_f03,
    compute_f01,
    aggregate_f01,
    aggregate_losses,
)


# ---- Helper ----

def _single_item_df(**overrides):
    """One-row-per-order DataFrame for simple formula tests."""
    base = {
        "order_id": ["ORD-001"],
        "category": ["fashion"],
        "selling_price": [100.0],
        "discount_given": [0.0],
        "net_selling_price": [100.0],
        "is_discounted": [False],
        "cogs_total": [40.0],
        "actual_shipping_cost": [5.0],
        "gateway_fee": [3.0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


# ================================================================
# F03: Margin Floor Breach Tests
# ================================================================

class TestF03MarginFloorBreach:

    def test_f03_flags_negative_margin(self):
        """Negative margin order: Net Selling $100, COGS $80, Ship $15, GW $10 -> Profit -$5.00."""
        df = _single_item_df(
            net_selling_price=[100.0], cogs_total=[80.0],
            actual_shipping_cost=[15.0], gateway_fee=[10.0],
        )
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(-5.0)
        assert result["f03_breach"].iloc[0] == True
        assert result["f03_loss"].iloc[0] == pytest.approx(5.0)

    def test_f03_does_not_flag_positive_margin(self):
        """Positive margin order: Net Selling $100, COGS $40, Ship $5, GW $3 -> Profit $52.00."""
        df = _single_item_df(
            net_selling_price=[100.0], cogs_total=[40.0],
            actual_shipping_cost=[5.0], gateway_fee=[3.0],
        )
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(52.0)
        assert result["f03_breach"].iloc[0] == False
        assert result["f03_loss"].iloc[0] == 0.0

    def test_f03_boundary_exactly_zero_profit(self):
        """Boundary: Profit exactly 0.0 -> NOT a floor breach."""
        df = _single_item_df(
            net_selling_price=[100.0], cogs_total=[85.0],
            actual_shipping_cost=[10.0], gateway_fee=[5.0],
        )
        # Profit = 100 - 85 - 10 - 5 = 0.0
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(0.0)
        assert result["f03_breach"].iloc[0] == False
        assert result["f03_loss"].iloc[0] == 0.0

    def test_f03_missing_cogs_stays_nan_and_not_flagged(self):
        """Missing COGS must stay NaN and NOT falsely trigger a negative-margin breach."""
        df = _single_item_df(cogs_total=[np.nan])
        result = compute_f03(df)
        assert pd.isna(result["net_contribution_margin"].iloc[0])
        assert result["f03_breach"].iloc[0] == False

    def test_f03_null_gateway_fee_defaults_to_zero(self):
        """Missing gateway fee defaults to 0.0 and calculates correctly."""
        df = _single_item_df(gateway_fee=[np.nan])
        result = compute_f03(df)
        # 100 - 40 - 5 - 0 = 55.0
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(55.0)
        assert result["f03_breach"].iloc[0] == False

    def test_f03_hundred_percent_discount_flags_full_cost(self):
        """100% discount: Net price 0, COGS 20, Ship 5, GW 3 -> Profit -28.00."""
        df = _single_item_df(
            net_selling_price=[0.0], cogs_total=[20.0],
            actual_shipping_cost=[5.0], gateway_fee=[3.0],
        )
        result = compute_f03(df)
        assert result["f03_breach"].iloc[0] == True
        assert result["f03_loss"].iloc[0] == pytest.approx(28.0)

    def test_f03_frequency_and_severity_aggregation(self):
        """F03 aggregate tracks both breach frequency (%) and total severity ($)."""
        df = pd.DataFrame({
            "order_id": ["ORD-1", "ORD-2", "ORD-3", "ORD-4"],
            "net_selling_price": [100.0, 100.0, 50.0, 100.0],
            "cogs_total": [40.0, 95.0, 70.0, np.nan],  # ORD-2 and ORD-3 are negative
            "actual_shipping_cost": [5.0, 10.0, 10.0, 5.0],
            "gateway_fee": [3.0, 3.0, 2.0, 3.0],
        })
        # ORD-1: 100 - 40 - 5 - 3 = +52 (positive)
        # ORD-2: 100 - 95 - 10 - 3 = -8 (breach, loss 8)
        # ORD-3: 50 - 70 - 10 - 2 = -32 (breach, loss 32)
        # ORD-4: NaN COGS -> NaN profit
        scored = compute_f03(df)
        agg = aggregate_f03(scored)
        assert agg["orders_evaluated"] == 3  # Valid non-null
        assert agg["orders_flagged"] == 2
        assert agg["breach_rate_pct"] == pytest.approx(2 / 3 * 100.0)
        assert agg["total_loss"] == pytest.approx(40.0)
        assert agg["avg_loss_per_breached_order"] == pytest.approx(20.0)


# ================================================================
# F01: Promotion Margin Leakage Tests
# ================================================================

class TestF01PromotionMarginLeakage:

    def test_f01_discounted_profitable_order_above_floor_no_breach(self):
        """Discounted order with profit above floor -> NOT flagged for F01."""
        df = _single_item_df(
            selling_price=[100.0], discount_given=[10.0], net_selling_price=[90.0],
            is_discounted=[True], cogs_total=[30.0], actual_shipping_cost=[5.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        # Profit = 90 - 30 - 5 - 3 = 52.0. Target floor = 15.0 -> above floor
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == False
        assert result["f01_loss"].iloc[0] == 0.0

    def test_f01_discounted_order_below_profit_floor_flags_breach(self):
        """Discounted order where profit is below floor -> FLAGGED for F01."""
        df = _single_item_df(
            selling_price=[100.0], discount_given=[20.0], net_selling_price=[80.0],
            is_discounted=[True], cogs_total=[60.0], actual_shipping_cost=[5.0],
            gateway_fee=[3.0], target_min_profit=[20.0],
        )
        # Profit = 80 - 60 - 5 - 3 = 12.0. Target floor = 20.0 -> Gap = 8.0
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == True
        assert result["f01_loss"].iloc[0] == pytest.approx(8.0)

    def test_f01_discounted_order_with_negative_profit(self):
        """Discounted order pushed into negative profit -> FLAGGED with full gap."""
        df = _single_item_df(
            selling_price=[100.0], discount_given=[30.0], net_selling_price=[70.0],
            is_discounted=[True], cogs_total=[75.0], actual_shipping_cost=[10.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        # Profit = 70 - 75 - 10 - 3 = -18.0. Target = 15.0 -> Gap = 15 - (-18) = 33.0
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == True
        assert result["f01_loss"].iloc[0] == pytest.approx(33.0)

    def test_f01_non_discounted_order_below_floor_is_not_f01_leakage(self):
        """Non-discounted order below profit floor must NOT be flagged as F01 promo leakage."""
        df = _single_item_df(
            selling_price=[100.0], discount_given=[0.0], net_selling_price=[100.0],
            is_discounted=[False], cogs_total=[80.0], actual_shipping_cost=[10.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        # Profit = 100 - 80 - 10 - 3 = 7.0 (below target 15.0), but is_discounted is False
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == False
        assert result["f01_loss"].iloc[0] == 0.0

    def test_f01_non_discounted_order_negative_profit_not_f01(self):
        """Non-discounted negative profit order is an F03 issue, NOT an F01 promotion issue."""
        df = _single_item_df(
            selling_price=[100.0], discount_given=[0.0], net_selling_price=[100.0],
            is_discounted=[False], cogs_total=[110.0], actual_shipping_cost=[10.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        # Profit = 100 - 110 - 10 - 3 = -23.0
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == False
        assert result["f01_loss"].iloc[0] == 0.0

    def test_f01_boundary_exactly_equal_to_profit_floor(self):
        """Boundary: order profit exactly equal to target minimum floor -> NOT breached."""
        df = _single_item_df(
            selling_price=[100.0], discount_given=[10.0], net_selling_price=[90.0],
            is_discounted=[True], cogs_total=[62.0], actual_shipping_cost=[10.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        # Profit = 90 - 62 - 10 - 3 = 15.0. Target = 15.0 -> Exactly at floor
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == False
        assert result["f01_loss"].iloc[0] == 0.0

    def test_f01_different_category_profit_floors(self):
        """F01 automatically applies category-specific profit floor thresholds."""
        df = pd.DataFrame({
            "order_id": ["ORD-FAS", "ORD-BEA", "ORD-ELE"],
            "category": ["fashion", "beauty", "electronics"],
            "selling_price": [100.0, 100.0, 100.0],
            "discount_given": [10.0, 10.0, 10.0],
            "net_selling_price": [90.0, 90.0, 90.0],
            "is_discounted": [True, True, True],
            "cogs_total": [70.0, 70.0, 80.0],
            "actual_shipping_cost": [5.0, 5.0, 3.0],
            "gateway_fee": [3.0, 3.0, 2.0],
        })
        # Fashion target: 15% ($15). Beauty target: 20% ($20). Electronics target: 8% ($8).
        # Fashion profit: 90 - 70 - 5 - 3 = 12 (Target 15 -> breach, gap 3)
        # Beauty profit: 90 - 70 - 5 - 3 = 12 (Target 20 -> breach, gap 8)
        # Electronics profit: 90 - 80 - 3 - 2 = 5 (Target 8 -> breach, gap 3)
        result = compute_f01(df)
        assert result.loc[result["category"] == "fashion", "f01_loss"].iloc[0] == pytest.approx(3.0)
        assert result.loc[result["category"] == "beauty", "f01_loss"].iloc[0] == pytest.approx(8.0)
        assert result.loc[result["category"] == "electronics", "f01_loss"].iloc[0] == pytest.approx(3.0)

    def test_f01_order_percentage_score_aggregation(self):
        """F01 aggregate calculates % of total orders breaching profit floor due to promotions."""
        df = pd.DataFrame({
            "order_id": ["ORD-1", "ORD-2", "ORD-3", "ORD-4", "ORD-5"],
            "category": ["fashion"] * 5,
            "selling_price": [100.0] * 5,
            "discount_given": [0.0, 0.0, 20.0, 20.0, 10.0],
            "net_selling_price": [100.0, 100.0, 80.0, 80.0, 90.0],
            "is_discounted": [False, False, True, True, True],
            "cogs_total": [40.0, 90.0, 60.0, 70.0, 30.0],
            "actual_shipping_cost": [5.0] * 5,
            "gateway_fee": [3.0] * 5,
            "target_min_profit": [15.0] * 5,
        })
        # Total orders = 5. Discounted orders = 3 (ORD-3, 4, 5).
        # ORD-1: No promo, profit 52 (ok)
        # ORD-2: No promo, profit 2 (below floor, but no promo -> not F01)
        # ORD-3: Promo, profit = 80 - 60 - 5 - 3 = 12 (Target 15 -> F01 breach, loss 3)
        # ORD-4: Promo, profit = 80 - 70 - 5 - 3 = 2 (Target 15 -> F01 breach, loss 13)
        # ORD-5: Promo, profit = 90 - 30 - 5 - 3 = 52 (above floor -> ok)
        scored = compute_f01(df)
        agg = aggregate_f01(scored)
        assert agg["orders_evaluated"] == 5
        assert agg["discounted_orders"] == 3
        assert agg["orders_flagged"] == 2
        assert agg["f01_score_pct"] == pytest.approx(40.0)  # 2 / 5 = 40%
        assert agg["discounted_breach_rate_pct"] == pytest.approx(2 / 3 * 100.0)
        assert agg["total_loss"] == pytest.approx(16.0)  # 3 + 13

    def test_f01_zero_orders_edge_case(self):
        """F01 gracefully handles empty DataFrame."""
        empty_df = pd.DataFrame(columns=[
            "order_id", "category", "selling_price", "net_selling_price",
            "is_discounted", "cogs_total", "actual_shipping_cost", "gateway_fee",
        ])
        result = compute_f01(empty_df)
        agg = aggregate_f01(result)
        assert agg["orders_evaluated"] == 0
        assert agg["orders_flagged"] == 0
        assert agg["f01_score_pct"] == 0.0
        assert agg["total_loss"] == 0.0


# ================================================================
# Multi-Item and Partial Return Tests
# ================================================================

class TestMultiItemAndReturns:

    def test_shipping_and_gateway_counted_once_per_order(self):
        """Order-level costs apply once across all line items of the order."""
        df = pd.DataFrame({
            "order_id": ["ORD-X", "ORD-X", "ORD-X"],
            "category": ["fashion", "beauty", "home_goods"],
            "selling_price": [50.0, 30.0, 20.0],
            "discount_given": [0.0, 0.0, 0.0],
            "net_selling_price": [50.0, 30.0, 20.0],
            "is_discounted": [False, False, False],
            "cogs_total": [20.0, 15.0, 10.0],
            "actual_shipping_cost": [12.0, 12.0, 12.0],
            "gateway_fee": [3.0, 3.0, 3.0],
        })
        result = compute_f03(df)
        # Line margins: 30, 15, 10 = 55. Order profit = 55 - 12 - 3 = 40
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(40.0)
        assert result["f03_breach"].iloc[0] == False

    def test_duplicate_order_rows_deduped_in_aggregation(self):
        """Deduplication ensures multiple line items do not multiply aggregate order counts."""
        df = pd.DataFrame({
            "order_id": ["ORD-A", "ORD-A"],
            "net_selling_price": [10.0, 10.0],
            "cogs_total": [15.0, 15.0],
            "actual_shipping_cost": [5.0, 5.0],
            "gateway_fee": [2.0, 2.0],
        })
        # Line gross: -5, -5 = -10. Order profit = -10 - 5 - 2 = -17
        result = compute_f03(df)
        agg = aggregate_f03(result)
        assert agg["orders_evaluated"] == 1
        assert agg["orders_flagged"] == 1
        assert agg["total_loss"] == pytest.approx(17.0)

    def test_partial_returns_exclude_returned_item_margin(self):
        """Partial return: returned items contribute 0 active margin to order profit."""
        df = pd.DataFrame({
            "order_id": ["ORD-R", "ORD-R"],
            "net_selling_price": [100.0, 50.0],
            "cogs_total": [40.0, 20.0],
            "actual_shipping_cost": [10.0, 10.0],
            "gateway_fee": [5.0, 5.0],
            "is_returned": [False, True],
        })
        result = compute_f03(df)
        # Active margin: (100 - 40) + 0 = 60. Order profit = 60 - 10 - 5 = 45.0
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(45.0)
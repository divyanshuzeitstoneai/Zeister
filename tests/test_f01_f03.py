"""Tests for F01 (Promotion Margin Leakage) and F03 (Margin Floor Breach)."""

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


def _single_item_df(**overrides):
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


class TestF03MarginFloorBreach:

    def test_f03_flags_negative_margin(self):
        df = _single_item_df(
            net_selling_price=[100.0], cogs_total=[80.0],
            actual_shipping_cost=[15.0], gateway_fee=[10.0],
        )
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(-5.0)
        assert result["f03_breach"].iloc[0] == True
        assert result["f03_loss"].iloc[0] == pytest.approx(5.0)

    def test_f03_does_not_flag_positive_margin(self):
        df = _single_item_df(
            net_selling_price=[100.0], cogs_total=[40.0],
            actual_shipping_cost=[5.0], gateway_fee=[3.0],
        )
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(52.0)
        assert result["f03_breach"].iloc[0] == False
        assert result["f03_loss"].iloc[0] == 0.0

    def test_f03_boundary_exactly_zero_profit(self):
        df = _single_item_df(
            net_selling_price=[100.0], cogs_total=[85.0],
            actual_shipping_cost=[10.0], gateway_fee=[5.0],
        )
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(0.0)
        assert result["f03_breach"].iloc[0] == False
        assert result["f03_loss"].iloc[0] == 0.0

    def test_f03_missing_cogs_stays_nan_and_not_flagged(self):
        df = _single_item_df(cogs_total=[np.nan])
        result = compute_f03(df)
        assert pd.isna(result["net_contribution_margin"].iloc[0])
        assert result["f03_breach"].iloc[0] == False

    def test_f03_null_gateway_fee_defaults_to_zero(self):
        df = _single_item_df(gateway_fee=[np.nan])
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(55.0)
        assert result["f03_breach"].iloc[0] == False

    def test_f03_hundred_percent_discount_flags_full_cost(self):
        df = _single_item_df(
            net_selling_price=[0.0], cogs_total=[20.0],
            actual_shipping_cost=[5.0], gateway_fee=[3.0],
        )
        result = compute_f03(df)
        assert result["f03_breach"].iloc[0] == True
        assert result["f03_loss"].iloc[0] == pytest.approx(28.0)

    def test_f03_frequency_and_severity_aggregation(self):
        df = pd.DataFrame({
            "order_id": ["ORD-1", "ORD-2", "ORD-3", "ORD-4"],
            "net_selling_price": [100.0, 100.0, 50.0, 100.0],
            "cogs_total": [40.0, 95.0, 70.0, np.nan],
            "actual_shipping_cost": [5.0, 10.0, 10.0, 5.0],
            "gateway_fee": [3.0, 3.0, 2.0, 3.0],
        })
        scored = compute_f03(df)
        agg = aggregate_f03(scored)
        assert agg["orders_evaluated"] == 3
        assert agg["orders_flagged"] == 2
        assert agg["breach_rate_pct"] == pytest.approx(2 / 3 * 100.0)
        assert agg["total_loss"] == pytest.approx(40.0)
        assert agg["avg_loss_per_breached_order"] == pytest.approx(20.0)


class TestF01PromotionMarginLeakage:

    def test_f01_discounted_profitable_order_above_floor_no_breach(self):
        df = _single_item_df(
            selling_price=[100.0], discount_given=[10.0], net_selling_price=[90.0],
            is_discounted=[True], cogs_total=[30.0], actual_shipping_cost=[5.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == False
        assert result["f01_loss"].iloc[0] == 0.0

    def test_f01_discounted_order_below_profit_floor_flags_breach(self):
        df = _single_item_df(
            selling_price=[100.0], discount_given=[20.0], net_selling_price=[80.0],
            is_discounted=[True], cogs_total=[60.0], actual_shipping_cost=[5.0],
            gateway_fee=[3.0], target_min_profit=[20.0],
        )
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == True
        assert result["f01_loss"].iloc[0] == pytest.approx(8.0)

    def test_f01_discounted_order_with_negative_profit(self):
        df = _single_item_df(
            selling_price=[100.0], discount_given=[30.0], net_selling_price=[70.0],
            is_discounted=[True], cogs_total=[75.0], actual_shipping_cost=[10.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == True
        assert result["f01_loss"].iloc[0] == pytest.approx(33.0)

    def test_f01_non_discounted_order_below_floor_is_not_f01_leakage(self):
        df = _single_item_df(
            selling_price=[100.0], discount_given=[0.0], net_selling_price=[100.0],
            is_discounted=[False], cogs_total=[80.0], actual_shipping_cost=[10.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == False
        assert result["f01_loss"].iloc[0] == 0.0

    def test_f01_non_discounted_order_negative_profit_not_f01(self):
        df = _single_item_df(
            selling_price=[100.0], discount_given=[0.0], net_selling_price=[100.0],
            is_discounted=[False], cogs_total=[110.0], actual_shipping_cost=[10.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == False
        assert result["f01_loss"].iloc[0] == 0.0

    def test_f01_boundary_exactly_equal_to_profit_floor(self):
        df = _single_item_df(
            selling_price=[100.0], discount_given=[10.0], net_selling_price=[90.0],
            is_discounted=[True], cogs_total=[62.0], actual_shipping_cost=[10.0],
            gateway_fee=[3.0], target_min_profit=[15.0],
        )
        result = compute_f01(df)
        assert result["f01_flagged"].iloc[0] == False
        assert result["f01_loss"].iloc[0] == 0.0

    def test_f01_different_category_profit_floors(self):
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
        result = compute_f01(df)
        assert result.loc[result["category"] == "fashion", "f01_loss"].iloc[0] == pytest.approx(1.50)
        assert result.loc[result["category"] == "beauty", "f01_loss"].iloc[0] == pytest.approx(6.00)
        assert result.loc[result["category"] == "electronics", "f01_loss"].iloc[0] == pytest.approx(2.20)

    def test_f01_order_percentage_score_aggregation(self):
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
        scored = compute_f01(df)
        agg = aggregate_f01(scored)
        assert agg["orders_evaluated"] == 5
        assert agg["discounted_orders"] == 3
        assert agg["orders_flagged"] == 2
        assert agg["f01_score_pct"] == pytest.approx(40.0)
        assert agg["discounted_breach_rate_pct"] == pytest.approx(2 / 3 * 100.0)
        assert agg["total_loss"] == pytest.approx(16.0)

    def test_f01_zero_orders_edge_case(self):
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


class TestMultiItemAndReturns:

    def test_shipping_and_gateway_counted_once_per_order(self):
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
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(40.0)
        assert result["f03_breach"].iloc[0] == False

    def test_duplicate_order_rows_deduped_in_aggregation(self):
        df = pd.DataFrame({
            "order_id": ["ORD-A", "ORD-A"],
            "net_selling_price": [10.0, 10.0],
            "cogs_total": [15.0, 15.0],
            "actual_shipping_cost": [5.0, 5.0],
            "gateway_fee": [2.0, 2.0],
        })
        result = compute_f03(df)
        agg = aggregate_f03(result)
        assert agg["orders_evaluated"] == 1
        assert agg["orders_flagged"] == 1
        assert agg["total_loss"] == pytest.approx(17.0)

    def test_partial_returns_exclude_returned_item_margin(self):
        df = pd.DataFrame({
            "order_id": ["ORD-R", "ORD-R"],
            "net_selling_price": [100.0, 50.0],
            "cogs_total": [40.0, 20.0],
            "actual_shipping_cost": [10.0, 10.0],
            "gateway_fee": [5.0, 5.0],
            "is_returned": [False, True],
        })
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(45.0)
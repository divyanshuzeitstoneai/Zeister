"""Tests for full edge-case matrix and end-to-end integration across F01–F12."""

import numpy as np
import pandas as pd
import pytest

from src.data_clean import dedup_orders, apply_cogs_policy
from src.scoring.f01_f03 import (
    compute_line_item_margin,
    compute_order_profit,
    compute_f03,
    aggregate_f03,
    compute_f01,
    aggregate_f01,
)
from src.scoring.f02 import compute_f02
from src.scoring.f04 import compute_f04, aggregate_f04
from src.scoring.f05 import compute_f05, aggregate_f05
from src.scoring.f09 import compute_f09
from src.scoring.f10 import compute_f10, aggregate_f10
from src.scoring.f11 import compute_f11, aggregate_f11
from src.scoring.f12 import compute_f12


def _order(order_id="ORD-T", **kwargs):
    base = {
        "order_id": [order_id],
        "category": ["fashion"],
        "selling_price": [100.0],
        "discount_given": [0.0],
        "net_selling_price": [100.0],
        "is_discounted": [False],
        "cogs_total": [40.0],
        "product_weight_kg": [1.0],
        "shipping_charged_to_customer": [5.0],
        "actual_shipping_cost": [8.0],
        "gateway_fee": [3.0],
        "is_returned": [False],
        "refund_amount": [0.0],
        "target_min_profit": [15.0],
    }
    base.update(kwargs)
    return pd.DataFrame(base)


class TestMissingCOGS:

    def test_exclude_policy_drops_row(self):
        df = _order(cogs_total=[np.nan])
        result = apply_cogs_policy(df, policy="exclude")
        assert len(result) == 0

    def test_excluded_row_not_scored(self):
        df = _order(cogs_total=[np.nan])
        result = apply_cogs_policy(df, policy="exclude")
        if len(result) > 0:
            result = compute_f03(result)
            agg = aggregate_f03(result)
            assert agg["total_loss"] == 0.0

    def test_impute_policy_fills_and_scores(self):
        df = pd.concat([
            _order("ORD-A", category=["fashion"], cogs_total=[40.0]),
            _order("ORD-B", category=["fashion"], cogs_total=[np.nan]),
        ], ignore_index=True)
        result = apply_cogs_policy(df, policy="impute_category_avg")
        assert len(result) == 2
        assert result["cogs_total"].isna().sum() == 0
        assert result.loc[1, "cogs_total"] == pytest.approx(40.0)


class TestMissingGatewayFee:

    def test_null_gateway_fee_computes_with_zero(self):
        df = _order(gateway_fee=[np.nan])
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(52.0)
        assert result["f03_breach"].iloc[0] == False


class TestBundledOrders:

    def test_three_items_shipping_once(self):
        df = pd.DataFrame({
            "order_id": ["ORD-B", "ORD-B", "ORD-B"],
            "net_selling_price": [50.0, 30.0, 20.0],
            "cogs_total": [20.0, 15.0, 10.0],
            "actual_shipping_cost": [12.0, 12.0, 12.0],
            "gateway_fee": [3.0, 3.0, 3.0],
            "shipping_charged_to_customer": [5.0, 5.0, 5.0],
        })
        result = compute_f03(df)
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(40.0)

        f05 = compute_f05(df)
        agg = aggregate_f05(f05)
        assert agg["orders_evaluated"] == 1
        assert agg["net_shipping_position"] == pytest.approx(-7.0)


class TestPartialReturns:

    def test_returned_items_excluded_from_margin(self):
        df = pd.DataFrame({
            "order_id": ["ORD-PR", "ORD-PR", "ORD-PR"],
            "net_selling_price": [80.0, 40.0, 30.0],
            "cogs_total": [30.0, 20.0, 10.0],
            "actual_shipping_cost": [10.0, 10.0, 10.0],
            "gateway_fee": [4.0, 4.0, 4.0],
            "is_returned": [False, True, False],
            "shipping_charged_to_customer": [5.0, 5.0, 5.0],
        })
        result = compute_order_profit(df)
        assert result["order_profit"].iloc[0] == pytest.approx(56.0)

    def test_f05_still_counts_shipping_for_partial_return(self):
        df = pd.DataFrame({
            "order_id": ["ORD-PR2", "ORD-PR2"],
            "shipping_charged_to_customer": [5.0, 5.0],
            "actual_shipping_cost": [12.0, 12.0],
            "is_returned": [False, True],
        })
        f05 = compute_f05(df)
        agg = aggregate_f05(f05)
        assert agg["net_shipping_position"] == pytest.approx(-7.0)


class TestFullDiscountAndFreeShipping:

    def test_100_percent_discount_max_flaggable_loss(self):
        df = _order(
            selling_price=[100.0], discount_given=[100.0],
            net_selling_price=[0.0], is_discounted=[True],
            cogs_total=[20.0], target_min_profit=[15.0],
        )
        result = compute_f03(df)
        result = compute_f01(result)
        assert result["f03_breach"].iloc[0] == True
        assert result["f03_loss"].iloc[0] == pytest.approx(31.0)
        assert result["f01_flagged"].iloc[0] == True
        assert result["f01_loss"].iloc[0] == pytest.approx(46.0)

    def test_cheap_bulky_item_f04(self):
        df_orders = pd.DataFrame({
            "order_id": ["ORD-BULKY"],
            "shipping_charged_to_customer": [0.0],
            "actual_shipping_cost": [25.0],
        })
        df_items = pd.DataFrame({
            "order_id": ["ORD-BULKY"],
            "selling_price": [15.0],
            "net_selling_price": [15.0],
            "cogs_total": [8.0],
            "product_weight_kg": [10.0],
            "length_cm": [50.0],
            "width_cm": [40.0],
            "height_cm": [30.0],
            "is_returned": [False],
        })
        res = compute_f04(df_orders, df_items)
        assert res["f04_flagged"].iloc[0] == True
        assert res["f04_leakage"].iloc[0] == pytest.approx(18.0)


class TestFullPipelineSuite:

    def test_all_formulas_execute_on_master_dataset(self):
        df_orders = pd.DataFrame({
            "order_id": ["ORD-1", "ORD-2"],
            "channel": ["web", "amazon"],
            "gross_sales": [100.0, 100.0],
            "net_sales": [90.0, 100.0],
            "shipping_charged_to_customer": [0.0, 5.0],
            "actual_shipping_cost": [12.0, 10.0],
            "gateway_fee": [3.0, 3.0],
            "chargeback_amount": [0.0, 0.0],
            "is_cancelled": [False, False],
        })
        df_items = pd.DataFrame({
            "order_id": ["ORD-1", "ORD-2"],
            "product_id": ["SKU-1", "SKU-2"],
            "category": ["fashion", "electronics"],
            "quantity": [1, 1],
            "selling_price": [100.0, 100.0],
            "discount_given": [10.0, 0.0],
            "net_selling_price": [90.0, 100.0],
            "is_discounted": [True, False],
            "cogs_total": [40.0, 50.0],
            "product_weight_kg": [1.0, 1.0],
            "length_cm": [np.nan, np.nan],
            "width_cm": [np.nan, np.nan],
            "height_cm": [np.nan, np.nan],
            "channel_fee_pct": [0.0, 0.15],
            "is_returned": [False, False],
            "refund_amount": [0.0, 0.0],
            "restocking_cost": [0.0, 0.0],
        })

        scored = compute_f03(df_items.merge(df_orders[["order_id", "actual_shipping_cost", "gateway_fee"]], on="order_id"))
        f03_res = aggregate_f03(scored)
        assert f03_res["orders_evaluated"] == 2

        scored_f01 = compute_f01(scored)
        f01_res = aggregate_f01(scored_f01)
        assert f01_res["orders_evaluated"] == 2

        f02_res = compute_f02(df_orders, df_items)
        assert f02_res["total_sales"] == 200.0

        f04_df = compute_f04(df_orders, df_items)
        f04_res = aggregate_f04(f04_df)
        assert f04_res["orders_evaluated"] == 2

        f05_df = compute_f05(df_orders)
        f05_res = aggregate_f05(f05_df)
        assert f05_res["orders_evaluated"] == 2

        f09_res = compute_f09(df_orders, df_items)
        assert f09_res["primary_channel"] == "web"

        f10_df = compute_f10(df_orders, df_items)
        f10_res = aggregate_f10(f10_df)
        assert f10_res["total_skus_evaluated"] == 2

        f11_df = compute_f11(df_orders, df_items)
        f11_res = aggregate_f11(f11_df)
        assert f11_res["orders_evaluated"] == 2

        f12_res = compute_f12(df_orders, df_items)
        assert f12_res["gross_sales"] == 200.0

"""Tests for F05 Shipping Cost Recovery."""

import pandas as pd
import numpy as np
import pytest

from src.scoring.f05 import compute_f05, aggregate_f05


def _make_f05_df(**overrides):
    base = {
        "order_id": ["ORD-001"],
        "shipping_charged_to_customer": [5.0],
        "actual_shipping_cost": [4.50],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestF05Formula:

    def test_surplus_when_charged_more_than_actual(self):
        df = _make_f05_df(shipping_charged_to_customer=[5.0],
                          actual_shipping_cost=[4.50])
        result = compute_f05(df)
        assert result["shipping_delta"].iloc[0] == pytest.approx(0.50)
        assert result["f05_surplus"].iloc[0] == True
        assert result["f05_deficit"].iloc[0] == False

    def test_deficit_when_actual_exceeds_charged(self):
        df = _make_f05_df(shipping_charged_to_customer=[5.0],
                          actual_shipping_cost=[8.50])
        result = compute_f05(df)
        assert result["shipping_delta"].iloc[0] == pytest.approx(-3.50)
        assert result["f05_surplus"].iloc[0] == False
        assert result["f05_deficit"].iloc[0] == True

    def test_exact_break_even(self):
        df = _make_f05_df(shipping_charged_to_customer=[5.0],
                          actual_shipping_cost=[5.0])
        result = compute_f05(df)
        assert result["shipping_delta"].iloc[0] == pytest.approx(0.0)
        assert result["f05_surplus"].iloc[0] == False
        assert result["f05_deficit"].iloc[0] == False

    def test_zero_shipping_both_zero(self):
        df = _make_f05_df(shipping_charged_to_customer=[0.0],
                          actual_shipping_cost=[0.0])
        result = compute_f05(df)
        assert result["shipping_delta"].iloc[0] == pytest.approx(0.0)
        assert result["f05_surplus"].iloc[0] == False
        assert result["f05_deficit"].iloc[0] == False


class TestF05Aggregation:

    def test_net_sum_across_all_orders(self):
        df = pd.DataFrame({
            "order_id": ["A", "B", "C"],
            "shipping_charged_to_customer": [10.0, 5.0, 8.0],
            "actual_shipping_cost": [6.0, 9.0, 8.0],
        })
        result = compute_f05(df)
        agg = aggregate_f05(result)
        assert agg["orders_evaluated"] == 3
        assert agg["orders_surplus"] == 1
        assert agg["orders_deficit"] == 1
        assert agg["total_surplus"] == pytest.approx(4.0)
        assert agg["total_deficit"] == pytest.approx(-4.0)
        assert agg["net_shipping_position"] == pytest.approx(0.0)

    def test_storewide_net_surplus(self):
        df = pd.DataFrame({
            "order_id": ["A", "B"],
            "shipping_charged_to_customer": [10.0, 8.0],
            "actual_shipping_cost": [5.0, 3.0],
        })
        result = compute_f05(df)
        agg = aggregate_f05(result)
        assert agg["net_shipping_position"] == pytest.approx(10.0)

    def test_storewide_net_deficit(self):
        df = pd.DataFrame({
            "order_id": ["A", "B"],
            "shipping_charged_to_customer": [2.0, 3.0],
            "actual_shipping_cost": [8.0, 10.0],
        })
        result = compute_f05(df)
        agg = aggregate_f05(result)
        assert agg["net_shipping_position"] == pytest.approx(-13.0)


class TestF05EdgeCases:

    def test_free_shipping_pure_deficit(self):
        df = _make_f05_df(shipping_charged_to_customer=[0.0],
                          actual_shipping_cost=[12.0])
        result = compute_f05(df)
        assert result["shipping_delta"].iloc[0] == pytest.approx(-12.0)
        assert result["f05_deficit"].iloc[0] == True

    def test_returned_order_still_incurs_shipping_cost(self):
        df = pd.DataFrame({
            "order_id": ["ORD-RET"],
            "shipping_charged_to_customer": [5.0],
            "actual_shipping_cost": [12.0],
            "is_returned": [True],
        })
        result = compute_f05(df)
        assert result["shipping_delta"].iloc[0] == pytest.approx(-7.0)

    def test_multi_item_order_counted_once(self):
        df = pd.DataFrame({
            "order_id": ["ORD-M", "ORD-M", "ORD-M"],
            "shipping_charged_to_customer": [5.0, 5.0, 5.0],
            "actual_shipping_cost": [12.0, 12.0, 12.0],
        })
        result = compute_f05(df)
        agg = aggregate_f05(result)
        assert agg["orders_evaluated"] == 1
        assert agg["total_deficit"] == pytest.approx(-7.0)
        assert agg["net_shipping_position"] == pytest.approx(-7.0)

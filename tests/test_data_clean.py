"""tests/test_data_clean.py — Tests for the data-integrity pipeline."""

import pandas as pd
import numpy as np
import pytest

from src.data_clean import (
    dedup_orders,
    validate_required_columns,
    apply_cogs_policy,
    recompute_target_min_profit,
    clean_pipeline,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_df(**overrides):
    """Build a minimal valid DataFrame; override any column via kwargs."""
    base = {
        "order_id": ["ORD-001", "ORD-002", "ORD-003"],
        "category": ["fashion", "beauty", "electronics"],
        "selling_price": [100.0, 50.0, 200.0],
        "discount_given": [10.0, 5.0, 0.0],
        "net_selling_price": [90.0, 45.0, 200.0],
        "is_discounted": [True, True, False],
        "cogs_total": [40.0, 20.0, 100.0],
        "product_weight_kg": [1.0, 0.5, 3.0],
        "shipping_charged_to_customer": [5.0, 5.0, 0.0],
        "actual_shipping_cost": [8.0, 4.0, 12.0],
        "gateway_fee": [3.0, 1.5, 6.0],
        "is_returned": [False, False, False],
        "refund_amount": [0.0, 0.0, 0.0],
        "target_min_profit": [15.0, 7.5, 30.0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


# ---------------------------------------------------------------------------
# Dedup tests (Bug 1.5)
# ---------------------------------------------------------------------------

class TestDedupOrders:

    def test_removes_exact_duplicate_order_ids(self):
        df = _make_df(order_id=["ORD-001", "ORD-001", "ORD-002"])
        result = dedup_orders(df)
        assert len(result) == 2
        assert result["order_id"].tolist() == ["ORD-001", "ORD-002"]

    def test_keeps_first_occurrence(self):
        df = _make_df(
            order_id=["ORD-001", "ORD-001", "ORD-002"],
            selling_price=[100.0, 999.0, 50.0],  # second ORD-001 has different price
        )
        result = dedup_orders(df)
        assert result.loc[result.order_id == "ORD-001", "selling_price"].iloc[0] == 100.0

    def test_no_duplicates_returns_unchanged(self):
        df = _make_df()
        result = dedup_orders(df)
        assert len(result) == len(df)

    def test_resets_index_after_dedup(self):
        df = _make_df(order_id=["ORD-001", "ORD-001", "ORD-002"])
        result = dedup_orders(df)
        assert list(result.index) == [0, 1]


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidateRequiredColumns:

    def test_passes_when_all_present_and_non_null(self):
        df = _make_df()
        # Should not raise
        validate_required_columns(df)

    def test_raises_on_missing_column(self):
        df = _make_df().drop(columns=["order_id"])
        with pytest.raises(ValueError, match="Missing required columns"):
            validate_required_columns(df)

    def test_raises_on_null_in_required_column(self):
        df = _make_df(order_id=["ORD-001", None, "ORD-003"])
        with pytest.raises(ValueError, match="null values"):
            validate_required_columns(df)

    def test_custom_column_list(self):
        df = _make_df()
        # cogs_total is NOT in default required list, but test custom
        df.loc[0, "cogs_total"] = np.nan
        # Should not raise with default columns (cogs_total not required)
        validate_required_columns(df)
        # Should raise if explicitly required
        with pytest.raises(ValueError, match="null values"):
            validate_required_columns(df, columns=["cogs_total"])


# ---------------------------------------------------------------------------
# COGS policy tests (Decision 1)
# ---------------------------------------------------------------------------

class TestApplyCOGSPolicy:

    def test_exclude_drops_null_cogs_rows(self):
        df = _make_df(cogs_total=[40.0, np.nan, 100.0])
        result = apply_cogs_policy(df, policy="exclude")
        assert len(result) == 2
        assert result["cogs_total"].isna().sum() == 0

    def test_exclude_no_nulls_returns_unchanged(self):
        df = _make_df()
        result = apply_cogs_policy(df, policy="exclude")
        assert len(result) == len(df)

    def test_impute_fills_with_category_average(self):
        df = _make_df(
            order_id=["ORD-001", "ORD-002", "ORD-003", "ORD-004"],
            category=["fashion", "fashion", "fashion", "beauty"],
            selling_price=[100.0, 100.0, 100.0, 50.0],
            net_selling_price=[90.0, 90.0, 90.0, 45.0],
            discount_given=[10.0, 10.0, 10.0, 5.0],
            is_discounted=[True, True, True, True],
            cogs_total=[40.0, 60.0, np.nan, 20.0],
            product_weight_kg=[1.0, 1.0, 1.0, 0.5],
            shipping_charged_to_customer=[5.0, 5.0, 5.0, 5.0],
            actual_shipping_cost=[8.0, 8.0, 8.0, 4.0],
            gateway_fee=[3.0, 3.0, 3.0, 1.5],
            is_returned=[False, False, False, False],
            refund_amount=[0.0, 0.0, 0.0, 0.0],
            target_min_profit=[15.0, 15.0, 15.0, 7.5],
        )
        result = apply_cogs_policy(df, policy="impute_category_avg")
        assert len(result) == 4
        assert result["cogs_total"].isna().sum() == 0
        # fashion avg COGS = (40 + 60) / 2 = 50.0
        assert result.loc[2, "cogs_total"] == pytest.approx(50.0)

    def test_invalid_policy_raises(self):
        df = _make_df(cogs_total=[40.0, np.nan, 100.0])
        with pytest.raises(ValueError, match="Unknown COGS policy"):
            apply_cogs_policy(df, policy="magic")


# ---------------------------------------------------------------------------
# Target-min-profit recomputation (Decision 2)
# ---------------------------------------------------------------------------

class TestRecomputeTargetMinProfit:

    def test_flat_15_percent(self):
        df = _make_df()
        flat_margins = {cat: 0.15 for cat in ["fashion", "beauty", "electronics"]}
        result = recompute_target_min_profit(df, margins=flat_margins)
        for _, row in result.iterrows():
            assert row["target_min_profit"] == pytest.approx(row["net_selling_price"] * 0.15)

    def test_category_specific_margins(self):
        custom = {"fashion": 0.20, "beauty": 0.10, "electronics": 0.08}
        df = _make_df()
        result = recompute_target_min_profit(df, margins=custom)
        assert result.loc[0, "target_min_profit"] == pytest.approx(90.0 * 0.20)
        assert result.loc[1, "target_min_profit"] == pytest.approx(45.0 * 0.10)
        assert result.loc[2, "target_min_profit"] == pytest.approx(200.0 * 0.08)

    def test_unknown_category_uses_default(self):
        df = _make_df(category=["unknown_cat", "beauty", "electronics"])
        result = recompute_target_min_profit(df, default=0.12)
        assert result.loc[0, "target_min_profit"] == pytest.approx(90.0 * 0.12)


class TestCleanPipeline:

    def test_full_pipeline_dedup_and_validate(self):
        df = _make_df(order_id=["ORD-001", "ORD-001", "ORD-002"])
        result = clean_pipeline(df, recompute_targets=True)
        assert len(result) == 2
        assert result.loc[0, "target_min_profit"] == pytest.approx(90.0 * 0.15)
        assert result.loc[1, "target_min_profit"] == pytest.approx(200.0 * 0.08)

    def test_pipeline_with_cogs_exclude(self):
        df = _make_df(cogs_total=[40.0, np.nan, 100.0])
        result = clean_pipeline(df, cogs_policy="exclude", recompute_targets=False)
        assert len(result) == 2
        assert result["cogs_total"].isna().sum() == 0

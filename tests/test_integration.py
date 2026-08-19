"""tests/test_integration.py — Full edge-case matrix from the verification plan.

Each test encodes a row (or cluster of rows) from Section 4's edge-case table,
exercising the full pipeline: clean → F03 → F01 → F05.

F04 tests are stubbed as xfail until Decision 3 (formula) is resolved.
"""

import pandas as pd
import numpy as np
import pytest

from src.data_clean import dedup_orders, apply_cogs_policy
from src.scoring.f01_f03 import (
    compute_line_item_margin,
    compute_order_profit,
    compute_f03,
    compute_f01,
    aggregate_losses,
)
from src.scoring.f05 import compute_f05, aggregate_f05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _order(order_id="ORD-T", **kwargs):
    """Build a single-row order DataFrame with sensible defaults."""
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


# ================================================================
# Edge case: Missing COGS — exclude vs impute
# ================================================================

class TestMissingCOGS:

    def test_exclude_policy_drops_row(self):
        df = _order(cogs_total=[np.nan])
        result = apply_cogs_policy(df, policy="exclude")
        assert len(result) == 0

    def test_excluded_row_not_scored(self):
        """After exclusion, F03 should have nothing to score."""
        df = _order(cogs_total=[np.nan])
        result = apply_cogs_policy(df, policy="exclude")
        if len(result) > 0:
            result = compute_f03(result)
            agg = aggregate_losses(result, "f03_loss", "f03_breach")
            assert agg["total_loss"] == 0.0

    def test_impute_policy_fills_and_scores(self):
        # Two orders: one with COGS, one without
        df = pd.concat([
            _order("ORD-A", category=["fashion"], cogs_total=[40.0]),
            _order("ORD-B", category=["fashion"], cogs_total=[np.nan]),
        ], ignore_index=True)
        result = apply_cogs_policy(df, policy="impute_category_avg")
        assert len(result) == 2
        assert result["cogs_total"].isna().sum() == 0
        # Imputed value should be 40.0 (only one non-null in fashion)
        assert result.loc[1, "cogs_total"] == pytest.approx(40.0)


# ================================================================
# Edge case: Missing gateway fee (non-Shopify-Payments store)
# ================================================================

class TestMissingGatewayFee:

    def test_null_gateway_fee_computes_with_zero(self):
        """Non-Shopify-Payments stores → null gateway_fee → treated as 0."""
        df = _order(gateway_fee=[np.nan])
        result = compute_f03(df)
        # profit = (100 - 40) - 8 - 0 = 52
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(52.0)
        assert result["f03_breach"].iloc[0] == False


# ================================================================
# Edge case: Bundled orders (multi-item) — shipping/gateway once
# ================================================================

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
        # F03
        result = compute_f03(df)
        # line margins: 30, 15, 10 = 55.  order_profit = 55 - 12 - 3 = 40
        assert result["net_contribution_margin"].iloc[0] == pytest.approx(40.0)

        # F05 — shipping counted once
        f05 = compute_f05(df)
        agg = aggregate_f05(f05)
        assert agg["orders_evaluated"] == 1
        # delta = 5 - 12 = -7 (once, not thrice)
        assert agg["net_shipping_position"] == pytest.approx(-7.0)


# ================================================================
# Edge case: Partial returns (1 of 3 items returned)
# ================================================================

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
        # Active items: 80-30=50, 30-10=20 → sum=70
        # Returned: 40-20=20 → excluded
        # order_profit = 70 - 10 - 4 = 56
        assert result["order_profit"].iloc[0] == pytest.approx(56.0)

    def test_f05_still_counts_shipping_for_partial_return(self):
        """Courier cost already incurred — return doesn't undo shipping."""
        df = pd.DataFrame({
            "order_id": ["ORD-PR2", "ORD-PR2"],
            "shipping_charged_to_customer": [5.0, 5.0],
            "actual_shipping_cost": [12.0, 12.0],
            "is_returned": [False, True],
        })
        f05 = compute_f05(df)
        agg = aggregate_f05(f05)
        assert agg["net_shipping_position"] == pytest.approx(-7.0)


# ================================================================
# Edge case: 100% discount order
# ================================================================

class TestFullDiscount:

    def test_100_percent_discount_max_flaggable_loss(self):
        df = _order(
            selling_price=[100.0], discount_given=[100.0],
            net_selling_price=[0.0], is_discounted=[True],
            cogs_total=[20.0], target_min_profit=[15.0],
        )
        result = compute_f03(df)
        result = compute_f01(result)
        # margin = (0 - 20) - 8 - 3 = -31
        assert result["f03_breach"].iloc[0] == True
        assert result["f03_loss"].iloc[0] == pytest.approx(31.0)
        # F01: target 15, margin -31 → loss = 15 - (-31) = 46
        assert result["f01_flagged"].iloc[0] == True
        assert result["f01_loss"].iloc[0] == pytest.approx(46.0)


# ================================================================
# Edge case: $0 shipping charged, real courier cost > 0
# ================================================================

class TestFreeShipping:

    def test_zero_charged_full_courier_deficit(self):
        df = _order(shipping_charged_to_customer=[0.0], actual_shipping_cost=[22.0])
        f05 = compute_f05(df)
        assert f05["shipping_delta"].iloc[0] == pytest.approx(-22.0)
        assert f05["f05_deficit"].iloc[0] == True


# ================================================================
# Edge case: Duplicate order_id (after dedup)
# ================================================================

class TestDedupIntegration:

    def test_dedup_removes_duplicates_before_scoring(self):
        df = pd.concat([_order("ORD-DUP"), _order("ORD-DUP")], ignore_index=True)
        assert len(df) == 2
        deduped = dedup_orders(df)
        assert len(deduped) == 1
        result = compute_f03(deduped)
        agg = aggregate_losses(result, "f03_loss", "f03_breach")
        assert agg["orders_evaluated"] == 1


# ================================================================
# Edge case: Extreme outlier — cheap, bulky item (F04 target scenario)
# ================================================================

class TestExtremeOutlier:

    def test_cheap_bulky_item_f04(self):
        """This is exactly the case F04 is meant to catch: cheap product, heavy/bulky shipping."""
        from src.scoring.f04 import compute_f04
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
        res = compute_f04(df_orders, df_items, formula="formula_b")
        assert res["f04_flagged"].iloc[0] == True
        # Shipping ($25) - Product Profit ($7) = $18 loss
        assert res["f04_leakage"].iloc[0] == pytest.approx(18.0)


# ================================================================
# Edge case: Free-shipping threshold boundary
# ================================================================

class TestFreeShippingThreshold:

    def test_order_exactly_at_threshold(self):
        """Boundary: order cart value exactly at $50 threshold with free shipping granted."""
        from src.scoring.f04 import compute_f04
        df_orders = pd.DataFrame({
            "order_id": ["ORD-50"],
            "shipping_charged_to_customer": [0.0],
            "actual_shipping_cost": [8.0],
        })
        df_items = pd.DataFrame({
            "order_id": ["ORD-50"],
            "selling_price": [50.0],
            "net_selling_price": [50.0],
            "cogs_total": [45.0],  # only $5 profit
            "product_weight_kg": [2.0],
            "length_cm": [np.nan],
            "width_cm": [np.nan],
            "height_cm": [np.nan],
            "is_returned": [False],
        })
        res = compute_f04(df_orders, df_items, formula="formula_b")
        # Courier ($8) - Profit ($5) = $3 leakage
        assert res["f04_flagged"].iloc[0] == True
        assert res["f04_leakage"].iloc[0] == pytest.approx(3.0)


# ================================================================
# Full pipeline smoke test on synthetic multi-scenario dataset
# ================================================================

class TestFullPipelineSmokeTest:

    def test_mixed_scenario_no_crash_no_nan_infinity(self):
        """Run all scores on a mixed dataset — no crashes, no inf values."""
        df = pd.concat([
            _order("ORD-1", cogs_total=[40.0], gateway_fee=[3.0]),
            _order("ORD-2", cogs_total=[np.nan], gateway_fee=[np.nan]),  # will be excluded
            _order("ORD-3", net_selling_price=[0.0], cogs_total=[50.0],
                   is_discounted=[True], discount_given=[100.0],
                   target_min_profit=[15.0]),
            _order("ORD-4", shipping_charged_to_customer=[0.0],
                   actual_shipping_cost=[25.0]),
        ], ignore_index=True)

        # COGS exclusion
        clean = apply_cogs_policy(df, policy="exclude")
        assert len(clean) == 3  # ORD-2 excluded

        # F03
        scored = compute_f03(clean)
        assert not np.isinf(scored["net_contribution_margin"]).any()

        # F01
        disc = scored[scored["is_discounted"]].copy()
        if len(disc) > 0:
            disc = compute_f01(disc)
            assert not np.isinf(disc["f01_loss"]).any()

        # F05
        f05 = compute_f05(clean)
        assert not np.isinf(f05["shipping_delta"]).any()
        agg = aggregate_f05(f05)
        assert np.isfinite(agg["net_shipping_position"])

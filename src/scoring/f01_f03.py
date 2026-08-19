"""src/scoring/f01_f03.py — F01 (Promotion Margin Leakage) & F03 (Margin Floor Breach).

Architecture (Bug 1.2 fix):
    Line-item level:  gross_profit = net_selling_price − cogs_total
    Order level:      order_profit = Σ(gross_profit) − shipping − gateway_fee

    Shipping and gateway fee are order-level costs — they apply once per order,
    not per line item.  When the dataset has one row per order this is a no-op,
    but the architecture now correctly handles multi-item orders without
    double-counting order-level costs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Line-item level
# ---------------------------------------------------------------------------

def compute_line_item_margin(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``line_gross_profit = net_selling_price − cogs_total`` per row.

    Rows with null COGS will produce NaN margin — this is intentional;
    the COGS-handling policy should be applied upstream (``data_clean.apply_cogs_policy``).
    """
    df = df.copy()
    df["line_gross_profit"] = df["net_selling_price"] - df["cogs_total"]
    return df


# ---------------------------------------------------------------------------
# Order-level rollup
# ---------------------------------------------------------------------------

def compute_order_profit(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate line-item margins and subtract order-level costs.

    For each ``order_id``:
        order_gross_profit = Σ(line_gross_profit)   — across all non-returned items
        order_profit = order_gross_profit − actual_shipping_cost − gateway_fee

    The result is merged back onto the original DataFrame as:
        ``order_gross_profit``, ``order_shipping_cost``, ``order_gateway_fee``,
        ``order_profit`` (= net contribution margin at order level).

    When the dataset is one-row-per-order this behaves identically to the
    old flat formula, but correctly handles multi-item orders.
    """
    df = df.copy()

    # Compute line_gross_profit if not already present
    if "line_gross_profit" not in df.columns:
        df = compute_line_item_margin(df)

    # For partial returns: only non-returned items contribute revenue/COGS
    # If there's no per-line-item 'is_returned' column, treat every row as active
    if "is_returned" in df.columns:
        active_margin = df["line_gross_profit"].where(~df["is_returned"], 0.0)
    else:
        active_margin = df["line_gross_profit"]

    df["_active_line_gross_profit"] = active_margin

    # Sum line-item margins per order
    # CRITICAL: if ANY line item in an order has NaN COGS (→ NaN line_gross_profit),
    # the whole order's profit must be NaN — not silently computed without that item.
    order_gross = (
        df.groupby("order_id")["_active_line_gross_profit"]
        .sum()
        .rename("order_gross_profit")
    )
    # Detect orders where any line item had NaN margin
    has_nan = (
        df.groupby("order_id")["_active_line_gross_profit"]
        .apply(lambda x: x.isna().any())
    )
    order_gross[has_nan] = np.nan

    # Shipping and gateway fee: take the FIRST value per order
    # (they're order-level — should be identical across line items of same order)
    order_costs = (
        df.groupby("order_id")[["actual_shipping_cost", "gateway_fee"]]
        .first()
        .rename(columns={
            "actual_shipping_cost": "order_shipping_cost",
            "gateway_fee": "order_gateway_fee",
        })
    )

    order_level = order_gross.to_frame().join(order_costs)
    # Fill NaN gateway fee with 0 for the purpose of computing order profit
    # (NaN gateway fee means non-Shopify-Payments store — Decision: use 0, not block)
    order_level["order_gateway_fee_filled"] = order_level["order_gateway_fee"].fillna(0.0)
    order_level["order_profit"] = (
        order_level["order_gross_profit"]
        - order_level["order_shipping_cost"]
        - order_level["order_gateway_fee_filled"]
    )

    # Merge back
    merge_cols = ["order_gross_profit", "order_shipping_cost",
                  "order_gateway_fee", "order_profit"]
    df = df.merge(order_level[merge_cols], on="order_id", how="left")

    # Clean up temp column
    df.drop(columns=["_active_line_gross_profit"], inplace=True)

    return df


# ---------------------------------------------------------------------------
# F03 — Margin Floor Breach
# ---------------------------------------------------------------------------

def compute_f03(df: pd.DataFrame) -> pd.DataFrame:
    """Flag orders where the order-level profit is negative.

    Adds:
        ``net_contribution_margin`` — alias for ``order_profit`` (backward compat)
        ``f03_breach`` — True where margin < 0
        ``f03_loss``   — absolute value of negative margin (0 otherwise)
    """
    df = df.copy()

    # Ensure order-level profit is computed
    if "order_profit" not in df.columns:
        df = compute_order_profit(df)

    df["net_contribution_margin"] = df["order_profit"]
    df["f03_breach"] = df["net_contribution_margin"] < 0
    df["f03_loss"] = np.where(df["f03_breach"], -df["net_contribution_margin"], 0.0)
    return df


# ---------------------------------------------------------------------------
# F01 — Promotion Margin Leakage
# ---------------------------------------------------------------------------

def compute_f01(df: pd.DataFrame) -> pd.DataFrame:
    """Flag orders where margin is below the target minimum profit.

    Requires ``net_contribution_margin`` (from ``compute_f03``) and
    ``target_min_profit`` to be present.

    Adds:
        ``f01_loss``    — gap between target and actual margin (0 if above target)
        ``f01_flagged`` — True where loss > 0
    """
    df = df.copy()

    if "net_contribution_margin" not in df.columns:
        df = compute_f03(df)

    df["f01_loss"] = np.where(
        df["net_contribution_margin"] < df["target_min_profit"],
        df["target_min_profit"] - df["net_contribution_margin"],
        0.0,
    )
    df["f01_flagged"] = df["f01_loss"] > 0
    return df


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_losses(df: pd.DataFrame, loss_col: str, flag_col: str) -> dict:
    """Aggregate losses, deduplicating on ``order_id``.

    This ensures multi-row orders (multiple line items) are not double-counted
    at the aggregate level.  The order-level columns (``order_profit``,
    ``f03_loss``, ``f01_loss``) are already computed at order granularity,
    so taking the first row per order_id is correct.
    """
    deduped = df.drop_duplicates(subset="order_id")
    return {
        "orders_evaluated": len(deduped),
        "orders_flagged": int(deduped[flag_col].sum()),
        "total_loss": float(deduped.loc[deduped[flag_col], loss_col].sum()),
    }
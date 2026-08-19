"""src/scoring/f01_f03.py — F01 (Promotion Margin Leakage) & F03 (Margin Floor Breach).

Business Definitions:
    F03 (Margin Floor Breach):
        Measures orders that become unprofitable (net contribution margin < 0)
        after accounting for net selling price, COGS, shipping, and gateway fees.
        Outputs: frequency of breaches (%) and loss severity ($).

    F01 (Promotion Margin Leakage):
        Measures the percentage of total orders where promotional discounts push
        the sale below the required profit floor (target minimum profit).
        Outputs: F01 score (% of total orders breached due to promo),
        breach count, and total promotional margin leakage ($).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import TARGET_MARGINS, DEFAULT_TARGET_MARGIN


# ---------------------------------------------------------------------------
# Line-item level
# ---------------------------------------------------------------------------

def compute_line_item_margin(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``line_gross_profit = net_selling_price − cogs_total`` per row.

    Rows with null COGS produce NaN margin — this is intentional;
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
    """
    df = df.copy()

    # Compute line_gross_profit if not already present
    if "line_gross_profit" not in df.columns:
        df = compute_line_item_margin(df)

    # For partial returns: only non-returned items contribute revenue/COGS
    if "is_returned" in df.columns:
        active_margin = df["line_gross_profit"].where(~df["is_returned"], 0.0)
    else:
        active_margin = df["line_gross_profit"]

    df["_active_line_gross_profit"] = active_margin

    # Sum line-item margins per order
    # If ANY line item in an order has NaN COGS, order gross profit must be NaN
    order_gross = (
        df.groupby("order_id")["_active_line_gross_profit"]
        .sum()
        .rename("order_gross_profit")
    )
    has_nan = (
        df.groupby("order_id")["_active_line_gross_profit"]
        .apply(lambda x: x.isna().any())
    )
    order_gross[has_nan] = np.nan

    # Shipping and gateway fee: take first per order
    order_costs = (
        df.groupby("order_id")[["actual_shipping_cost", "gateway_fee"]]
        .first()
        .rename(columns={
            "actual_shipping_cost": "order_shipping_cost",
            "gateway_fee": "order_gateway_fee",
        })
    )

    order_level = order_gross.to_frame().join(order_costs)
    order_level["order_gateway_fee_filled"] = order_level["order_gateway_fee"].fillna(0.0)
    order_level["order_shipping_cost_filled"] = order_level["order_shipping_cost"].fillna(0.0)
    order_level["order_profit"] = (
        order_level["order_gross_profit"]
        - order_level["order_shipping_cost_filled"]
        - order_level["order_gateway_fee_filled"]
    )

    # Aggregate discount status to order level if line-item level
    if "is_discounted" in df.columns:
        order_disc = df.groupby("order_id")["is_discounted"].any().rename("order_is_discounted")
        order_level = order_level.join(order_disc)
    elif "discount_given" in df.columns:
        order_disc = (df.groupby("order_id")["discount_given"].sum() > 0).rename("order_is_discounted")
        order_level = order_level.join(order_disc)

    # Merge back
    merge_cols = ["order_gross_profit", "order_shipping_cost",
                  "order_gateway_fee", "order_profit"]
    if "order_is_discounted" in order_level.columns:
        merge_cols.append("order_is_discounted")
    
    # Avoid duplicate column names if already present in df
    for col in merge_cols:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    df = df.merge(order_level[merge_cols], on="order_id", how="left")
    df.drop(columns=["_active_line_gross_profit"], inplace=True)

    return df


# ---------------------------------------------------------------------------
# F03 — Margin Floor Breach
# ---------------------------------------------------------------------------

def compute_f03(df: pd.DataFrame) -> pd.DataFrame:
    """Flag orders where order-level net profit is strictly negative (< 0).

    Adds:
        ``net_contribution_margin`` — alias for ``order_profit``
        ``f03_breach`` — True where margin < 0 (False for >= 0 or NaN)
        ``f03_loss``   — absolute value of negative margin (0.0 otherwise)
    """
    df = df.copy()

    if "order_profit" not in df.columns:
        df = compute_order_profit(df)

    df["net_contribution_margin"] = df["order_profit"]
    # NaN margin does not flag breach
    df["f03_breach"] = df["net_contribution_margin"] < 0.0
    df["f03_breach"] = df["f03_breach"].fillna(False)
    df["f03_loss"] = np.where(df["f03_breach"], -df["net_contribution_margin"], 0.0)
    return df


def aggregate_f03(df: pd.DataFrame) -> dict:
    """Aggregate F03 Margin Floor Breach metrics.

    Deduplicates on ``order_id`` to ensure order-level metric accuracy.
    """
    deduped = df.drop_duplicates(subset="order_id")
    # Only evaluate orders with valid (non-null) margin
    valid = deduped.dropna(subset=["net_contribution_margin"]) if "net_contribution_margin" in deduped.columns else deduped
    evaluated_count = len(valid)
    flagged = valid[valid["f03_breach"]]
    flagged_count = len(flagged)
    total_loss = float(flagged["f03_loss"].sum()) if flagged_count > 0 else 0.0
    breach_rate_pct = (flagged_count / evaluated_count * 100.0) if evaluated_count > 0 else 0.0
    avg_loss = (total_loss / flagged_count) if flagged_count > 0 else 0.0

    return {
        "orders_evaluated": evaluated_count,
        "orders_flagged": flagged_count,
        "breach_rate_pct": breach_rate_pct,
        "total_loss": total_loss,
        "avg_loss_per_breached_order": avg_loss,
    }


# ---------------------------------------------------------------------------
# F01 — Promotion Margin Leakage
# ---------------------------------------------------------------------------

def compute_f01(
    df: pd.DataFrame,
    target_margins: dict[str, float] | None = None,
    default_target_margin: float | None = None,
) -> pd.DataFrame:
    """Flag orders where promotional discounts push profit below the required floor.

    Business definition:
        F01 measures the percentage of total orders where promotional discounts
        push the sale below the required profit floor.

    An order is flagged for F01 if and only if:
        1. The order was discounted (``is_discounted == True`` or ``order_is_discounted == True``)
        2. The order's net contribution margin is strictly below the required profit floor (``target_min_profit``)

    Adds:
        ``is_discounted`` (ensured)
        ``target_min_profit`` (computed if missing)
        ``f01_flagged`` — True where order is discounted and margin < target_min_profit
        ``f01_loss``    — dollar gap (target_min_profit - margin) for flagged orders, 0 otherwise
    """
    df = df.copy()
    target_margins = target_margins or TARGET_MARGINS
    default_target = default_target_margin if default_target_margin is not None else DEFAULT_TARGET_MARGIN

    if "net_contribution_margin" not in df.columns:
        df = compute_f03(df)

    # Determine discount status per row / order
    if "is_discounted" not in df.columns:
        if "order_is_discounted" in df.columns:
            df["is_discounted"] = df["order_is_discounted"]
        elif "discount_given" in df.columns:
            df["is_discounted"] = df["discount_given"] > 0
        else:
            df["is_discounted"] = False

    # Compute target_min_profit if not already present
    if "target_min_profit" not in df.columns:
        price_col = "selling_price" if "selling_price" in df.columns else "net_selling_price"
        if "category" in df.columns:
            rates = df["category"].map(target_margins).fillna(default_target)
            df["target_min_profit"] = df[price_col] * rates
        else:
            df["target_min_profit"] = df[price_col] * default_target

    # Aggregate target_min_profit to order level if line items exist
    if df["order_id"].duplicated().any():
        order_target = df.groupby("order_id")["target_min_profit"].sum().rename("_order_target_min_profit")
        df = df.merge(order_target, on="order_id", how="left")
        target_col = "_order_target_min_profit"
    else:
        target_col = "target_min_profit"

    # Discounted check: order must be discounted
    is_disc = df["is_discounted"]
    if "order_is_discounted" in df.columns:
        is_disc = is_disc | df["order_is_discounted"]

    # Floor breach check: order profit < target_min_profit
    margin = df["net_contribution_margin"]
    target = df[target_col]

    is_below_floor = (margin < target) & margin.notna()

    # F01 Flagged only when BOTH discounted and below floor
    df["f01_flagged"] = (is_disc & is_below_floor).fillna(False)

    # F01 Dollar Loss Gap
    df["f01_loss"] = np.where(
        df["f01_flagged"],
        np.maximum(0.0, target - margin),
        0.0,
    )

    if "_order_target_min_profit" in df.columns:
        df.drop(columns=["_order_target_min_profit"], inplace=True)

    return df


def aggregate_f01(df: pd.DataFrame) -> dict:
    """Aggregate F01 Promotion Margin Leakage metrics.

    Business output:
        - ``orders_evaluated``: Total evaluated orders
        - ``discounted_orders``: Number of orders that received a promotional discount
        - ``orders_flagged``: Number of discounted orders breaching the profit floor
        - ``f01_score_pct``: % of total orders breaching profit floor due to promotions
        - ``discounted_breach_rate_pct``: % of discounted orders breaching floor
        - ``total_loss``: Total dollar leakage gap
        - ``avg_loss_per_flagged_order``: Average loss on flagged orders
    """
    deduped = df.drop_duplicates(subset="order_id")
    valid = deduped.dropna(subset=["net_contribution_margin"]) if "net_contribution_margin" in deduped.columns else deduped
    total_orders = len(valid)

    is_disc = valid["is_discounted"]
    if "order_is_discounted" in valid.columns:
        is_disc = is_disc | valid["order_is_discounted"]
    discounted_orders = int(is_disc.sum())

    flagged = valid[valid["f01_flagged"]]
    orders_flagged = len(flagged)

    f01_score_pct = (orders_flagged / total_orders * 100.0) if total_orders > 0 else 0.0
    disc_breach_rate = (orders_flagged / discounted_orders * 100.0) if discounted_orders > 0 else 0.0
    total_loss = float(flagged["f01_loss"].sum()) if orders_flagged > 0 else 0.0
    avg_loss = (total_loss / orders_flagged) if orders_flagged > 0 else 0.0

    return {
        "orders_evaluated": total_orders,
        "discounted_orders": discounted_orders,
        "orders_flagged": orders_flagged,
        "f01_score_pct": f01_score_pct,
        "discounted_breach_rate_pct": disc_breach_rate,
        "total_loss": total_loss,
        "avg_loss_per_flagged_order": avg_loss,
    }


def aggregate_losses(df: pd.DataFrame, loss_col: str, flag_col: str) -> dict:
    """Legacy helper for backward compatibility."""
    deduped = df.drop_duplicates(subset="order_id")
    return {
        "orders_evaluated": len(deduped),
        "orders_flagged": int(deduped[flag_col].sum()),
        "total_loss": float(deduped.loc[deduped[flag_col], loss_col].sum()),
    }
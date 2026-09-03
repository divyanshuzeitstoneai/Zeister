"""F06: Payment Fee Leakage Score.

Measures gateway fee overpayment vs. a standard benchmark, segmented by
payment method (standard card, BNPL, international card).

Core formulas:
  Standard Benchmark Fee  = (order_amount × standard_fee_pct) + standard_fixed_fee
  Fee Variance            = actual_gateway_fee − standard_benchmark_fee
  Leakage (per order)     = max(0, fee_variance)  — only overpayment counts
  Fee Efficiency Score    = (standard_benchmark_fee / actual_gateway_fee) × 100

Critical rules:
  - actual_gateway_fee null → order is Unresolved (NEVER default to 0)
  - Missing benchmark metafield → fallback to industry default (2.9% + $0.30),
    flag is_benchmark_estimated = True
  - Payment method classification ladder:
      payment_method_name → infer from gateway_name → "Unknown"
  - Negative variance (savings) is NOT counted as leakage (max(0, ...))
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.config import F06_STANDARD_FEE_PCT, F06_STANDARD_FIXED_FEE, F06_HIGH_COST_RATES


# ═══════════════════════════════════════════════════════════════════════
# PAYMENT METHOD CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

# Gateway names that imply a specific payment method
GATEWAY_TO_METHOD = {
    "shop_pay_installments": "BNPL",
    "afterpay": "BNPL",
    "klarna": "BNPL",
    "affirm": "BNPL",
    "sezzle": "BNPL",
    "zip": "BNPL",
    "paypal": "PayPal",
    "shopify_payments": "Card",
    "stripe": "Card",
    "manual": "Manual",
    "cash": "Manual",
}

# Payment method name patterns that map to method categories
METHOD_NAME_PATTERNS = {
    "Visa": "Card",
    "Mastercard": "Card",
    "Amex": "Card",
    "American Express": "Card",
    "Discover": "Card",
    "JCB": "Card",
    "Diners": "Card",
    "Shop Pay": "Card",
    "Shop Pay Installments": "BNPL",
    "Afterpay": "BNPL",
    "Klarna": "BNPL",
    "Affirm": "BNPL",
    "Sezzle": "BNPL",
    "PayPal": "PayPal",
}


def classify_payment_method(
    payment_method_name: str | None,
    gateway_name: str | None,
) -> tuple[str, bool]:
    """Classify a payment into a method category.

    Returns (method_category, is_method_known).
    Classification ladder:
      1. payment_method_name (most specific)
      2. gateway_name (inferred)
      3. "Unknown" (attribution unavailable)
    """
    # Step 1: Try payment_method_name (longest pattern first so specific matches take precedence)
    if payment_method_name and pd.notna(payment_method_name):
        pmn = str(payment_method_name).strip()
        sorted_patterns = sorted(METHOD_NAME_PATTERNS.items(), key=lambda x: len(x[0]), reverse=True)
        for pattern, category in sorted_patterns:
            if pattern.lower() in pmn.lower():
                return category, True

    # Step 2: Try gateway_name inference
    if gateway_name and pd.notna(gateway_name):
        gw = str(gateway_name).strip().lower()
        if gw in GATEWAY_TO_METHOD:
            return GATEWAY_TO_METHOD[gw], True

    # Step 3: Unresolvable
    return "Unknown", False


def get_standard_benchmark_fee(
    order_amount: float,
    standard_fee_pct: float | None = None,
    standard_fixed_fee: float | None = None,
    is_benchmark_configured: bool = True,
) -> tuple[float, bool]:
    """Calculate the standard benchmark fee for an order.

    Formula: Standard Benchmark Fee = (Order Amount × standard_fee_pct) + standard_fixed_fee
    Returns: (standard_benchmark_fee, is_benchmark_estimated)
    """
    if standard_fee_pct is not None:
        pct = standard_fee_pct
        is_estimated = not is_benchmark_configured
    else:
        pct = F06_STANDARD_FEE_PCT
        is_estimated = True

    if standard_fixed_fee is not None:
        fixed = standard_fixed_fee
    else:
        fixed = F06_STANDARD_FIXED_FEE
        is_estimated = True

    benchmark = (order_amount * pct) + fixed
    return round(benchmark, 2), is_estimated


# ═══════════════════════════════════════════════════════════════════════
# PER-ORDER SCORING
# ═══════════════════════════════════════════════════════════════════════

def compute_f06(
    df_orders: pd.DataFrame,
    df_transactions: pd.DataFrame | None = None,
    standard_fee_pct: float | None = None,
    standard_fixed_fee: float | None = None,
    high_cost_rates: dict | None = None,
) -> pd.DataFrame:
    """Compute F06 Payment Fee Leakage per order.

    Required columns on df_orders:
      - order_id, gateway_fee (actual fee paid)
      - net_sales or total_received (order amount for benchmark calc)

    Optional columns (from df_transactions or df_orders):
      - payment_method_name, gateway_name  (for method classification)
      - is_international_card (for intl-card rate selection)

    Returns df_orders with new columns:
      - payment_method_category: Card/BNPL/PayPal/IntlCard/Unknown
      - is_method_known: whether attribution was possible
      - standard_benchmark_fee: expected fee at benchmark rate
      - is_benchmark_estimated: True if benchmark used fallback
      - fee_variance: actual - benchmark
      - f06_leakage: max(0, fee_variance)
      - fee_efficiency_pct: (benchmark / actual) × 100
      - f06_status: "Unresolved" if actual_gateway_fee is null
      - is_fee_estimated: True if any fallback was used
    """
    df = df_orders.copy()
    std_pct = standard_fee_pct if standard_fee_pct is not None else F06_STANDARD_FEE_PCT
    std_fix = standard_fixed_fee if standard_fixed_fee is not None else F06_STANDARD_FIXED_FEE
    hcr = high_cost_rates or F06_HIGH_COST_RATES

    # Merge transaction info if provided
    if df_transactions is not None and not df_transactions.empty:
        tx_cols = ["order_id"]
        for col in ["payment_method_name", "gateway_name"]:
            if col in df_transactions.columns:
                tx_cols.append(col)
        if len(tx_cols) > 1:
            # Take first transaction per order (primary payment)
            tx_dedup = df_transactions.drop_duplicates(subset="order_id")[tx_cols]
            for col in tx_cols[1:]:
                if col in df.columns:
                    df.drop(columns=[col], inplace=True)
            df = df.merge(tx_dedup, on="order_id", how="left")

    # Determine order amount
    if "net_sales" in df.columns:
        order_amount = df["net_sales"]
    elif "total_received" in df.columns:
        order_amount = df["total_received"]
    elif "net_paid_amount" in df.columns:
        order_amount = df["net_paid_amount"]
    else:
        order_amount = pd.Series(0.0, index=df.index)

    # Determine actual gateway fee
    actual_fee_col = "gateway_fee"
    if actual_fee_col not in df.columns:
        actual_fee_col = "actual_gateway_fee"
    if actual_fee_col not in df.columns:
        df["f06_status"] = "Unresolved"
        df["f06_leakage"] = np.nan
        df["fee_efficiency_pct"] = np.nan
        return df

    actual_fee = df[actual_fee_col]

    # Classify payment method
    pmn_col = "payment_method_name" if "payment_method_name" in df.columns else None
    gw_col = "gateway_name" if "gateway_name" in df.columns else None

    method_categories = []
    method_known = []
    for idx in df.index:
        pmn = df.at[idx, pmn_col] if pmn_col else None
        gw = df.at[idx, gw_col] if gw_col else None
        # Check for international card flag
        if "is_international_card" in df.columns and pd.notna(df.at[idx, "is_international_card"]):
            if df.at[idx, "is_international_card"]:
                method_categories.append("IntlCard")
                method_known.append(True)
                continue
        cat, known = classify_payment_method(pmn, gw)
        method_categories.append(cat)
        method_known.append(known)

    df["payment_method_category"] = method_categories
    df["is_method_known"] = method_known

    # Calculate benchmarks per row
    benchmarks = []
    benchmark_estimated = []
    has_custom_benchmark = (standard_fee_pct is not None) and (standard_fixed_fee is not None)

    for idx in df.index:
        loc = df.index.get_loc(idx)
        val = order_amount.iloc[loc] if hasattr(order_amount, "iloc") else order_amount[idx]
        amt = float(val) if pd.notna(val) else 0.0
        
        # Check if row has merchant metafield overrides
        row_pct = df.at[idx, "standard_fee_pct"] if "standard_fee_pct" in df.columns and pd.notna(df.at[idx, "standard_fee_pct"]) else standard_fee_pct
        row_fix = df.at[idx, "standard_fixed_fee"] if "standard_fixed_fee" in df.columns and pd.notna(df.at[idx, "standard_fixed_fee"]) else standard_fixed_fee
        row_configured = has_custom_benchmark or ("standard_fee_pct" in df.columns and pd.notna(df.at[idx, "standard_fee_pct"]))

        bm, is_est = get_standard_benchmark_fee(amt, row_pct, row_fix, is_benchmark_configured=row_configured)
        benchmarks.append(bm)
        benchmark_estimated.append(is_est)

    df["standard_benchmark_fee"] = benchmarks
    df["is_benchmark_estimated"] = benchmark_estimated

    # Core calculations
    # CRITICAL: If actual_gateway_fee is null → Unresolved, NEVER 0
    actual = actual_fee.copy()
    is_null_fee = actual.isna()

    df["fee_variance"] = np.where(
        is_null_fee,
        np.nan,
        actual - df["standard_benchmark_fee"],
    )

    df["f06_leakage"] = np.where(
        is_null_fee,
        np.nan,
        np.maximum(0.0, df["fee_variance"]),
    )

    df["fee_efficiency_pct"] = np.where(
        is_null_fee | (actual == 0),
        np.nan,
        (df["standard_benchmark_fee"] / actual) * 100.0,
    )

    df["f06_status"] = np.where(
        is_null_fee,
        "Unresolved",
        np.where(
            df["f06_leakage"] > 0,
            "Leaking",
            "Efficient",
        ),
    )

    df["is_fee_estimated"] = df["is_benchmark_estimated"] | is_null_fee

    return df


# ═══════════════════════════════════════════════════════════════════════
# AGGREGATION
# ═══════════════════════════════════════════════════════════════════════

def aggregate_f06(df: pd.DataFrame) -> dict:
    """Aggregate F06 Payment Fee Leakage to store-level summary.

    Returns dict with:
      - orders_evaluated: total orders with non-null actual_gateway_fee
      - orders_unresolved: orders with null fee (excluded from scoring)
      - orders_leaking: orders where fee > benchmark
      - orders_efficient: orders where fee <= benchmark
      - total_leakage: sum of max(0, variance) across all leaking orders
      - total_savings: sum of negative variances (orders paying below benchmark)
      - avg_efficiency_pct: mean fee efficiency score
      - leakage_by_method: breakdown by payment method category
    """
    deduped = df.drop_duplicates(subset="order_id") if "order_id" in df.columns else df

    if "f06_status" not in deduped.columns:
        return {"orders_evaluated": 0, "orders_unresolved": len(deduped),
                "total_leakage": 0.0, "avg_efficiency_pct": 0.0}

    unresolved = deduped[deduped["f06_status"] == "Unresolved"]
    resolved = deduped[deduped["f06_status"] != "Unresolved"]

    leaking = resolved[resolved["f06_status"] == "Leaking"]
    efficient = resolved[resolved["f06_status"] == "Efficient"]

    total_leakage = float(resolved["f06_leakage"].sum()) if len(resolved) > 0 else 0.0
    total_savings = float(
        resolved.loc[resolved["fee_variance"] < 0, "fee_variance"].sum()
    ) if len(resolved) > 0 else 0.0

    avg_efficiency = float(resolved["fee_efficiency_pct"].mean()) if len(resolved) > 0 else 0.0

    # Breakdown by payment method
    method_breakdown = {}
    if "payment_method_category" in resolved.columns and len(resolved) > 0:
        for method, group in resolved.groupby("payment_method_category"):
            method_breakdown[method] = {
                "orders": len(group),
                "total_leakage": float(group["f06_leakage"].sum()),
                "avg_efficiency_pct": float(group["fee_efficiency_pct"].mean()),
                "orders_leaking": int((group["f06_status"] == "Leaking").sum()),
            }

    leakage_rate_pct = (len(leaking) / len(resolved) * 100.0) if len(resolved) > 0 else 0.0

    return {
        "orders_evaluated": len(resolved),
        "orders_unresolved": len(unresolved),
        "orders_leaking": len(leaking),
        "orders_efficient": len(efficient),
        "leakage_rate_pct": leakage_rate_pct,
        "total_leakage": total_leakage,
        "total_savings": total_savings,
        "net_fee_position": total_leakage + total_savings,
        "avg_efficiency_pct": avg_efficiency,
        "leakage_by_method": method_breakdown,
    }

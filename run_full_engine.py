"""run_full_engine.py — Comprehensive Master Runner for F01–F12 Zeitster Scoring Engine.

Runs all scoring models against the multi-table synthetic dataset:
    - F01: Promotion Margin Leakage
    - F02: Discount Dependency Score
    - F03: Margin Floor Breach
    - F04: Free-Shipping Leakage (Volumetric & True Cash Loss)
    - F05: Shipping Cost Recovery (Net Surplus / Deficit)
    - F09: Channel Margin Divergence (Marketplaces vs Primary)
    - F10: Return & Refund Profitability
    - F11: Product True Net Profit
    - F12: Revenue Leakage Ratio

Usage:
    python run_full_engine.py
"""

import logging
import pandas as pd

from src.scoring.f01_f03 import compute_f03, compute_f01, aggregate_losses
from src.scoring.f02 import compute_f02
from src.scoring.f04 import compute_f04, aggregate_f04
from src.scoring.f05 import compute_f05, aggregate_f05
from src.scoring.f09 import compute_f09
from src.scoring.f10 import compute_f10
from src.scoring.f11 import compute_f11
from src.scoring.f12 import compute_f12

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ORDERS_PATH = "data/synthetic_orders.csv.gz"
LINE_ITEMS_PATH = "data/synthetic_line_items.csv.gz"


def run_all():
    logger.info("Loading orders from %s ...", ORDERS_PATH)
    df_orders = pd.read_csv(ORDERS_PATH, compression="gzip")
    logger.info("Loading line items from %s ...", LINE_ITEMS_PATH)
    df_line_items = pd.read_csv(LINE_ITEMS_PATH, compression="gzip")
    
    print("\n" + "=" * 70)
    print("ZEITSTER SCORING ENGINE — FULL SUITE EXECUTION (F01–F12)")
    print("=" * 70)
    print(f"Dataset Size: {len(df_orders):,} orders, {len(df_line_items):,} line items")
    print(f"Gross Merchandise Value (GMV): ${df_orders['gross_sales'].sum():,.2f}")
    
    # -------------------------------------------------------------------
    # F03 & F01
    # -------------------------------------------------------------------
    active_orders = df_orders[~df_orders["is_cancelled"]]["order_id"]
    active_items = df_line_items[df_line_items["order_id"].isin(active_orders)].copy()
    
    # Flatten items for order-level rollup with F01/F03
    merged_items = active_items.merge(
        df_orders[["order_id", "actual_shipping_cost", "gateway_fee"]],
        on="order_id",
        how="left",
    )
    
    scored_f03 = compute_f03(merged_items)
    f03_res = aggregate_losses(scored_f03, "f03_loss", "f03_breach")
    
    print("\n--- F03: Margin Floor Breach ---")
    print(f"  Orders Evaluated: {f03_res['orders_evaluated']:,}")
    print(f"  Unprofitable Orders: {f03_res['orders_flagged']:,} ({f03_res['orders_flagged']/f03_res['orders_evaluated']*100:.2f}%)")
    print(f"  Total Floor Breach Loss: ${f03_res['total_loss']:,.2f}")

    # F01 on discounted
    from src.config import TARGET_MARGINS
    merged_items["target_min_profit"] = merged_items.apply(
        lambda r: r["selling_price"] * TARGET_MARGINS.get(r["category"], 0.15), axis=1
    )
    disc_items = merged_items[merged_items["is_discounted"]].copy()
    if len(disc_items) > 0:
        scored_f01 = compute_f01(disc_items)
        f01_res = aggregate_losses(scored_f01, "f01_loss", "f01_flagged")
        print("\n--- F01: Promotion Margin Leakage ---")
        print(f"  Discounted Orders: {f01_res['orders_evaluated']:,}")
        print(f"  Below-Target Orders: {f01_res['orders_flagged']:,} ({f01_res['orders_flagged']/f01_res['orders_evaluated']*100:.2f}%)")
        print(f"  Total Promo Leakage: ${f01_res['total_loss']:,.2f}")

    # -------------------------------------------------------------------
    # F02: Discount Dependency
    # -------------------------------------------------------------------
    f02_res = compute_f02(df_orders, df_line_items)
    print("\n--- F02: Discount Dependency ---")
    print(f"  Discounted Sales Share: {f02_res['discounted_share']*100:.1f}% (Benchmark: {f02_res['healthy_benchmark']*100:.1f}%)")
    print(f"  Threshold Breached: {f02_res['is_breached']}")
    print(f"  Average Discount Depth: {f02_res['avg_discount_depth']*100:.1f}%")
    print(f"  Total Discount Dependency Loss: ${f02_res['f02_loss']:,.2f}")

    # -------------------------------------------------------------------
    # F04: Free-Shipping Leakage
    # -------------------------------------------------------------------
    f04_df = compute_f04(df_orders, df_line_items)
    f04_res = aggregate_f04(f04_df)
    print("\n--- F04: Free-Shipping Leakage ---")
    print(f"  Orders Evaluated: {f04_res['orders_evaluated']:,}")
    print(f"  Orders Leaking Cash on Shipping: {f04_res['orders_flagged']:,}")
    print(f"  Total Free-Shipping Leakage: ${f04_res['total_leakage']:,.2f}")

    # -------------------------------------------------------------------
    # F05: Shipping Cost Recovery
    # -------------------------------------------------------------------
    f05_df = compute_f05(df_orders)
    f05_res = aggregate_f05(f05_df)
    print("\n--- F05: Shipping Cost Recovery ---")
    print(f"  Orders with Surplus: {f05_res['orders_surplus']:,} | Orders with Deficit: {f05_res['orders_deficit']:,}")
    print(f"  Total Surplus Collected: ${f05_res['total_surplus']:,.2f}")
    print(f"  Total Deficit Incurred:  ${f05_res['total_deficit']:,.2f}")
    print(f"  Net Shipping Position:   ${f05_res['net_shipping_position']:,.2f}")

    # -------------------------------------------------------------------
    # F09: Channel Margin Divergence
    # -------------------------------------------------------------------
    f09_res = compute_f09(df_orders, df_line_items)
    print("\n--- F09: Channel Margin Divergence ---")
    print(f"  Primary Benchmark Channel: {f09_res['primary_channel']}")
    print(f"  Total Marketplace Margin Loss: ${f09_res['total_divergence_loss']:,.2f}")
    for ch, data in f09_res["channel_breakdown"].items():
        print(f"    - {ch.upper():8s} ({data['units_sold']:,} units): loss = ${data['divergence_loss']:,.2f}")

    # -------------------------------------------------------------------
    # F10: Return & Refund Profitability
    # -------------------------------------------------------------------
    f10_res = compute_f10(df_orders, df_line_items)
    print("\n--- F10: Return & Refund Profitability ---")
    print(f"  Total Items Returned: {f10_res['total_returns']:,} (Return Rate: {f10_res['return_rate_pct']:.1f}%)")
    print(f"  Refunded Revenue: ${f10_res['total_refunded_amount']:,.2f}")
    print(f"  Restocking & Logistics Costs: ${f10_res['total_restocking_cost']:,.2f}")
    print(f"  Total True Return Loss: ${f10_res['total_f10_loss']:,.2f}")

    # -------------------------------------------------------------------
    # F11: Product True Net Profit
    # -------------------------------------------------------------------
    f11_df = compute_f11(df_orders, df_line_items)
    unprofitable_skus = f11_df[f11_df["is_unprofitable_sku"]]
    print("\n--- F11: SKU True Net Profit ---")
    print(f"  Total Active SKUs Evaluated: {len(f11_df):,}")
    print(f"  Unprofitable SKUs Flagged: {len(unprofitable_skus):,} ({len(unprofitable_skus)/len(f11_df)*100:.1f}%)")
    print(f"  Total Net Profit Generated: ${f11_df['total_net_profit'].sum():,.2f}")

    # -------------------------------------------------------------------
    # F12: Revenue Leakage Ratio
    # -------------------------------------------------------------------
    f12_res = compute_f12(df_orders, df_line_items)
    print("\n--- F12: Overall Revenue Leakage Ratio ---")
    print(f"  Gross Revenue: ${f12_res['gross_sales']:,.2f}")
    print(f"  Total Cumulative Financial Leakage: ${f12_res['total_leakage']:,.2f}")
    print(f"  Revenue Leakage Ratio: {f12_res['leakage_ratio_pct']:.2f}%")
    print(f"  Net Revenue Retention: {f12_res['revenue_retention_pct']:.2f}%")
    print("  Leak Breakdown:")
    for leak_type, amt in f12_res["leak_breakdown"].items():
        print(f"    - {leak_type:25s}: ${amt:,.2f} ({amt/f12_res['gross_sales']*100:.2f}%)")
    
    print("\n" + "=" * 70)
    print("ALL SCORING ENGINES (F01–F12) EXECUTED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    run_all()

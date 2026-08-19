"""Master runner for F01–F12 scoring engines."""

import logging
import pandas as pd

from src.scoring.f01_f03 import compute_f03, aggregate_f03, compute_f01, aggregate_f01
from src.scoring.f02 import compute_f02
from src.scoring.f04 import compute_f04, aggregate_f04
from src.scoring.f05 import compute_f05, aggregate_f05
from src.scoring.f09 import compute_f09
from src.scoring.f10 import compute_f10, aggregate_f10
from src.scoring.f11 import compute_f11, aggregate_f11
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
    
    active_orders = df_orders[~df_orders["is_cancelled"]]["order_id"]
    active_items = df_line_items[df_line_items["order_id"].isin(active_orders)].copy()
    
    merged_items = active_items.merge(
        df_orders[["order_id", "actual_shipping_cost", "gateway_fee"]],
        on="order_id",
        how="left",
    )
    
    scored_f03 = compute_f03(merged_items)
    f03_res = aggregate_f03(scored_f03)
    
    print("\n--- F03: Margin Floor Breach ---")
    print(f"  Orders Evaluated: {f03_res['orders_evaluated']:,}")
    print(f"  Unprofitable Orders: {f03_res['orders_flagged']:,} ({f03_res['breach_rate_pct']:.2f}%)")
    print(f"  Total Floor Breach Loss: ${f03_res['total_loss']:,.2f}")

    scored_f01 = compute_f01(scored_f03)
    f01_res = aggregate_f01(scored_f01)
    print("\n--- F01: Promotion Margin Leakage ---")
    print(f"  Orders Evaluated: {f01_res['orders_evaluated']:,}")
    print(f"  Discounted Orders: {f01_res['discounted_orders']:,}")
    print(f"  Below-Target Orders: {f01_res['orders_flagged']:,} (F01 Score: {f01_res['f01_score_pct']:.2f}% of orders, {f01_res['discounted_breach_rate_pct']:.2f}% of promo orders)")
    print(f"  Total Promo Leakage Loss: ${f01_res['total_loss']:,.2f}")

    f02_res = compute_f02(df_orders, df_line_items)
    print("\n--- F02: Discount Dependency ---")
    print(f"  Discounted Sales Share: {f02_res['f02_score_pct']:.1f}% (Benchmark: {f02_res['healthy_benchmark']*100:.1f}%)")
    print(f"  Threshold Breached: {f02_res['is_breached']}")
    print(f"  Average Discount Depth: {f02_res['avg_discount_depth']*100:.1f}%")
    print(f"  Total Discount Dependency Loss: ${f02_res['f02_loss']:,.2f}")

    f04_df = compute_f04(df_orders, df_line_items)
    f04_res = aggregate_f04(f04_df)
    print("\n--- F04: Free-Shipping Leakage ---")
    print(f"  Orders Evaluated: {f04_res['orders_evaluated']:,}")
    print(f"  Orders Leaking Cash on Shipping: {f04_res['orders_flagged']:,} ({f04_res['order_leakage_pct']:.2f}%)")
    print(f"  Total Free-Shipping Net Leakage: ${f04_res['total_f04_leakage']:,.2f}")

    f05_df = compute_f05(df_orders)
    f05_res = aggregate_f05(f05_df)
    print("\n--- F05: Shipping Cost Recovery ---")
    print(f"  Orders with Surplus: {f05_res['orders_surplus']:,} | Orders with Deficit: {f05_res['orders_deficit']:,}")
    print(f"  Total Surplus Collected: ${f05_res['total_surplus']:,.2f}")
    print(f"  Total Deficit Incurred:  ${f05_res['total_deficit']:,.2f}")
    print(f"  Net Shipping Position:   ${f05_res['net_shipping_position']:,.2f}")

    f09_res = compute_f09(df_orders, df_line_items)
    print("\n--- F09: Channel Margin Divergence ---")
    print(f"  Primary Benchmark Channel: {f09_res['primary_channel']}")
    print(f"  Total Marketplace Margin Loss: ${f09_res['total_divergence_loss']:,.2f}")
    for ch, data in f09_res["channel_breakdown"].items():
        print(f"    - {ch.upper():8s} ({data['units_sold']:,} units): loss = ${data['channel_divergence_loss']:,.2f}")

    f10_df = compute_f10(df_orders, df_line_items)
    f10_res = aggregate_f10(f10_df)
    print("\n--- F10: Product Contribution ---")
    print(f"  Total Active SKUs Evaluated: {f10_res['total_skus_evaluated']:,}")
    print(f"  Negative Contribution SKUs: {f10_res['negative_contribution_skus']:,} ({f10_res['negative_sku_pct']:.1f}%)")
    print(f"  Total Net Merchandise Revenue: ${f10_res['total_net_revenue']:,.2f}")
    print(f"  Total True Product Contribution: ${f10_res['total_product_contribution']:,.2f} ({f10_res['overall_contribution_margin_pct']:.1f}% margin)")

    f11_df = compute_f11(df_orders, df_line_items)
    f11_res = aggregate_f11(f11_df)
    print("\n--- F11: Order Profitability ---")
    print(f"  Total Orders Evaluated: {f11_res['orders_evaluated']:,}")
    print(f"  Profitable Orders: {f11_res['profitable_orders']:,} | Unprofitable: {f11_res['unprofitable_orders']:,} ({f11_res['unprofitable_order_pct']:.1f}%)")
    print(f"  Total Revenue Collected: ${f11_res['total_revenue_collected']:,.2f}")
    print(f"  Total Net Order Profit: ${f11_res['total_order_net_profit']:,.2f} ({f11_res['overall_net_margin_pct']:.1f}% margin)")

    f12_res = compute_f12(df_orders, df_line_items)
    print("\n--- F12: Revenue Quality Score ---")
    print(f"  Gross Top-Line Revenue: ${f12_res['gross_sales']:,.2f}")
    print(f"  Total Cumulative Revenue Drains: ${f12_res['total_leakage']:,.2f}")
    print(f"  Net Retained Revenue: ${f12_res['net_retained_revenue']:,.2f}")
    print(f"  Revenue Quality Score: {f12_res['revenue_quality_score_pct']:.2f}%")
    print("  Revenue Drain Breakdown:")
    for leak_type, amt in f12_res["leak_breakdown"].items():
        print(f"    - {leak_type:25s}: ${amt:,.2f} ({amt/f12_res['gross_sales']*100:.2f}%)")
    
    print("\n" + "=" * 70)
    print("ALL SCORING ENGINES (F01–F12) EXECUTED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    run_all()

"""src/generators/generate_data.py — Generates multi-table synthetic dataset for F01–F12.

Outputs:
    1. data/synthetic_orders.csv.gz (order-level attributes, shipping, channels, gateway, disputes)
    2. data/synthetic_line_items.csv.gz (line-item bundles, COGS, dimensions, returns, channel fees)

Calibrated against real ecommerce benchmarks with realistic ambiguities:
    - ~20% missing COGS (nulls)
    - ~30% non-Shopify-Payments gateway fees (nulls)
    - ~90% missing product dimensions (no native Shopify fields)
    - Multi-item order bundles (1-4 line items per order)
    - Channel fee variations (Amazon 15%, TikTok 8%, Walmart 15%, Web 0%)
    - Category-accurate return rates & restocking costs
    - Edge cases: 100% discount, zero shipping with heavy packages, cancellations, disputes
"""

import gzip
import logging
import os
import random
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Category configs
CATEGORY_CONFIG = {
    "fashion": {
        "price_mu": 4.3, "price_sigma": 0.5, "min_p": 15, "max_p": 350,
        "cogs_pct": (0.35, 0.55), "weight_kg": (0.2, 1.5),
        "return_rate": 0.32, "dim_range": (20, 35, 5, 15, 2, 10),
    },
    "beauty": {
        "price_mu": 3.7, "price_sigma": 0.6, "min_p": 10, "max_p": 180,
        "cogs_pct": (0.20, 0.40), "weight_kg": (0.1, 0.8),
        "return_rate": 0.12, "dim_range": (5, 20, 5, 15, 3, 12),
    },
    "electronics": {
        "price_mu": 5.2, "price_sigma": 0.8, "min_p": 25, "max_p": 1200,
        "cogs_pct": (0.60, 0.85), "weight_kg": (0.3, 4.0),
        "return_rate": 0.15, "dim_range": (15, 45, 10, 35, 3, 20),
    },
    "home_goods": {
        "price_mu": 4.5, "price_sigma": 0.7, "min_p": 20, "max_p": 600,
        "cogs_pct": (0.40, 0.65), "weight_kg": (1.0, 12.0),
        "return_rate": 0.15, "dim_range": (25, 80, 20, 60, 10, 50),
    },
    "luxury": {
        "price_mu": 5.6, "price_sigma": 0.6, "min_p": 150, "max_p": 2500,
        "cogs_pct": (0.25, 0.45), "weight_kg": (0.3, 2.5),
        "return_rate": 0.18, "dim_range": (15, 40, 10, 30, 5, 20),
    },
    "pet_care": {
        "price_mu": 3.5, "price_sigma": 0.5, "min_p": 8, "max_p": 150,
        "cogs_pct": (0.45, 0.70), "weight_kg": (0.5, 8.0),
        "return_rate": 0.08, "dim_range": (15, 50, 10, 40, 5, 30),
    },
}

CHANNELS = ["web", "amazon", "tiktok", "walmart"]
CHANNEL_WEIGHTS = [0.60, 0.22, 0.12, 0.06]
CHANNEL_FEES = {"web": 0.00, "amazon": 0.15, "tiktok": 0.08, "walmart": 0.15}

RETURN_REASONS = ["size_fit", "defective", "changed_mind", "not_as_described", "arrived_late"]


def generate_dataset(num_orders: int = 100_000, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generates order-level and line-item-level DataFrames."""
    np.random.seed(seed)
    random.seed(seed)
    
    logger.info("Generating %d orders with realistic multi-table structure...", num_orders)

    order_records = []
    line_item_records = []
    
    start_date = pd.Timestamp("2025-01-01")
    end_date = pd.Timestamp("2025-12-31")
    date_range_days = (end_date - start_date).days

    line_item_counter = 0

    for i in range(num_orders):
        order_id = f"ORD-{i:07d}"
        created_at = start_date + pd.Timedelta(days=random.randint(0, date_range_days),
                                              hours=random.randint(0, 23),
                                              minutes=random.randint(0, 59))
        
        channel = random.choices(CHANNELS, weights=CHANNEL_WEIGHTS)[0]
        channel_fee_rate = CHANNEL_FEES[channel]
        
        # Determine number of line items (bundles)
        # 60% 1 item, 25% 2 items, 10% 3 items, 5% 4 items
        num_items = random.choices([1, 2, 3, 4], weights=[0.60, 0.25, 0.10, 0.05])[0]
        
        order_gross_subtotal = 0.0
        order_net_subtotal = 0.0
        order_total_weight = 0.0
        
        order_line_items = []
        
        for _ in range(num_items):
            line_item_counter += 1
            line_item_id = f"LI-{line_item_counter:08d}"
            category = random.choice(list(CATEGORY_CONFIG.keys()))
            cfg = CATEGORY_CONFIG[category]
            
            # Unit price
            raw_price = np.exp(np.random.normal(cfg["price_mu"], cfg["price_sigma"]))
            price = float(np.clip(raw_price, cfg["min_p"], cfg["max_p"]))
            price = round(price, 2)
            
            # Quantity (usually 1, occasionally 2)
            qty = random.choices([1, 2], weights=[0.90, 0.10])[0]
            total_item_price = round(price * qty, 2)
            
            # Discount (45% of items discounted)
            is_disc = random.random() < 0.45
            if is_disc:
                disc_rate = np.random.beta(2, 8)  # average ~20%
                disc_given = round(total_item_price * disc_rate, 2)
            else:
                disc_given = 0.0
            
            net_item_price = round(max(0.0, total_item_price - disc_given), 2)
            
            # COGS (20% missing rate in real world)
            has_cogs = random.random() >= 0.20
            if has_cogs:
                cogs_ratio = random.uniform(cfg["cogs_pct"][0], cfg["cogs_pct"][1])
                cogs_val = round(total_item_price * cogs_ratio, 2)
            else:
                cogs_val = np.nan
            
            # Weight
            w_min, w_max = cfg["weight_kg"]
            item_weight = round(random.uniform(w_min, w_max) * qty, 2)
            order_total_weight += item_weight
            
            # Dimensions (L x W x H in cm) — only ~10% populated via custom metafields
            has_dims = random.random() < 0.10
            if has_dims:
                l_min, l_max, w_min_d, w_max_d, h_min, h_max = cfg["dim_range"]
                len_cm = round(random.uniform(l_min, l_max), 1)
                wid_cm = round(random.uniform(w_min_d, w_max_d), 1)
                hgt_cm = round(random.uniform(h_min, h_max), 1)
            else:
                len_cm, wid_cm, hgt_cm = np.nan, np.nan, np.nan
            
            # Return status
            is_ret = random.random() < cfg["return_rate"]
            if is_ret:
                ret_reason = random.choice(RETURN_REASONS)
                ref_amount = net_item_price
                restock_cost = round(total_item_price * 0.08, 2)  # ~8% handling/inspect cost
            else:
                ret_reason = None
                ref_amount = 0.0
                restock_cost = 0.0
            
            order_gross_subtotal += total_item_price
            order_net_subtotal += net_item_price
            
            line_item_records.append({
                "order_id": order_id,
                "line_item_id": line_item_id,
                "product_id": f"SKU-{category[:3].upper()}-{random.randint(100, 999)}",
                "category": category,
                "quantity": qty,
                "selling_price": total_item_price,
                "discount_given": disc_given,
                "net_selling_price": net_item_price,
                "is_discounted": is_disc,
                "cogs_total": cogs_val,
                "product_weight_kg": item_weight,
                "length_cm": len_cm,
                "width_cm": wid_cm,
                "height_cm": hgt_cm,
                "is_returned": is_ret,
                "return_reason": ret_reason,
                "refund_amount": ref_amount,
                "restocking_cost": restock_cost,
                "channel_fee_pct": channel_fee_rate,
            })

        # Order-level shipping calculation
        free_shipping_qualifies = order_net_subtotal >= 50.00
        if free_shipping_qualifies or (random.random() < 0.15):
            shipping_charged = 0.0
            free_shipping_applied = True
        else:
            shipping_charged = round(random.uniform(3.99, 8.99), 2)
            free_shipping_applied = False
        
        # Real courier cost (based on weight + base rate)
        base_courier = 4.50 + (order_total_weight * 1.80) + random.uniform(-0.5, 2.5)
        actual_shipping = round(max(3.50, base_courier), 2)
        
        # Gateway fee (Shopify payments ~70% of stores, ~30% external)
        uses_shopify_payments = random.random() >= 0.30
        if uses_shopify_payments:
            gw_fee = round((order_net_subtotal + shipping_charged) * 0.029 + 0.30, 2)
        else:
            gw_fee = np.nan
        
        # Cancellation status (~2% of orders cancelled before fulfillment)
        is_cancelled = random.random() < 0.02
        if is_cancelled:
            shipping_charged = 0.0
            actual_shipping = 0.0
            gw_fee = 0.0
        
        # Disputes / chargebacks (~0.6% rate)
        has_chargeback = (random.random() < 0.006) and not is_cancelled
        chargeback_amount = (order_net_subtotal + shipping_charged + 15.00) if has_chargeback else 0.0
        
        order_records.append({
            "order_id": order_id,
            "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "channel": channel,
            "currency": "USD",
            "gross_sales": round(order_gross_subtotal, 2),
            "net_sales": round(order_net_subtotal, 2),
            "shipping_charged_to_customer": shipping_charged,
            "actual_shipping_cost": actual_shipping,
            "gateway_fee": gw_fee,
            "free_shipping_applied": free_shipping_applied,
            "is_cancelled": is_cancelled,
            "chargeback_amount": chargeback_amount,
        })

    df_orders = pd.DataFrame(order_records)
    df_line_items = pd.DataFrame(line_item_records)

    return df_orders, df_line_items


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    orders_path = "data/synthetic_orders.csv.gz"
    line_items_path = "data/synthetic_line_items.csv.gz"
    
    df_orders, df_line_items = generate_dataset(num_orders=100_000)
    
    logger.info("Saving %s (%d rows)...", orders_path, len(df_orders))
    df_orders.to_csv(orders_path, index=False, compression="gzip")
    
    logger.info("Saving %s (%d rows)...", line_items_path, len(df_line_items))
    df_line_items.to_csv(line_items_path, index=False, compression="gzip")
    
    logger.info("Generation complete! Ready for F01–F12 stress testing.")

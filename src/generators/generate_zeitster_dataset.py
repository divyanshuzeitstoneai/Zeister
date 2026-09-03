"""src/generators/generate_zeitster_dataset.py — Full 16-table Zeitster synthetic dataset generator.

Generates a realistic, multi-tenant synthetic dataset for formula testing per the
Zeitster dataset generation spec. Produces one CSV per table in data/zeitster_*.csv.gz.

Tables generated (16 total):
  1. merchants           — dim_merchant
  2. customers           — dim_customer
  3. orders              — fact_orders
  4. line_items           — fact_order_line_items
  5. transactions         — fact_transactions
  6. refunds              — fact_refunds
  7. shipping_fulfillments — fact_shipping_fulfillments
  8. disputes             — fact_disputes
  9. subscriptions        — dim_subscriptions
  10. subscription_events — fact_subscription_events
  11. products_variants   — dim_products_variants
  12. metafields          — dim_metafields (current Shopify mirror)
  13. metafield_history   — fact_metafield_history (Zeitster append-only log)
  14. support_tickets     — fact_support_tickets
  15. category_cogs_benchmarks — ref_category_cogs
  16. category_margin_targets  — ref_category_margin_targets

Field-status null rates (from Phase 4 mapping):
  ✅ VERIFIED  — never null on valid orders
  ⚠️ PARTIAL   — ~15-20% null (manual/offline orders)
  ⚙️ METAFIELD — null pre-cutover; ~15-30% null post-cutover
  ❌ EXTERNAL  — ~5-10% null (late/missing 3PL/gateway data)
  🧮 DERIVED   — never stored; computed from other fields
"""

from __future__ import annotations

import gzip
import logging
import os
import random
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS & CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

SEED = 42
DATE_START = date(2025, 1, 1)
DATE_END = date(2026, 6, 30)
ORDERS_PER_MERCHANT = 600
CUSTOMERS_PER_MERCHANT = 80
PRODUCTS_PER_MERCHANT = 40

# ── Merchant Definitions ─────────────────────────────────────────────

MERCHANT_DEFS = [
    {"merchant_id": "M001", "merchant_name": "StyleVault", "primary_category": "fashion",
     "region": "US", "subscription_start_date": "2025-01-15", "cutover_date": "2025-06-01",
     "data_quality_tier": "clean"},
    {"merchant_id": "M002", "merchant_name": "GlowUp Beauty", "primary_category": "beauty",
     "region": "US", "subscription_start_date": "2025-02-01", "cutover_date": "2025-07-15",
     "data_quality_tier": "clean"},
    {"merchant_id": "M003", "merchant_name": "TechNova", "primary_category": "electronics",
     "region": "US", "subscription_start_date": "2025-03-01", "cutover_date": "2025-08-01",
     "data_quality_tier": "mixed"},
    {"merchant_id": "M004", "merchant_name": "CozyNest Home", "primary_category": "home_goods",
     "region": "UK", "subscription_start_date": "2025-01-01", "cutover_date": "2025-09-01",
     "data_quality_tier": "clean"},
    {"merchant_id": "M005", "merchant_name": "PawPalace", "primary_category": "pet_care",
     "region": "US", "subscription_start_date": "2025-04-01", "cutover_date": "2025-10-01",
     "data_quality_tier": "messy"},
    {"merchant_id": "M006", "merchant_name": "FreshBite", "primary_category": "food_bev",
     "region": "CA", "subscription_start_date": "2025-02-15", "cutover_date": "2025-06-15",
     "data_quality_tier": "mixed"},
    {"merchant_id": "M007", "merchant_name": "LuxeAura", "primary_category": "luxury",
     "region": "US", "subscription_start_date": "2025-01-01", "cutover_date": "2025-07-01",
     "data_quality_tier": "clean"},
    {"merchant_id": "M008", "merchant_name": "UrbanThreads", "primary_category": "fashion",
     "region": "UK", "subscription_start_date": "2025-05-01", "cutover_date": "2025-11-01",
     "data_quality_tier": "messy"},
    {"merchant_id": "M009", "merchant_name": "Sparkle Skin", "primary_category": "beauty",
     "region": "AU", "subscription_start_date": "2025-03-15", "cutover_date": "2025-08-15",
     "data_quality_tier": "mixed"},
    {"merchant_id": "M010", "merchant_name": "GadgetZone", "primary_category": "electronics",
     "region": "US", "subscription_start_date": "2025-06-01", "cutover_date": "2025-09-15",
     "data_quality_tier": "messy"},
]

REGION_CURRENCY = {"US": "USD", "UK": "GBP", "CA": "CAD", "AU": "AUD"}

# ── Category Configuration ───────────────────────────────────────────

CATEGORY_CONFIG = {
    "fashion": {
        "price_range": (15, 350), "cogs_pct": (0.35, 0.55),
        "weight_kg": (0.2, 1.5), "return_rate": 0.32,
        "benchmark_cogs": 35.00, "dim_range": (20, 35, 5, 15, 2, 10),
    },
    "beauty": {
        "price_range": (10, 180), "cogs_pct": (0.20, 0.40),
        "weight_kg": (0.1, 0.8), "return_rate": 0.12,
        "benchmark_cogs": 18.50, "dim_range": (5, 20, 5, 15, 3, 12),
    },
    "electronics": {
        "price_range": (25, 1200), "cogs_pct": (0.60, 0.85),
        "weight_kg": (0.3, 4.0), "return_rate": 0.15,
        "benchmark_cogs": 120.00, "dim_range": (15, 45, 10, 35, 3, 20),
    },
    "home_goods": {
        "price_range": (20, 600), "cogs_pct": (0.40, 0.65),
        "weight_kg": (1.0, 12.0), "return_rate": 0.15,
        "benchmark_cogs": 45.00, "dim_range": (25, 80, 20, 60, 10, 50),
    },
    "luxury": {
        "price_range": (150, 2500), "cogs_pct": (0.25, 0.45),
        "weight_kg": (0.3, 2.5), "return_rate": 0.18,
        "benchmark_cogs": 350.00, "dim_range": (15, 40, 10, 30, 5, 20),
    },
    "pet_care": {
        "price_range": (8, 150), "cogs_pct": (0.45, 0.70),
        "weight_kg": (0.5, 8.0), "return_rate": 0.08,
        "benchmark_cogs": 22.00, "dim_range": (15, 50, 10, 40, 5, 30),
    },
    "food_bev": {
        "price_range": (5, 80), "cogs_pct": (0.40, 0.65),
        "weight_kg": (0.3, 5.0), "return_rate": 0.05,
        "benchmark_cogs": 12.00, "dim_range": (10, 30, 8, 20, 5, 15),
    },
}

CHANNELS = ["web", "amazon", "tiktok", "retail"]
CHANNEL_WEIGHTS = [0.60, 0.22, 0.10, 0.08]
CHANNEL_FEES = {"web": 0.00, "amazon": 0.15, "tiktok": 0.08, "retail": 0.00}

RETURN_REASONS = ["size_fit", "defective", "changed_mind", "not_as_described", "arrived_late"]
DISPUTE_STATUSES = ["NEEDS_RESPONSE", "UNDER_REVIEW", "WON", "LOST"]
ORDER_STATUSES = ["COMPLETED", "PARTIALLY_FULFILLED", "UNFULFILLED"]
SUBSCRIPTION_PLANS = [
    {"plan_id": "PLAN-M-30", "plan_type": "MONTHLY", "billing_interval": "MONTHLY", "amount": 30.00},
    {"plan_id": "PLAN-M-50", "plan_type": "MONTHLY", "billing_interval": "MONTHLY", "amount": 50.00},
    {"plan_id": "PLAN-M-80", "plan_type": "MONTHLY", "billing_interval": "MONTHLY", "amount": 80.00},
    {"plan_id": "PLAN-M-100", "plan_type": "MONTHLY", "billing_interval": "MONTHLY", "amount": 100.00},
    {"plan_id": "PLAN-A-500", "plan_type": "ANNUAL", "billing_interval": "ANNUAL", "amount": 500.00},
    {"plan_id": "PLAN-A-1000", "plan_type": "ANNUAL", "billing_interval": "ANNUAL", "amount": 1000.00},
]

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Daniel", "Lisa", "Matthew", "Nancy",
    "Anthony", "Betty", "Mark", "Margaret", "Donald", "Sandra", "Steven", "Ashley",
    "Paul", "Kimberly", "Andrew", "Emily", "Joshua", "Donna", "Kenneth", "Michelle",
    "Aisha", "Raj", "Wei", "Fatima", "Carlos", "Yuki", "Omar", "Priya", "Ivan", "Mei",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Patel", "Chen", "Kim", "Singh", "Nakamura", "Mueller", "Ivanov", "Ali", "Santos",
]

METAFIELD_KEYS = [
    ("shop", "custom", "target_margin_pct", "number_decimal"),
    ("product", "custom", "unit_cost_override", "number_decimal"),
    ("product", "custom", "length_cm", "number_decimal"),
    ("product", "custom", "width_cm", "number_decimal"),
    ("product", "custom", "height_cm", "number_decimal"),
    ("variant", "custom", "weight_override_kg", "number_decimal"),
    ("customer", "custom", "vip_tier", "single_line_text_field"),
    ("shop", "custom", "free_shipping_threshold", "number_decimal"),
]


# ═══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def rand_date(start: date, end: date) -> date:
    """Return a random date between start and end (inclusive)."""
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(0, delta)))


def rand_datetime(start: date, end: date) -> datetime:
    """Return a random datetime between start and end dates."""
    d = rand_date(start, end)
    return datetime(d.year, d.month, d.day,
                    random.randint(0, 23), random.randint(0, 59), random.randint(0, 59))


def fmt_dt(dt: datetime | date) -> str:
    """Format datetime to string."""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d")


def null_rate_for_tier(base_rate: float, tier: str) -> float:
    """Adjust null rate based on merchant data quality tier."""
    if tier == "clean":
        return base_rate * 0.5
    elif tier == "messy":
        return base_rate * 1.5
    return base_rate  # mixed


def maybe_null(value, rate: float):
    """Return None with given probability, otherwise return value."""
    if random.random() < rate:
        return None
    return value


def generate_price(category: str) -> float:
    """Generate a realistic price for a category using log-normal distribution."""
    cfg = CATEGORY_CONFIG[category]
    low, high = cfg["price_range"]
    mu = np.log((low + high) / 2)
    sigma = 0.5
    price = float(np.clip(np.exp(np.random.normal(mu, sigma)), low, high))
    return round(price, 2)


# ═══════════════════════════════════════════════════════════════════════
# TABLE GENERATORS
# ═══════════════════════════════════════════════════════════════════════

def gen_merchants() -> pd.DataFrame:
    """Generate the merchants dimension table."""
    logger.info("Generating merchants table...")
    return pd.DataFrame(MERCHANT_DEFS)


def gen_customers(merchants_df: pd.DataFrame) -> pd.DataFrame:
    """Generate customers for each merchant."""
    logger.info("Generating customers table...")
    rows = []
    for _, m in merchants_df.iterrows():
        mid = m["merchant_id"]
        sub_start = datetime.strptime(m["subscription_start_date"], "%Y-%m-%d").date()
        for i in range(1, CUSTOMERS_PER_MERCHANT + 1):
            cid = f"CUST-{mid}-{i:04d}"
            created = rand_date(sub_start - timedelta(days=365), DATE_END)
            lifetime = max(1, int(np.random.exponential(5)))
            rows.append({
                "customer_id": cid,
                "merchant_id": mid,
                "first_name": random.choice(FIRST_NAMES),
                "last_name": random.choice(LAST_NAMES),
                "email": f"{cid.lower().replace('-', '.')}@example.com",
                "created_at": fmt_dt(created),
                "is_vip": i <= int(CUSTOMERS_PER_MERCHANT * 0.10),  # top 10%
                "lifetime_orders": lifetime,
                "test_case_id": f"POP-{mid}-CUST-{i:04d}",
            })
    return pd.DataFrame(rows)


def gen_products_variants(merchants_df: pd.DataFrame) -> pd.DataFrame:
    """Generate product/variant catalog per merchant."""
    logger.info("Generating products_variants table...")
    rows = []
    for _, m in merchants_df.iterrows():
        mid = m["merchant_id"]
        primary_cat = m["primary_category"]
        # 70% products in primary category, 30% in other categories
        categories = list(CATEGORY_CONFIG.keys())
        for i in range(1, PRODUCTS_PER_MERCHANT + 1):
            cat = primary_cat if random.random() < 0.70 else random.choice(categories)
            cfg = CATEGORY_CONFIG[cat]
            pid = f"PROD-{mid}-{i:04d}"
            vid = f"VAR-{mid}-{i:04d}"
            base_price = generate_price(cat)
            cogs_ratio = random.uniform(cfg["cogs_pct"][0], cfg["cogs_pct"][1])
            # unit_cost: ~10% null to simulate unitCost gaps
            unit_cost = round(base_price * cogs_ratio, 2)
            unit_cost = maybe_null(unit_cost, 0.10)
            w_min, w_max = cfg["weight_kg"]
            rows.append({
                "product_id": pid,
                "variant_id": vid,
                "merchant_id": mid,
                "category": cat,
                "sku": f"SKU-{cat[:3].upper()}-{mid}-{i:03d}",
                "unit_cost": unit_cost,
                "weight_kg": round(random.uniform(w_min, w_max), 2),
                "is_sellable": True,
                "test_case_id": f"POP-{mid}-PROD-{i:04d}",
            })
    return pd.DataFrame(rows)


def gen_orders_and_line_items(
    merchants_df: pd.DataFrame,
    customers_df: pd.DataFrame,
    products_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate orders and line items for all merchants.

    Null rates:
      - actual_shipping_cost: ❌ EXTERNAL ~8% null
      - gateway_fee: ⚠️ PARTIAL ~18% null
    """
    logger.info("Generating orders and line_items tables...")
    order_rows = []
    li_rows = []
    li_counter = 0

    for _, m in merchants_df.iterrows():
        mid = m["merchant_id"]
        tier = m["data_quality_tier"]
        cutover = datetime.strptime(m["cutover_date"], "%Y-%m-%d").date()
        currency = REGION_CURRENCY.get(m["region"], "USD")

        m_customers = customers_df[customers_df["merchant_id"] == mid]["customer_id"].tolist()
        m_products = products_df[products_df["merchant_id"] == mid]

        for seq in range(1, ORDERS_PER_MERCHANT + 1):
            oid = f"ORD-{mid}-{seq:05d}"
            cid = random.choice(m_customers)
            created = rand_datetime(DATE_START, DATE_END)
            created_date = created.date()
            is_pre_cutover = created_date < cutover

            channel = random.choices(CHANNELS, weights=CHANNEL_WEIGHTS)[0]
            channel_fee_rate = CHANNEL_FEES[channel]

            # Number of line items: 60% single, 25% 2, 10% 3, 5% 4
            num_items = random.choices([1, 2, 3, 4], weights=[0.60, 0.25, 0.10, 0.05])[0]

            order_gross = 0.0
            order_discounts = 0.0
            order_cogs = 0.0
            order_weight = 0.0
            order_refunded = 0.0
            has_return = False
            all_cogs_present = True

            item_records = []
            for item_idx in range(num_items):
                li_counter += 1
                lid = f"LI-{mid}-{li_counter:07d}"

                # Pick a product from this merchant
                prod_row = m_products.sample(1).iloc[0]
                cat = prod_row["category"]
                cfg = CATEGORY_CONFIG[cat]

                # Price
                price = generate_price(cat)
                qty = random.choices([1, 2, 3], weights=[0.85, 0.12, 0.03])[0]
                gross_price = round(price * qty, 2)

                # Discount
                is_disc = random.random() < 0.40
                if is_disc:
                    disc_rate = min(np.random.beta(2, 8), 0.60)
                    discount_amount = round(gross_price * disc_rate, 2)
                else:
                    discount_amount = 0.0
                net_price = round(max(0.01, gross_price - discount_amount), 2)

                # COGS (✅ verified but ~10% null for unitCost gaps)
                cogs_null_rate = null_rate_for_tier(0.10, tier)
                has_cogs = random.random() >= cogs_null_rate
                if has_cogs:
                    cogs_ratio = random.uniform(cfg["cogs_pct"][0], cfg["cogs_pct"][1])
                    cogs = round(gross_price * cogs_ratio, 2)
                else:
                    cogs = None
                    all_cogs_present = False

                # Weight
                w_min, w_max = cfg["weight_kg"]
                item_weight = round(random.uniform(w_min, w_max) * qty, 2)
                order_weight += item_weight

                # Dimensions (⚙️ METAFIELD — null pre-cutover, ~70-85% present post-cutover)
                if is_pre_cutover:
                    length_cm, width_cm, height_cm = None, None, None
                else:
                    dim_rate = 0.75 if tier != "messy" else 0.55
                    if random.random() < dim_rate:
                        l_min, l_max, w_min_d, w_max_d, h_min, h_max = cfg["dim_range"]
                        length_cm = round(random.uniform(l_min, l_max), 1)
                        width_cm = round(random.uniform(w_min_d, w_max_d), 1)
                        height_cm = round(random.uniform(h_min, h_max), 1)
                    else:
                        length_cm, width_cm, height_cm = None, None, None

                # Returns
                is_returned = random.random() < cfg["return_rate"]
                current_quantity = 0 if is_returned else qty
                refund_amount = net_price if is_returned else 0.0
                restocking_cost = round(gross_price * 0.08, 2) if is_returned else 0.0

                if is_returned:
                    has_return = True
                    order_refunded += refund_amount

                order_gross += gross_price
                order_discounts += discount_amount
                if cogs is not None:
                    order_cogs += cogs

                item_records.append({
                    "line_item_id": lid,
                    "order_id": oid,
                    "product_id": prod_row["product_id"],
                    "variant_id": prod_row["variant_id"],
                    "category": cat,
                    "sku": prod_row["sku"],
                    "quantity": qty,
                    "current_quantity": current_quantity,
                    "gross_price": gross_price,
                    "discount_amount": discount_amount,
                    "net_price": net_price,
                    "cogs": cogs,
                    "actual_cogs": cogs,  # alias for category3_* compat
                    "category_avg_cogs": cfg["benchmark_cogs"],
                    "product_weight_kg": item_weight,
                    "length_cm": length_cm,
                    "width_cm": width_cm,
                    "height_cm": height_cm,
                    "is_returned": is_returned,
                    "is_sellable": not is_returned,  # for category3_* compat
                    "refund_amount": refund_amount,
                    "restocking_cost": restocking_cost,
                    "channel_fee_pct": channel_fee_rate,
                    "test_case_id": f"POP-{mid}-ORD-{seq:05d}-LI-{item_idx + 1}",
                })

            li_rows.extend(item_records)

            # Order-level calculations
            net_sales = round(order_gross - order_discounts, 2)
            discount_pct = round(order_discounts / order_gross, 4) if order_gross > 0 else 0.0

            # Shipping
            free_ship_qualifies = net_sales >= 50.00
            if free_ship_qualifies or random.random() < 0.15:
                shipping_charged = 0.0
            else:
                shipping_charged = round(random.uniform(3.99, 12.99), 2)

            # Actual shipping cost (❌ EXTERNAL — ~8% missing/late)
            ship_null_rate = null_rate_for_tier(0.08, tier)
            base_ship = 4.50 + (order_weight * 1.80) + random.uniform(-0.5, 2.5)
            actual_shipping = round(max(3.50, base_ship), 2)
            actual_shipping = maybe_null(actual_shipping, ship_null_rate)

            # Gateway fee (⚠️ PARTIAL — ~18% null on non-Shopify-Payments stores)
            gw_null_rate = null_rate_for_tier(0.18, tier)
            if random.random() >= gw_null_rate:
                gateway_fee = round((net_sales + shipping_charged) * 0.029 + 0.30, 2)
            else:
                gateway_fee = None

            # Cancellation (~2%)
            is_cancelled = random.random() < 0.02
            if is_cancelled:
                completed_status = "CANCELLED"
                shipping_charged = 0.0
                actual_shipping = 0.0
                gateway_fee = 0.0
                order_refunded = net_sales  # full refund on cancel
            else:
                completed_status = random.choices(
                    ORDER_STATUSES, weights=[0.90, 0.05, 0.05]
                )[0]

            total_received = round(net_sales + shipping_charged, 2)

            # Disputes (~0.6%)
            has_dispute = random.random() < 0.006 and not is_cancelled
            dispute_status = random.choice(DISPUTE_STATUSES) if has_dispute else "NONE"
            chargeback_amount = round(net_sales + 15.00, 2) if has_dispute else 0.0

            order_rows.append({
                "order_id": oid,
                "merchant_id": mid,
                "customer_id": cid,
                "created_at": fmt_dt(created),
                "order_date": fmt_dt(created),  # alias for category3_* compat
                "channel": channel,
                "currency": currency,
                "gross_sales": round(order_gross, 2),
                "net_sales": net_sales,
                "net_paid_amount": net_sales,  # alias for category3_* compat
                "total_discounts": round(order_discounts, 2),
                "current_subtotal": net_sales,
                "subtotal_price": net_sales,
                "discount_pct": discount_pct,
                "shipping_charged_to_customer": shipping_charged,
                "shipping_charged": shipping_charged,  # alias for category3_* compat
                "actual_shipping_cost": actual_shipping,
                "gateway_fee": gateway_fee,
                "total_received": total_received,
                "total_refunded": round(order_refunded, 2),
                "total_refunded_amount": round(order_refunded, 2),  # alias for category3_* compat
                "dispute_status": dispute_status,
                "chargeback_amount": chargeback_amount,
                "completed_order_status": completed_status,
                "is_cancelled": is_cancelled,
                "source_name": channel,
                "test_case_id": f"POP-{mid}-ORD-{seq:05d}",
            })

    return pd.DataFrame(order_rows), pd.DataFrame(li_rows)


def gen_transactions(orders_df: pd.DataFrame) -> pd.DataFrame:
    """Generate transaction records for each order.

    fees_amount: ⚠️ PARTIAL — null on manual/offline orders (~15-20%).
    """
    logger.info("Generating transactions table...")
    rows = []
    tx_counter = 0

    for _, o in orders_df.iterrows():
        tx_counter += 1
        tid = f"TX-{tx_counter:07d}"
        is_manual = o["channel"] == "retail"

        # For cancelled orders, transaction is FAILED or REFUNDED
        if o["is_cancelled"]:
            status = "REFUNDED"
        elif o["dispute_status"] != "NONE":
            status = "DISPUTED"
        else:
            status = random.choices(
                ["SUCCESS", "SUCCESS", "SUCCESS", "PENDING"],
                weights=[0.95, 0.02, 0.02, 0.01],
            )[0]

        # Gateway fees null on manual/retail orders (~15-20%)
        if is_manual or random.random() < 0.15:
            fees = None
        else:
            fees = o["gateway_fee"]

        rows.append({
            "transaction_id": tid,
            "order_id": o["order_id"],
            "gateway_name": "shopify_payments" if not is_manual else "manual",
            "status": status,
            "fees_amount": fees,
            "captured_at": o["created_at"],
            "test_case_id": o["test_case_id"].replace("ORD", "TX"),
        })

    return pd.DataFrame(rows)


def gen_refunds(orders_df: pd.DataFrame, line_items_df: pd.DataFrame) -> pd.DataFrame:
    """Generate refund records for returned line items."""
    logger.info("Generating refunds table...")
    rows = []
    refund_counter = 0

    returned_items = line_items_df[line_items_df["is_returned"] == True]
    # Group by order
    for oid, group in returned_items.groupby("order_id"):
        refund_counter += 1
        order_row = orders_df[orders_df["order_id"] == oid]
        if order_row.empty:
            continue
        order_row = order_row.iloc[0]

        ref_li_ids = ",".join(group["line_item_id"].tolist())
        refund_amount = round(group["refund_amount"].sum(), 2)
        order_date = datetime.strptime(order_row["created_at"], "%Y-%m-%d %H:%M:%S")
        refund_date = order_date + timedelta(days=random.randint(3, 30))

        rows.append({
            "refund_id": f"REF-{refund_counter:06d}",
            "order_id": oid,
            "refund_line_item_ids": ref_li_ids,
            "refund_amount": refund_amount,
            "refund_date": fmt_dt(refund_date),
            "reason": random.choice(RETURN_REASONS),
            "test_case_id": order_row["test_case_id"].replace("ORD", "REF"),
        })

    # Also add refunds for cancelled orders (full order refund)
    cancelled = orders_df[orders_df["is_cancelled"] == True]
    for _, o in cancelled.iterrows():
        refund_counter += 1
        order_date = datetime.strptime(o["created_at"], "%Y-%m-%d %H:%M:%S")
        rows.append({
            "refund_id": f"REF-{refund_counter:06d}",
            "order_id": o["order_id"],
            "refund_line_item_ids": "ALL",
            "refund_amount": o["total_refunded"],
            "refund_date": fmt_dt(order_date + timedelta(days=random.randint(0, 3))),
            "reason": "order_cancelled",
            "test_case_id": o["test_case_id"].replace("ORD", "REF-CANCEL"),
        })

    return pd.DataFrame(rows)


def gen_shipping_fulfillments(orders_df: pd.DataFrame) -> pd.DataFrame:
    """Generate shipping fulfillment records.

    actual_shipping_cost: ❌ EXTERNAL — ~8% missing (late 3PL data).
    """
    logger.info("Generating shipping_fulfillments table...")
    rows = []
    ful_counter = 0

    non_cancelled = orders_df[orders_df["is_cancelled"] == False]
    for _, o in non_cancelled.iterrows():
        ful_counter += 1
        carriers = ["FedEx", "UPS", "USPS", "DHL", "Delhivery", "ShipRocket"]
        statuses = ["DELIVERED", "DELIVERED", "DELIVERED", "IN_TRANSIT", "OUT_FOR_DELIVERY"]

        # actual_shipping_cost: ~8% null (simulating late 3PL invoice)
        actual_cost = o["actual_shipping_cost"]  # may already be None from order gen

        rows.append({
            "fulfillment_id": f"FUL-{ful_counter:07d}",
            "order_id": o["order_id"],
            "tracking_carrier": random.choice(carriers),
            "tracking_number": f"TRK{random.randint(100000000, 999999999)}",
            "actual_shipping_cost": actual_cost,
            "delivery_status": random.choice(statuses),
            "test_case_id": o["test_case_id"].replace("ORD", "FUL"),
        })

    return pd.DataFrame(rows)


def gen_disputes(orders_df: pd.DataFrame) -> pd.DataFrame:
    """Generate dispute records for orders with dispute_status != NONE."""
    logger.info("Generating disputes table...")
    rows = []
    disp_counter = 0

    disputed = orders_df[orders_df["dispute_status"] != "NONE"]
    for _, o in disputed.iterrows():
        disp_counter += 1
        order_date = datetime.strptime(o["created_at"], "%Y-%m-%d %H:%M:%S")
        disp_date = order_date + timedelta(days=random.randint(15, 60))

        rows.append({
            "dispute_id": f"DISP-{disp_counter:05d}",
            "order_id": o["order_id"],
            "status": o["dispute_status"],
            "amount": o["chargeback_amount"],
            "created_at": fmt_dt(disp_date),
            "test_case_id": o["test_case_id"].replace("ORD", "DISP"),
        })

    return pd.DataFrame(rows)


def gen_subscriptions(
    customers_df: pd.DataFrame,
    merchants_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generate subscription records. Focus on merchants M001, M002, M006, M007 as subscription-heavy."""
    logger.info("Generating subscriptions table...")
    rows = []
    sub_counter = 0
    SUB_MERCHANTS = ["M001", "M002", "M006", "M007"]

    for _, m in merchants_df.iterrows():
        mid = m["merchant_id"]
        if mid not in SUB_MERCHANTS:
            continue

        m_customers = customers_df[customers_df["merchant_id"] == mid]["customer_id"].tolist()
        # ~25% of customers have subscriptions
        sub_customers = random.sample(m_customers, k=min(20, len(m_customers)))

        for cid in sub_customers:
            sub_counter += 1
            plan = random.choice(SUBSCRIPTION_PLANS)
            start = rand_date(DATE_START, DATE_END - timedelta(days=90))

            # Determine subscription status
            status_roll = random.random()
            if status_roll < 0.55:
                status = "ACTIVE"
                months_before_churn = None
                is_vol_cancel = False
                cancel_ts = None
            elif status_roll < 0.75:
                status = "CANCELLED"
                months_before_churn = round(random.uniform(1, 12), 1)
                is_vol_cancel = True
                cancel_ts = fmt_dt(rand_datetime(start + timedelta(days=30), DATE_END))
            elif status_roll < 0.90:
                status = "TERMINATED_PAYMENT_FAILED"
                months_before_churn = round(random.uniform(1, 8), 1)
                is_vol_cancel = False
                cancel_ts = None
            else:
                status = "IN_RETRY"
                months_before_churn = None
                is_vol_cancel = False
                cancel_ts = None

            avg_tenure = round(random.uniform(4, 18), 1) if random.random() > 0.15 else None

            rows.append({
                "subscription_id": f"SUB-{mid}-{sub_counter:05d}",
                "customer_id": cid,
                "merchant_id": mid,
                "plan_id": plan["plan_id"],
                "plan_type": plan["plan_type"],
                "billing_interval": plan["billing_interval"],
                "plan_billing_interval": plan["billing_interval"],  # alias for category3_* compat
                "status": status,
                "start_date": fmt_dt(start),
                "average_plan_tenure_months": avg_tenure,  # for category3_* compat
                "months_completed_before_churn": months_before_churn,
                "is_voluntary_cancelled": is_vol_cancel,
                "cancellation_timestamp": cancel_ts,
                "test_case_id": f"POP-{mid}-SUB-{sub_counter:05d}",
            })

    return pd.DataFrame(rows)


def gen_subscription_events(subscriptions_df: pd.DataFrame) -> pd.DataFrame:
    """Generate billing cycle events for subscriptions."""
    logger.info("Generating subscription_events table...")
    rows = []
    ev_counter = 0

    for _, sub in subscriptions_df.iterrows():
        sid = sub["subscription_id"]
        start = datetime.strptime(sub["start_date"], "%Y-%m-%d").date()
        plan_id = sub["plan_id"]
        # Find the plan amount
        plan_amount = next(
            (p["amount"] for p in SUBSCRIPTION_PLANS if p["plan_id"] == plan_id), 50.00
        )
        is_annual = sub["billing_interval"] == "ANNUAL"
        interval_days = 365 if is_annual else 30

        # Generate billing cycles from start to DATE_END
        cycle_date = start
        cycle_num = 0
        while cycle_date <= DATE_END:
            cycle_num += 1
            cycle_id = f"CYCLE-{sid}-{cycle_num:03d}"
            ev_counter += 1

            # Determine payment outcome based on subscription status
            if sub["status"] == "ACTIVE":
                payment_status = "SUCCESS"
                retry = 0
                is_terminal = False
            elif sub["status"] == "TERMINATED_PAYMENT_FAILED" and cycle_num >= 3:
                # Last cycle fails terminally
                payment_status = "FAILED"
                retry = 3
                is_terminal = True
            elif sub["status"] == "IN_RETRY":
                if random.random() < 0.3:
                    payment_status = "FAILED"
                    retry = random.randint(1, 3)
                    is_terminal = retry >= 3
                else:
                    payment_status = "SUCCESS"
                    retry = 0
                    is_terminal = False
            else:
                payment_status = "SUCCESS" if random.random() > 0.1 else "FAILED"
                retry = random.randint(1, 2) if payment_status == "FAILED" else 0
                is_terminal = False

            rows.append({
                "event_id": f"EV-{ev_counter:07d}",
                "subscription_id": sid,
                "billing_cycle_id": cycle_id,
                "event_date": fmt_dt(cycle_date),
                "invoice_amount": plan_amount,
                "retry_number": retry,
                "payment_status": payment_status,
                "is_terminal_failure": is_terminal,
                "is_voluntary_cancelled": bool(sub["is_voluntary_cancelled"]),  # for category3_* compat
                "test_case_id": sub["test_case_id"].replace("SUB", "SUBEV"),
            })

            cycle_date += timedelta(days=interval_days)

            # Stop generating events for terminated/cancelled after a point
            if sub["status"] in ("TERMINATED_PAYMENT_FAILED", "CANCELLED") and cycle_num >= 6:
                break

    return pd.DataFrame(rows)


def gen_metafields(
    merchants_df: pd.DataFrame,
    products_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generate current-state metafield snapshot (mirrors Shopify API)."""
    logger.info("Generating metafields table...")
    rows = []

    for _, m in merchants_df.iterrows():
        mid = m["merchant_id"]
        tier = m["data_quality_tier"]

        # Shop-level metafields (target margin, free shipping threshold)
        if tier != "messy" or random.random() > 0.4:
            rows.append({
                "entity_type": "shop",
                "entity_id": mid,
                "namespace": "custom",
                "key": "target_margin_pct",
                "value": str(round(random.uniform(0.08, 0.30), 2)),
                "value_type": "number_decimal",
                "updated_at": fmt_dt(rand_datetime(DATE_START, DATE_END)),
                "test_case_id": f"POP-{mid}-MF-SHOP-MARGIN",
            })
        if random.random() > 0.3:
            rows.append({
                "entity_type": "shop",
                "entity_id": mid,
                "namespace": "custom",
                "key": "free_shipping_threshold",
                "value": str(random.choice([40, 50, 75, 100, 150])),
                "value_type": "number_decimal",
                "updated_at": fmt_dt(rand_datetime(DATE_START, DATE_END)),
                "test_case_id": f"POP-{mid}-MF-SHOP-FREESHIP",
            })

        # Product-level metafields (dimensions)
        m_prods = products_df[products_df["merchant_id"] == mid]
        dim_rate = 0.40 if tier == "clean" else (0.20 if tier == "mixed" else 0.10)
        for _, p in m_prods.iterrows():
            if random.random() < dim_rate:
                cfg = CATEGORY_CONFIG.get(p["category"], CATEGORY_CONFIG["fashion"])
                l_min, l_max, w_min, w_max, h_min, h_max = cfg["dim_range"]
                for key, lo, hi in [
                    ("length_cm", l_min, l_max),
                    ("width_cm", w_min, w_max),
                    ("height_cm", h_min, h_max),
                ]:
                    rows.append({
                        "entity_type": "product",
                        "entity_id": p["product_id"],
                        "namespace": "custom",
                        "key": key,
                        "value": str(round(random.uniform(lo, hi), 1)),
                        "value_type": "number_decimal",
                        "updated_at": fmt_dt(rand_datetime(DATE_START, DATE_END)),
                        "test_case_id": f"POP-{mid}-MF-PROD-{p['product_id']}",
                    })

    return pd.DataFrame(rows)


def gen_metafield_history(
    merchants_df: pd.DataFrame,
    metafields_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generate Zeitster's append-only metafield history log.

    ONLY populated AFTER each merchant's cutover_date.
    Pre-cutover data is a permanent expected gap — NOT an error.
    """
    logger.info("Generating metafield_history table...")
    rows = []

    merchant_cutover = {
        m["merchant_id"]: datetime.strptime(m["cutover_date"], "%Y-%m-%d").date()
        for _, m in merchants_df.iterrows()
    }

    for _, mf in metafields_df.iterrows():
        entity_id = mf["entity_id"]
        # Determine which merchant this belongs to
        mid = None
        for m_id in merchant_cutover:
            if m_id in str(entity_id):
                mid = m_id
                break
        if mid is None:
            # Shop-level metafield — entity_id is the merchant_id itself
            mid = entity_id
        if mid not in merchant_cutover:
            continue

        cutover = merchant_cutover[mid]

        # Generate 1-5 history entries, all after cutover
        num_entries = random.randint(1, 5)
        for i in range(num_entries):
            recorded = rand_datetime(cutover, DATE_END)
            rows.append({
                "entity_id": entity_id,
                "field_name": mf["key"],
                "value": mf["value"] if i == num_entries - 1 else str(
                    round(float(mf["value"]) * random.uniform(0.8, 1.2), 2)
                    if mf["value_type"] == "number_decimal"
                    else mf["value"]
                ),
                "recorded_at": fmt_dt(recorded),
                "source": "webhook" if random.random() > 0.2 else "backfill",
                "test_case_id": f"POP-{mid}-MFH-{mf['key']}",
            })

    return pd.DataFrame(rows)


def gen_support_tickets(
    customers_df: pd.DataFrame,
    orders_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generate support ticket records (~5% of orders)."""
    logger.info("Generating support_tickets table...")
    rows = []
    ticket_counter = 0

    for _, o in orders_df.iterrows():
        if random.random() >= 0.05:
            continue
        ticket_counter += 1
        order_date = datetime.strptime(o["created_at"], "%Y-%m-%d %H:%M:%S")
        ticket_date = order_date + timedelta(days=random.randint(0, 14))

        rows.append({
            "ticket_id": f"TICK-{ticket_counter:06d}",
            "customer_id": o["customer_id"],
            "order_id": o["order_id"],
            "ticket_date": fmt_dt(ticket_date),
            "support_cost": round(random.uniform(5.0, 35.0), 2),
            "status": random.choice(["OPEN", "CLOSED", "ESCALATED"]),
            "test_case_id": o["test_case_id"].replace("ORD", "TICK"),
        })

    return pd.DataFrame(rows)


def gen_category_cogs_benchmarks() -> pd.DataFrame:
    """Generate category COGS benchmark reference table."""
    logger.info("Generating category_cogs_benchmarks table...")
    rows = [
        {"category": cat, "benchmark_cogs_amount": cfg["benchmark_cogs"]}
        for cat, cfg in CATEGORY_CONFIG.items()
    ]
    return pd.DataFrame(rows)


def gen_category_margin_targets(merchants_df: pd.DataFrame) -> pd.DataFrame:
    """Generate per-merchant category margin target configs.

    Some merchants never configure this → forces global fallback.
    """
    logger.info("Generating category_margin_targets table...")
    rows = []
    TARGET_MARGINS = {
        "fashion": 0.15, "beauty": 0.20, "electronics": 0.08,
        "home_goods": 0.12, "luxury": 0.25, "pet_care": 0.15, "food_bev": 0.18,
    }

    for _, m in merchants_df.iterrows():
        mid = m["merchant_id"]
        tier = m["data_quality_tier"]
        # Clean merchants configure all categories; messy merchants skip some
        for cat, margin in TARGET_MARGINS.items():
            if tier == "messy" and random.random() < 0.40:
                continue  # not configured
            is_configured = not (tier == "messy" and random.random() < 0.20)
            rows.append({
                "merchant_id": mid,
                "category": cat,
                "target_margin_pct": margin + random.uniform(-0.03, 0.03),
                "is_configured": is_configured,
                "test_case_id": f"POP-{mid}-MARGINTGT-{cat}",
            })

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE INJECTOR
# ═══════════════════════════════════════════════════════════════════════

def inject_edge_cases(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Inject deterministic, tagged edge-case rows into all tables.

    Covers all 14 required edge-case types from the dataset generation spec.
    Each type appears 5-10 times per applicable merchant.

    Edge-case types:
      EC01 — Normal/clean (already abundant in population)
      EC02 — Boundary (0% discount, 100% discount, $0 margin, at-threshold)
      EC03 — Missing field WITH approved fallback
      EC04 — Missing field WITH NO fallback → Unresolved
      EC05 — Pre-cutover order (no metafield history)
      EC06 — Post-cutover order with full metafield history
      EC07 — Partial refund (mixed active/refunded items)
      EC08 — Full order cancellation
      EC09 — Multi-line-item (3+ items, different categories)
      EC10 — Cross-channel (marketplace vs web)
      EC11 — Late-arriving external data
      EC12 — Subscription churn (voluntary & involuntary)
      EC13 — Disputed/charged-back order
      EC14 — Orphan/broken reference
    """
    logger.info("Injecting deterministic edge cases...")

    # We'll inject edge cases for 3 representative merchants: M001, M003, M005
    ec_merchants = ["M001", "M003", "M005"]
    merchants_df = tables["merchants"]

    new_customers = []
    new_orders = []
    new_line_items = []
    new_transactions = []
    new_refunds = []
    new_fulfillments = []
    new_disputes = []
    new_subscriptions = []
    new_sub_events = []
    new_support = []
    new_metafields = []
    new_mf_history = []

    for mid in ec_merchants:
        m_row = merchants_df[merchants_df["merchant_id"] == mid].iloc[0]
        cutover_str = m_row["cutover_date"]
        cutover = datetime.strptime(cutover_str, "%Y-%m-%d").date()
        currency = REGION_CURRENCY.get(m_row["region"], "USD")
        primary_cat = m_row["primary_category"]

        # Helper to create a customer for edge cases
        def make_customer(suffix, tc_id):
            return {
                "customer_id": f"CUST-EC-{mid}-{suffix}",
                "merchant_id": mid,
                "first_name": f"Edge{suffix}",
                "last_name": "Case",
                "email": f"ec.{suffix.lower()}@{mid.lower()}.test",
                "created_at": "2025-06-01 00:00:00",
                "is_vip": False,
                "lifetime_orders": 1,
                "test_case_id": tc_id,
            }

        # ── EC02: Boundary cases (7 variants) ─────────────────────────
        for rep in range(1, 8):
            cid = f"CUST-EC-{mid}-BOUND-{rep}"
            oid = f"ORD-EC-{mid}-BOUND-{rep}"
            tc_id = f"EC02-BOUNDARY-{mid}-{rep}"
            new_customers.append(make_customer(f"BOUND-{rep}", tc_id))

            if rep <= 2:  # 100% discount -> $0 net
                gross = 100.00
                disc = 100.00
                net = 0.01  # avoid div-by-zero
            elif rep <= 4:  # exactly-zero-margin
                gross = 100.00
                disc = 0.0
                net = 100.00
            elif rep <= 6:  # at free-shipping threshold exactly
                gross = 50.00
                disc = 0.0
                net = 50.00
            else:  # 0% discount, full price
                gross = 200.00
                disc = 0.0
                net = 200.00

            cogs = net * 0.50  # for zero-margin variants, COGS = net - shipping - gateway
            if rep in (3, 4):
                # Make exactly-zero-margin: COGS + shipping + gateway = net
                cogs = net - 8.00 - round(net * 0.029 + 0.30, 2)
                cogs = round(max(0, cogs), 2)

            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-03-15 10:00:00", "channel": "web",
                "currency": currency, "gross_sales": gross, "net_sales": net,
                "total_discounts": disc, "current_subtotal": net, "subtotal_price": net,
                "discount_pct": round(disc / gross, 4) if gross > 0 else 0,
                "shipping_charged_to_customer": 0.0,
                "actual_shipping_cost": 8.00, "gateway_fee": round(net * 0.029 + 0.30, 2),
                "total_received": net, "total_refunded": 0.0,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-BOUND-{rep}",
                "order_id": oid, "product_id": f"PROD-{mid}-0001",
                "variant_id": f"VAR-{mid}-0001", "category": primary_cat,
                "sku": f"SKU-EC-BOUND-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": gross, "discount_amount": disc, "net_price": net,
                "cogs": cogs,
                "category_avg_cogs": CATEGORY_CONFIG[primary_cat]["benchmark_cogs"],
                "product_weight_kg": 0.5, "length_cm": None, "width_cm": None,
                "height_cm": None, "is_returned": False, "refund_amount": 0.0,
                "restocking_cost": 0.0, "channel_fee_pct": 0.0,
                "test_case_id": tc_id,
            })
            new_transactions.append({
                "transaction_id": f"TX-EC-{mid}-BOUND-{rep}",
                "order_id": oid, "gateway_name": "shopify_payments",
                "status": "SUCCESS", "fees_amount": round(net * 0.029 + 0.30, 2),
                "captured_at": "2026-03-15 10:00:00", "test_case_id": tc_id,
            })

        # ── EC03: Missing field WITH approved fallback (6 variants) ───
        for rep in range(1, 7):
            cid = f"CUST-EC-{mid}-FB-{rep}"
            oid = f"ORD-EC-{mid}-FB-{rep}"
            tc_id = f"EC03-FALLBACK-{mid}-{rep}"
            new_customers.append(make_customer(f"FB-{rep}", tc_id))

            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-04-01 12:00:00", "channel": "web",
                "currency": currency, "gross_sales": 150.00, "net_sales": 150.00,
                "total_discounts": 0.0, "current_subtotal": 150.00, "subtotal_price": 150.00,
                "discount_pct": 0.0,
                "shipping_charged_to_customer": 5.00,
                "actual_shipping_cost": None if rep <= 3 else 10.00,  # ❌ missing for reps 1-3
                "gateway_fee": None if rep > 3 else 4.65,  # ⚠️ missing for reps 4-6
                "total_received": 155.00, "total_refunded": 0.0,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-FB-{rep}",
                "order_id": oid, "product_id": f"PROD-{mid}-0002",
                "variant_id": f"VAR-{mid}-0002", "category": primary_cat,
                "sku": f"SKU-EC-FB-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": 150.00, "discount_amount": 0.0, "net_price": 150.00,
                "cogs": None,  # Missing COGS → category_avg_cogs is the approved fallback
                "category_avg_cogs": CATEGORY_CONFIG[primary_cat]["benchmark_cogs"],
                "product_weight_kg": 1.0,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                "channel_fee_pct": 0.0, "test_case_id": tc_id,
            })

        # ── EC04: Missing field WITH NO fallback → Unresolved (5 variants) ─
        for rep in range(1, 6):
            cid = f"CUST-EC-{mid}-NOFB-{rep}"
            oid = f"ORD-EC-{mid}-NOFB-{rep}"
            tc_id = f"EC04-NO-FALLBACK-{mid}-{rep}"
            new_customers.append(make_customer(f"NOFB-{rep}", tc_id))

            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-04-10 09:00:00", "channel": "web",
                "currency": currency, "gross_sales": 200.00, "net_sales": 200.00,
                "total_discounts": 0.0, "current_subtotal": 200.00, "subtotal_price": 200.00,
                "discount_pct": 0.0,
                "shipping_charged_to_customer": 0.0,
                "actual_shipping_cost": None,  # Missing external
                "gateway_fee": None,  # Missing partial
                "total_received": 200.00, "total_refunded": 0.0,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })
            # Use unmapped category so both COGS and category_avg_cogs are unavailable
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-NOFB-{rep}",
                "order_id": oid, "product_id": f"PROD-EC-UNMAPPED-{rep}",
                "variant_id": f"VAR-EC-UNMAPPED-{rep}",
                "category": "unmapped_custom_tier",  # No benchmark exists
                "sku": f"SKU-EC-UNMAPPED-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": 200.00, "discount_amount": 0.0, "net_price": 200.00,
                "cogs": None, "category_avg_cogs": None,  # Both missing → Unresolved
                "product_weight_kg": 2.0,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                "channel_fee_pct": 0.0, "test_case_id": tc_id,
            })

        # ── EC05: Pre-cutover order (no metafield history) ────────────
        for rep in range(1, 8):
            cid = f"CUST-EC-{mid}-PRECUT-{rep}"
            oid = f"ORD-EC-{mid}-PRECUT-{rep}"
            tc_id = f"EC05-PRECUTOVER-{mid}-{rep}"
            new_customers.append(make_customer(f"PRECUT-{rep}", tc_id))

            pre_date = cutover - timedelta(days=random.randint(30, 180))
            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": fmt_dt(datetime(pre_date.year, pre_date.month, pre_date.day, 10, 0, 0)),
                "channel": "web", "currency": currency,
                "gross_sales": 120.00, "net_sales": 120.00,
                "total_discounts": 0.0, "current_subtotal": 120.00, "subtotal_price": 120.00,
                "discount_pct": 0.0,
                "shipping_charged_to_customer": 5.00,
                "actual_shipping_cost": 9.00, "gateway_fee": 3.78,
                "total_received": 125.00, "total_refunded": 0.0,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-PRECUT-{rep}",
                "order_id": oid, "product_id": f"PROD-{mid}-0003",
                "variant_id": f"VAR-{mid}-0003", "category": primary_cat,
                "sku": f"SKU-EC-PRECUT-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": 120.00, "discount_amount": 0.0, "net_price": 120.00,
                "cogs": round(120 * 0.45, 2),
                "category_avg_cogs": CATEGORY_CONFIG[primary_cat]["benchmark_cogs"],
                "product_weight_kg": 0.8,
                "length_cm": None, "width_cm": None, "height_cm": None,  # No dims pre-cutover
                "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                "channel_fee_pct": 0.0, "test_case_id": tc_id,
            })

        # ── EC06: Post-cutover with full metafield history ────────────
        for rep in range(1, 8):
            cid = f"CUST-EC-{mid}-POSTCUT-{rep}"
            oid = f"ORD-EC-{mid}-POSTCUT-{rep}"
            tc_id = f"EC06-POSTCUTOVER-{mid}-{rep}"
            new_customers.append(make_customer(f"POSTCUT-{rep}", tc_id))

            post_date = cutover + timedelta(days=random.randint(30, 300))
            if post_date > DATE_END:
                post_date = DATE_END - timedelta(days=10)

            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": fmt_dt(datetime(post_date.year, post_date.month, post_date.day, 14, 0, 0)),
                "channel": "web", "currency": currency,
                "gross_sales": 180.00, "net_sales": 180.00,
                "total_discounts": 0.0, "current_subtotal": 180.00, "subtotal_price": 180.00,
                "discount_pct": 0.0,
                "shipping_charged_to_customer": 0.0,
                "actual_shipping_cost": 11.00, "gateway_fee": 5.52,
                "total_received": 180.00, "total_refunded": 0.0,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })
            cfg = CATEGORY_CONFIG[primary_cat]
            l_min, l_max, w_min, w_max, h_min, h_max = cfg["dim_range"]
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-POSTCUT-{rep}",
                "order_id": oid, "product_id": f"PROD-{mid}-0004",
                "variant_id": f"VAR-{mid}-0004", "category": primary_cat,
                "sku": f"SKU-EC-POSTCUT-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": 180.00, "discount_amount": 0.0, "net_price": 180.00,
                "cogs": round(180 * 0.40, 2),
                "category_avg_cogs": cfg["benchmark_cogs"],
                "product_weight_kg": 1.2,
                "length_cm": round(random.uniform(l_min, l_max), 1),
                "width_cm": round(random.uniform(w_min, w_max), 1),
                "height_cm": round(random.uniform(h_min, h_max), 1),
                "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                "channel_fee_pct": 0.0, "test_case_id": tc_id,
            })
            # Add metafield history for this order's product
            new_metafields.append({
                "entity_type": "product", "entity_id": f"PROD-{mid}-0004",
                "namespace": "custom", "key": "length_cm",
                "value": str(round(random.uniform(l_min, l_max), 1)),
                "value_type": "number_decimal",
                "updated_at": fmt_dt(datetime(post_date.year, post_date.month, post_date.day)),
                "test_case_id": tc_id,
            })
            new_mf_history.append({
                "entity_id": f"PROD-{mid}-0004", "field_name": "length_cm",
                "value": str(round(random.uniform(l_min, l_max), 1)),
                "recorded_at": fmt_dt(datetime(post_date.year, post_date.month, post_date.day)),
                "source": "webhook", "test_case_id": tc_id,
            })

        # ── EC07: Partial refund (mixed active/refunded items) ────────
        for rep in range(1, 7):
            cid = f"CUST-EC-{mid}-PARTREF-{rep}"
            oid = f"ORD-EC-{mid}-PARTREF-{rep}"
            tc_id = f"EC07-PARTIAL-REFUND-{mid}-{rep}"
            new_customers.append(make_customer(f"PARTREF-{rep}", tc_id))

            cats = random.sample(list(CATEGORY_CONFIG.keys()), 3)
            total_gross = 0
            total_disc = 0
            total_ref = 0
            for li_idx, cat in enumerate(cats):
                cfg = CATEGORY_CONFIG[cat]
                is_ret = li_idx == 0  # only first item returned
                g_price = round(random.uniform(30, 200), 2)
                d_amt = round(g_price * 0.10, 2)
                n_price = round(g_price - d_amt, 2)
                total_gross += g_price
                total_disc += d_amt
                if is_ret:
                    total_ref += n_price

                new_line_items.append({
                    "line_item_id": f"LI-EC-{mid}-PARTREF-{rep}-{li_idx + 1}",
                    "order_id": oid, "product_id": f"PROD-{mid}-{(li_idx + 5):04d}",
                    "variant_id": f"VAR-{mid}-{(li_idx + 5):04d}", "category": cat,
                    "sku": f"SKU-EC-PARTREF-{rep}-{li_idx + 1}",
                    "quantity": 1, "current_quantity": 0 if is_ret else 1,
                    "gross_price": g_price, "discount_amount": d_amt, "net_price": n_price,
                    "cogs": round(g_price * 0.45, 2),
                    "category_avg_cogs": cfg["benchmark_cogs"],
                    "product_weight_kg": 1.0,
                    "length_cm": None, "width_cm": None, "height_cm": None,
                    "is_returned": is_ret, "refund_amount": n_price if is_ret else 0.0,
                    "restocking_cost": round(g_price * 0.08, 2) if is_ret else 0.0,
                    "channel_fee_pct": 0.0, "test_case_id": tc_id,
                })

            net_sales = round(total_gross - total_disc, 2)
            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-05-01 11:30:00", "channel": "web",
                "currency": currency, "gross_sales": round(total_gross, 2),
                "net_sales": net_sales,
                "total_discounts": round(total_disc, 2),
                "current_subtotal": net_sales, "subtotal_price": net_sales,
                "discount_pct": round(total_disc / total_gross, 4) if total_gross > 0 else 0,
                "shipping_charged_to_customer": 5.00,
                "actual_shipping_cost": 12.00, "gateway_fee": round(net_sales * 0.029 + 0.30, 2),
                "total_received": round(net_sales + 5.00, 2),
                "total_refunded": round(total_ref, 2),
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })
            new_refunds.append({
                "refund_id": f"REF-EC-{mid}-PARTREF-{rep}",
                "order_id": oid,
                "refund_line_item_ids": f"LI-EC-{mid}-PARTREF-{rep}-1",
                "refund_amount": round(total_ref, 2),
                "refund_date": "2026-05-10 00:00:00",
                "reason": random.choice(RETURN_REASONS),
                "test_case_id": tc_id,
            })

        # ── EC08: Full order cancellation ─────────────────────────────
        for rep in range(1, 6):
            cid = f"CUST-EC-{mid}-CANCEL-{rep}"
            oid = f"ORD-EC-{mid}-CANCEL-{rep}"
            tc_id = f"EC08-FULL-CANCEL-{mid}-{rep}"
            new_customers.append(make_customer(f"CANCEL-{rep}", tc_id))

            gross = round(random.uniform(50, 300), 2)
            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-02-20 16:00:00", "channel": "web",
                "currency": currency, "gross_sales": gross, "net_sales": gross,
                "total_discounts": 0.0, "current_subtotal": gross, "subtotal_price": gross,
                "discount_pct": 0.0,
                "shipping_charged_to_customer": 0.0,
                "actual_shipping_cost": 0.0, "gateway_fee": 0.0,
                "total_received": gross, "total_refunded": gross,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "CANCELLED", "is_cancelled": True,
                "source_name": "web", "test_case_id": tc_id,
            })
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-CANCEL-{rep}",
                "order_id": oid, "product_id": f"PROD-{mid}-0001",
                "variant_id": f"VAR-{mid}-0001", "category": primary_cat,
                "sku": f"SKU-EC-CANCEL-{rep}", "quantity": 1, "current_quantity": 0,
                "gross_price": gross, "discount_amount": 0.0, "net_price": gross,
                "cogs": round(gross * 0.40, 2),
                "category_avg_cogs": CATEGORY_CONFIG[primary_cat]["benchmark_cogs"],
                "product_weight_kg": 0.5,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "is_returned": False, "refund_amount": gross, "restocking_cost": 0.0,
                "channel_fee_pct": 0.0, "test_case_id": tc_id,
            })
            new_refunds.append({
                "refund_id": f"REF-EC-{mid}-CANCEL-{rep}",
                "order_id": oid, "refund_line_item_ids": "ALL",
                "refund_amount": gross,
                "refund_date": "2026-02-21 00:00:00", "reason": "order_cancelled",
                "test_case_id": tc_id,
            })

        # ── EC09: Multi-line-item (3+ items, different categories) ────
        for rep in range(1, 8):
            cid = f"CUST-EC-{mid}-MULTI-{rep}"
            oid = f"ORD-EC-{mid}-MULTI-{rep}"
            tc_id = f"EC09-MULTI-LINEITEM-{mid}-{rep}"
            new_customers.append(make_customer(f"MULTI-{rep}", tc_id))

            cats = random.sample(list(CATEGORY_CONFIG.keys()), min(4, len(CATEGORY_CONFIG)))
            total_gross = 0
            total_disc = 0
            for li_idx, cat in enumerate(cats):
                cfg = CATEGORY_CONFIG[cat]
                g_price = round(random.uniform(20, 300), 2)
                d_amt = round(g_price * random.uniform(0, 0.20), 2)
                n_price = round(g_price - d_amt, 2)
                total_gross += g_price
                total_disc += d_amt

                new_line_items.append({
                    "line_item_id": f"LI-EC-{mid}-MULTI-{rep}-{li_idx + 1}",
                    "order_id": oid, "product_id": f"PROD-{mid}-{(li_idx + 10):04d}",
                    "variant_id": f"VAR-{mid}-{(li_idx + 10):04d}", "category": cat,
                    "sku": f"SKU-EC-MULTI-{rep}-{li_idx + 1}",
                    "quantity": random.randint(1, 2), "current_quantity": random.randint(1, 2),
                    "gross_price": g_price, "discount_amount": d_amt, "net_price": n_price,
                    "cogs": round(g_price * random.uniform(0.35, 0.65), 2),
                    "category_avg_cogs": cfg["benchmark_cogs"],
                    "product_weight_kg": round(random.uniform(0.3, 3.0), 2),
                    "length_cm": None, "width_cm": None, "height_cm": None,
                    "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                    "channel_fee_pct": 0.0, "test_case_id": tc_id,
                })

            net_sales = round(total_gross - total_disc, 2)
            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-03-01 09:00:00", "channel": "web",
                "currency": currency, "gross_sales": round(total_gross, 2),
                "net_sales": net_sales,
                "total_discounts": round(total_disc, 2),
                "current_subtotal": net_sales, "subtotal_price": net_sales,
                "discount_pct": round(total_disc / total_gross, 4) if total_gross > 0 else 0,
                "shipping_charged_to_customer": 0.0,
                "actual_shipping_cost": 15.00, "gateway_fee": round(net_sales * 0.029 + 0.30, 2),
                "total_received": net_sales,
                "total_refunded": 0.0,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })

        # ── EC10: Cross-channel (marketplace vs web) ──────────────────
        for rep, channel in enumerate(["amazon", "tiktok", "retail", "amazon", "tiktok", "retail"], start=1):
            cid = f"CUST-EC-{mid}-CHAN-{rep}"
            oid = f"ORD-EC-{mid}-CHAN-{rep}"
            tc_id = f"EC10-CROSS-CHANNEL-{mid}-{rep}-{channel.upper()}"
            new_customers.append(make_customer(f"CHAN-{rep}", tc_id))

            fee_pct = CHANNEL_FEES.get(channel, 0)
            gross = round(random.uniform(50, 400), 2)
            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-04-15 13:00:00", "channel": channel,
                "currency": currency, "gross_sales": gross, "net_sales": gross,
                "total_discounts": 0.0, "current_subtotal": gross, "subtotal_price": gross,
                "discount_pct": 0.0,
                "shipping_charged_to_customer": 5.00,
                "actual_shipping_cost": 10.00,
                "gateway_fee": round(gross * 0.029 + 0.30, 2) if channel != "retail" else None,
                "total_received": gross + 5.00,
                "total_refunded": 0.0,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": channel, "test_case_id": tc_id,
            })
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-CHAN-{rep}",
                "order_id": oid, "product_id": f"PROD-{mid}-0001",
                "variant_id": f"VAR-{mid}-0001", "category": primary_cat,
                "sku": f"SKU-EC-CHAN-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": gross, "discount_amount": 0.0, "net_price": gross,
                "cogs": round(gross * 0.45, 2),
                "category_avg_cogs": CATEGORY_CONFIG[primary_cat]["benchmark_cogs"],
                "product_weight_kg": 1.0,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                "channel_fee_pct": fee_pct, "test_case_id": tc_id,
            })

        # ── EC11: Late-arriving external data ─────────────────────────
        for rep in range(1, 6):
            cid = f"CUST-EC-{mid}-LATE-{rep}"
            oid = f"ORD-EC-{mid}-LATE-{rep}"
            tc_id = f"EC11-LATE-EXTERNAL-{mid}-{rep}"
            new_customers.append(make_customer(f"LATE-{rep}", tc_id))

            gross = round(random.uniform(80, 250), 2)
            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-06-01 10:00:00", "channel": "web",
                "currency": currency, "gross_sales": gross, "net_sales": gross,
                "total_discounts": 0.0, "current_subtotal": gross, "subtotal_price": gross,
                "discount_pct": 0.0,
                "shipping_charged_to_customer": 0.0,
                "actual_shipping_cost": None,  # 3PL invoice not yet received
                "gateway_fee": None,  # External gateway fee not yet available
                "total_received": gross,
                "total_refunded": 0.0,
                "dispute_status": "NONE", "chargeback_amount": 0.0,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-LATE-{rep}",
                "order_id": oid, "product_id": f"PROD-{mid}-0001",
                "variant_id": f"VAR-{mid}-0001", "category": primary_cat,
                "sku": f"SKU-EC-LATE-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": gross, "discount_amount": 0.0, "net_price": gross,
                "cogs": round(gross * 0.50, 2),
                "category_avg_cogs": CATEGORY_CONFIG[primary_cat]["benchmark_cogs"],
                "product_weight_kg": 1.5,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                "channel_fee_pct": 0.0, "test_case_id": tc_id,
            })
            new_fulfillments.append({
                "fulfillment_id": f"FUL-EC-{mid}-LATE-{rep}",
                "order_id": oid, "tracking_carrier": "DHL",
                "tracking_number": f"TRK{random.randint(100000, 999999)}",
                "actual_shipping_cost": None,  # Late 3PL data
                "delivery_status": "DELIVERED",
                "test_case_id": tc_id,
            })

        # ── EC12: Subscription churn (voluntary & involuntary) ────────
        if mid in ["M001", "M007"]:  # subscription-heavy merchants
            for rep in range(1, 6):
                cid = f"CUST-EC-{mid}-CHURN-{rep}"
                sub_id = f"SUB-EC-{mid}-CHURN-{rep}"
                is_vol = rep <= 3  # 3 voluntary, 2 involuntary
                tc_id = f"EC12-CHURN-{'VOL' if is_vol else 'INVOL'}-{mid}-{rep}"

                new_customers.append(make_customer(f"CHURN-{rep}", tc_id))
                plan = random.choice(SUBSCRIPTION_PLANS[:4])  # Monthly plans

                new_subscriptions.append({
                    "subscription_id": sub_id, "customer_id": cid, "merchant_id": mid,
                    "plan_id": plan["plan_id"], "plan_type": plan["plan_type"],
                    "billing_interval": plan["billing_interval"],
                    "status": "CANCELLED" if is_vol else "TERMINATED_PAYMENT_FAILED",
                    "start_date": "2025-09-01",
                    "months_completed_before_churn": round(random.uniform(2, 8), 1),
                    "is_voluntary_cancelled": is_vol,
                    "cancellation_timestamp": "2026-05-15 14:00:00" if is_vol else None,
                    "test_case_id": tc_id,
                })
                # Terminal failure event for involuntary churn
                if not is_vol:
                    for retry in range(1, 4):
                        new_sub_events.append({
                            "event_id": f"EV-EC-{mid}-CHURN-{rep}-R{retry}",
                            "subscription_id": sub_id,
                            "billing_cycle_id": f"CYCLE-EC-{mid}-{rep}-2026-05",
                            "event_date": f"2026-05-{10 + retry * 3:02d}",
                            "invoice_amount": plan["amount"],
                            "retry_number": retry,
                            "payment_status": "FAILED",
                            "is_terminal_failure": retry == 3,
                            "test_case_id": tc_id,
                        })

        # ── EC13: Disputed/charged-back order ─────────────────────────
        for rep in range(1, 8):
            cid = f"CUST-EC-{mid}-DISP-{rep}"
            oid = f"ORD-EC-{mid}-DISP-{rep}"
            disp_status = DISPUTE_STATUSES[(rep - 1) % len(DISPUTE_STATUSES)]
            tc_id = f"EC13-DISPUTE-{disp_status}-{mid}-{rep}"
            new_customers.append(make_customer(f"DISP-{rep}", tc_id))

            gross = round(random.uniform(100, 500), 2)
            cb_amount = round(gross + 15.00, 2)
            new_orders.append({
                "order_id": oid, "merchant_id": mid, "customer_id": cid,
                "created_at": "2026-03-20 11:00:00", "channel": "web",
                "currency": currency, "gross_sales": gross, "net_sales": gross,
                "total_discounts": 0.0, "current_subtotal": gross, "subtotal_price": gross,
                "discount_pct": 0.0,
                "shipping_charged_to_customer": 5.00,
                "actual_shipping_cost": 10.00, "gateway_fee": round(gross * 0.029 + 0.30, 2),
                "total_received": gross + 5.00,
                "total_refunded": 0.0,
                "dispute_status": disp_status, "chargeback_amount": cb_amount,
                "completed_order_status": "COMPLETED", "is_cancelled": False,
                "source_name": "web", "test_case_id": tc_id,
            })
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-DISP-{rep}",
                "order_id": oid, "product_id": f"PROD-{mid}-0001",
                "variant_id": f"VAR-{mid}-0001", "category": primary_cat,
                "sku": f"SKU-EC-DISP-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": gross, "discount_amount": 0.0, "net_price": gross,
                "cogs": round(gross * 0.40, 2),
                "category_avg_cogs": CATEGORY_CONFIG[primary_cat]["benchmark_cogs"],
                "product_weight_kg": 1.0,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                "channel_fee_pct": 0.0, "test_case_id": tc_id,
            })
            new_disputes.append({
                "dispute_id": f"DISP-EC-{mid}-{rep}",
                "order_id": oid, "status": disp_status,
                "amount": cb_amount,
                "created_at": "2026-04-15 00:00:00",
                "test_case_id": tc_id,
            })

        # ── EC14: Orphan/broken reference ─────────────────────────────
        for rep in range(1, 6):
            tc_id = f"EC14-ORPHAN-{mid}-{rep}"
            # Line item pointing to non-existent order
            new_line_items.append({
                "line_item_id": f"LI-EC-{mid}-ORPHAN-{rep}",
                "order_id": f"ORD-DELETED-{mid}-{rep}",  # does NOT exist in orders
                "product_id": f"PROD-{mid}-0001",
                "variant_id": f"VAR-{mid}-0001", "category": primary_cat,
                "sku": f"SKU-EC-ORPHAN-{rep}", "quantity": 1, "current_quantity": 1,
                "gross_price": 99.99, "discount_amount": 0.0, "net_price": 99.99,
                "cogs": 40.00,
                "category_avg_cogs": CATEGORY_CONFIG[primary_cat]["benchmark_cogs"],
                "product_weight_kg": 0.5,
                "length_cm": None, "width_cm": None, "height_cm": None,
                "is_returned": False, "refund_amount": 0.0, "restocking_cost": 0.0,
                "channel_fee_pct": 0.0, "test_case_id": tc_id,
            })
            # Support ticket pointing to non-existent order
            new_support.append({
                "ticket_id": f"TICK-EC-{mid}-ORPHAN-{rep}",
                "customer_id": f"CUST-DELETED-{mid}-{rep}",  # does NOT exist
                "order_id": f"ORD-DELETED-{mid}-{rep}",
                "ticket_date": "2026-06-01 10:00:00",
                "support_cost": 20.00, "status": "OPEN",
                "test_case_id": tc_id,
            })

    # ── Merge edge cases into existing tables ─────────────────────────

    def _concat(existing: pd.DataFrame, new_rows: list) -> pd.DataFrame:
        if not new_rows:
            return existing
        new_df = pd.DataFrame(new_rows)
        # Align columns (new may have extra or missing)
        for col in existing.columns:
            if col not in new_df.columns:
                new_df[col] = None
        return pd.concat([existing, new_df[existing.columns]], ignore_index=True)

    tables["customers"] = _concat(tables["customers"], new_customers)
    tables["orders"] = _concat(tables["orders"], new_orders)
    tables["line_items"] = _concat(tables["line_items"], new_line_items)
    tables["transactions"] = _concat(tables["transactions"], new_transactions)
    tables["refunds"] = _concat(tables["refunds"], new_refunds)
    tables["shipping_fulfillments"] = _concat(tables["shipping_fulfillments"], new_fulfillments)
    tables["disputes"] = _concat(tables["disputes"], new_disputes)
    tables["subscriptions"] = _concat(tables["subscriptions"], new_subscriptions)
    tables["subscription_events"] = _concat(tables["subscription_events"], new_sub_events)
    tables["support_tickets"] = _concat(tables["support_tickets"], new_support)
    tables["metafields"] = _concat(tables["metafields"], new_metafields)
    tables["metafield_history"] = _concat(tables["metafield_history"], new_mf_history)

    logger.info("Edge case injection complete.")
    return tables


# ═══════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════

def generate_all(seed: int = SEED) -> dict[str, pd.DataFrame]:
    """Generate all 16 tables with population data + edge cases."""
    np.random.seed(seed)
    random.seed(seed)

    logger.info("=" * 60)
    logger.info("ZEITSTER SYNTHETIC DATASET GENERATOR — Starting")
    logger.info("=" * 60)

    merchants = gen_merchants()
    customers = gen_customers(merchants)
    products = gen_products_variants(merchants)
    orders, line_items = gen_orders_and_line_items(merchants, customers, products)
    transactions = gen_transactions(orders)
    refunds = gen_refunds(orders, line_items)
    fulfillments = gen_shipping_fulfillments(orders)
    disputes = gen_disputes(orders)
    subscriptions = gen_subscriptions(customers, merchants)
    sub_events = gen_subscription_events(subscriptions)
    metafields = gen_metafields(merchants, products)
    mf_history = gen_metafield_history(merchants, metafields)
    tickets = gen_support_tickets(customers, orders)
    benchmarks = gen_category_cogs_benchmarks()
    margin_targets = gen_category_margin_targets(merchants)

    tables = {
        "merchants": merchants,
        "customers": customers,
        "products_variants": products,
        "orders": orders,
        "line_items": line_items,
        "transactions": transactions,
        "refunds": refunds,
        "shipping_fulfillments": fulfillments,
        "disputes": disputes,
        "subscriptions": subscriptions,
        "subscription_events": sub_events,
        "metafields": metafields,
        "metafield_history": mf_history,
        "support_tickets": tickets,
        "category_cogs_benchmarks": benchmarks,
        "category_margin_targets": margin_targets,
    }

    tables = inject_edge_cases(tables)

    logger.info("=" * 60)
    logger.info("GENERATION COMPLETE — Summary:")
    for name, df in tables.items():
        logger.info("  %-30s %6d rows, %2d cols", name, len(df), len(df.columns))
    logger.info("=" * 60)

    return tables


def save_all(tables: dict[str, pd.DataFrame], output_dir: str = "data") -> None:
    """Save all tables to CSV files in the output directory."""
    os.makedirs(output_dir, exist_ok=True)
    small_tables = {"category_cogs_benchmarks", "category_margin_targets", "merchants"}

    for name, df in tables.items():
        if name in small_tables:
            path = os.path.join(output_dir, f"zeitster_{name}.csv")
            df.to_csv(path, index=False)
        else:
            path = os.path.join(output_dir, f"zeitster_{name}.csv.gz")
            df.to_csv(path, index=False, compression="gzip")
        logger.info("Saved %s → %s (%d rows)", name, path, len(df))


if __name__ == "__main__":
    tables = generate_all()
    save_all(tables)

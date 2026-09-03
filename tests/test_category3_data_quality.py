"""tests/test_category3_data_quality.py — Data Quality & Integrity Validation for Category 3 Synthetic Datasets."""

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def cat3_data():
    df_cust = pd.read_csv("data/category3_customers.csv.gz")
    df_ord = pd.read_csv("data/category3_orders.csv.gz")
    df_li = pd.read_csv("data/category3_line_items.csv.gz")
    df_subs = pd.read_csv("data/category3_subscriptions.csv.gz")
    df_events = pd.read_csv("data/category3_subscription_events.csv.gz")
    df_bench = pd.read_csv("data/category3_category_cogs_benchmarks.csv")
    df_supp = pd.read_csv("data/category3_support_tickets.csv.gz")
    df_vip = pd.read_csv("data/category3_vip_monthly.csv.gz")
    return {
        "customers": df_cust,
        "orders": df_ord,
        "line_items": df_li,
        "subscriptions": df_subs,
        "sub_events": df_events,
        "benchmarks": df_bench,
        "support": df_supp,
        "vip_monthly": df_vip,
    }


def test_primary_key_uniqueness(cat3_data):
    """Verify that all entity tables have unique primary keys."""
    assert cat3_data["customers"]["customer_id"].is_unique, "Duplicate customer_id found"
    assert cat3_data["orders"]["order_id"].is_unique, "Duplicate order_id found"
    assert cat3_data["line_items"]["line_item_id"].is_unique, "Duplicate line_item_id found"
    assert cat3_data["subscriptions"]["subscription_id"].is_unique, "Duplicate subscription_id found"
    assert cat3_data["sub_events"]["event_id"].is_unique, "Duplicate event_id found"


def test_foreign_key_referential_integrity(cat3_data):
    """Verify referential integrity across related tables."""
    cust_ids = set(cat3_data["customers"]["customer_id"])
    order_ids = set(cat3_data["orders"]["order_id"])
    sub_ids = set(cat3_data["subscriptions"]["subscription_id"])

    # Orders -> Customers
    assert set(cat3_data["orders"]["customer_id"]).issubset(cust_ids)

    # Line Items -> Orders
    assert set(cat3_data["line_items"]["order_id"]).issubset(order_ids)

    # Subscriptions -> Customers
    assert set(cat3_data["subscriptions"]["customer_id"]).issubset(cust_ids)

    # Subscription Events -> Subscriptions
    assert set(cat3_data["sub_events"]["subscription_id"]).issubset(sub_ids)


def test_subscription_deduplication_integrity(cat3_data):
    """Verify that multiple retries exist for the dedup test case but map to same cycle."""
    events = cat3_data["sub_events"]
    dedup_events = events[events["subscription_id"] == "SUB-DEDUP-001"]
    assert len(dedup_events) == 3
    assert len(dedup_events["billing_cycle_id"].unique()) == 1


def test_no_invalid_negative_monetary_values(cat3_data):
    """Verify non-negative monetary amounts."""
    assert (cat3_data["orders"]["net_paid_amount"] >= 0).all()
    assert (cat3_data["orders"]["total_refunded_amount"] >= 0).all()
    assert (cat3_data["line_items"]["gross_price"] >= 0).all()
    assert (cat3_data["sub_events"]["invoice_amount"] >= 0).all()


def test_category_benchmarks_presence(cat3_data):
    """Verify category benchmarks reference table."""
    bench = cat3_data["benchmarks"]
    assert len(bench) >= 6
    assert "benchmark_cogs_amount" in bench.columns
    assert (bench["benchmark_cogs_amount"] > 0).all()

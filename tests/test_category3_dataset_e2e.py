"""tests/test_category3_dataset_e2e.py — End-to-End Dataset Integration Tests for Category 3."""

from datetime import date
import pandas as pd
import pytest

from src.scoring.c03 import SyntheticOrder, evaluate_c03_population
from src.scoring.c07 import Subscription, PaymentRetryEvent, evaluate_c07_involuntary_churn
from src.scoring.c09 import CustomerOrderLine, evaluate_c09_profitability
from src.scoring.c11 import evaluate_c11_high_value_loss

EVAL_DATE = date(2026, 8, 1)


@pytest.fixture(scope="module")
def loaded_cat3_data():
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


def test_c03_dataset_e2e(loaded_cat3_data):
    """Run C03 directly against orders loaded from category3_orders.csv.gz."""
    df_ord = loaded_cat3_data["orders"]
    df_li = loaded_cat3_data["line_items"]

    # Compute item counts and return counts per order from line items
    item_counts = df_li.groupby("order_id").agg(
        total_items=("quantity", "sum"),
        returned_items=("is_returned", "sum")
    ).reset_index()

    df_ord_merged = df_ord.merge(item_counts, on="order_id", how="left")
    df_ord_merged["total_items"] = df_ord_merged["total_items"].fillna(1).astype(int)
    df_ord_merged["returned_items"] = df_ord_merged["returned_items"].fillna(0).astype(int)

    orders = []
    for _, row in df_ord_merged.iterrows():
        o_date = date.fromisoformat(str(row["order_date"]).split(" ")[0])
        orders.append(
            SyntheticOrder(
                order_id=row["order_id"],
                customer_id=row["customer_id"],
                order_date=o_date,
                completed_order_status=row["completed_order_status"],
                net_paid_amount=float(row["net_paid_amount"]),
                refund_amount=float(row["total_refunded_amount"]),
                dispute_status=row["dispute_status"] if pd.notna(row["dispute_status"]) else None,
                total_items=int(row["total_items"]),
                returned_items=int(row["returned_items"]),
            )
        )

    res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=0.10)
    assert res.total_customers_count >= 20
    assert res.eligible_population_count > 0
    assert res.vip_count > 0

    # Verify same-day repeat customer
    c_sameday = res.customer_evaluations.get("CUST-C03-SAMEDAY-001")
    assert c_sameday is not None
    assert c_sameday.is_vip is True
    assert c_sameday.avg_buying_rhythm == 0.0
    assert c_sameday.frequency_per_year == 365.0
    assert pytest.approx(c_sameday.expected_annual_spend, 0.01) == 365000.0


def test_c07_dataset_e2e(loaded_cat3_data):
    """Run C07 directly against subscriptions and events loaded from CSV."""
    df_subs = loaded_cat3_data["subscriptions"]
    df_events = loaded_cat3_data["sub_events"]

    subs = []
    for _, r in df_subs.iterrows():
        s_date = date.fromisoformat(str(r["start_date"]))
        avg_tenure = float(r["average_plan_tenure_months"]) if pd.notna(r["average_plan_tenure_months"]) else None
        subs.append(
            Subscription(
                subscription_id=r["subscription_id"],
                customer_id=r["customer_id"],
                plan_type=r["plan_type"],
                status=r["status"],
                start_date=s_date,
                average_plan_tenure_months=avg_tenure,
                months_completed_before_churn=float(r["months_completed_before_churn"]),
                is_voluntary_cancelled=bool(r["is_voluntary_cancelled"]),
            )
        )

    events = []
    for _, r in df_events.iterrows():
        ev_date = date.fromisoformat(str(r["event_date"]))
        events.append(
            PaymentRetryEvent(
                event_id=r["event_id"],
                subscription_id=r["subscription_id"],
                billing_cycle_id=r["billing_cycle_id"],
                event_date=ev_date,
                invoice_amount=float(r["invoice_amount"]),
                retry_number=int(r["retry_number"]),
                payment_status=r["payment_status"],
                is_terminal_failure=bool(r["is_terminal_failure"]),
                is_voluntary_cancelled=bool(r["is_voluntary_cancelled"]),
            )
        )

    res = evaluate_c07_involuntary_churn(subs, events, EVAL_DATE, rolling_window_days=30)
    assert res.total_events_evaluated >= 7
    # Deduplication test case must be present as 1 event
    dedup_ev = res.event_evaluations.get("SUB-DEDUP-001:CYCLE-2026-07")
    assert dedup_ev is not None
    assert dedup_ev.is_involuntary_churn is True
    assert dedup_ev.event_exposure_dollars == 300.0

    # Recovery test case must have $0 exposure
    rec_ev = res.event_evaluations.get("SUB-RECOVER-001:CYCLE-2026-07")
    assert rec_ev is not None
    assert rec_ev.is_involuntary_churn is False
    assert rec_ev.event_exposure_dollars == 0.0


def test_c09_dataset_e2e(loaded_cat3_data):
    """Run C09 directly against order line items and support tickets."""
    df_li = loaded_cat3_data["line_items"]
    df_ord = loaded_cat3_data["orders"]
    df_supp = loaded_cat3_data["support"]

    # Join orders for shipping & gateway fees
    df_merged = df_li.merge(
        df_ord[["order_id", "customer_id", "order_date", "actual_shipping_cost", "gateway_fee"]],
        on="order_id",
        how="left"
    )

    # Support costs per customer
    supp_costs = df_supp.groupby("customer_id")["support_cost"].sum().to_dict()

    lines = []
    for _, r in df_merged.iterrows():
        o_date = date.fromisoformat(str(r["order_date"]).split(" ")[0])
        act_cogs = float(r["actual_cogs"]) if pd.notna(r["actual_cogs"]) else None
        cat_cogs = float(r["category_avg_cogs"]) if pd.notna(r["category_avg_cogs"]) else None
        gw_fee = float(r["gateway_fee"]) if pd.notna(r["gateway_fee"]) else None
        supp_cost = supp_costs.get(r["customer_id"], 0.0)

        lines.append(
            CustomerOrderLine(
                order_id=r["order_id"],
                customer_id=r["customer_id"],
                order_date=o_date,
                item_id=r["product_id"],
                gross_price=float(r["gross_price"]),
                discount_amount=float(r["discount_amount"]),
                refunded_amount=float(r["refund_amount"]),
                actual_cogs=act_cogs,
                category_avg_cogs=cat_cogs,
                category=r["category"],
                is_returned=bool(r["is_returned"]),
                is_sellable=bool(r["is_sellable"]),
                shipping_cost=float(r["actual_shipping_cost"]),
                payment_gateway_fee=gw_fee,
                support_ticket_count=1 if supp_cost > 0 else 0,
                support_cost_per_ticket=supp_cost if supp_cost > 0 else 0.0,
            )
        )

    res = evaluate_c09_profitability(lines, EVAL_DATE)
    assert res.total_customers_count >= 15

    # Verify sellable vs damaged
    c_sell = res.customer_evaluations.get("CUST-C09-SELLABLE")
    c_dam = res.customer_evaluations.get("CUST-C09-DAMAGED")
    assert c_sell is not None and c_dam is not None
    assert c_sell.cogs_recovered_from_sellable_returns == 40.0
    assert c_dam.cogs_recovered_from_sellable_returns == 0.0

    # Verify missing category cogs unresolved
    c_nocogs = res.customer_evaluations.get("CUST-C09-NOCOGS")
    assert c_nocogs is not None
    assert c_nocogs.is_fully_computable is False
    assert c_nocogs.has_missing_cogs is True


def test_c11_dataset_e2e(loaded_cat3_data):
    """Run C11 directly by evaluating C03 population then C11 loss."""
    df_ord = loaded_cat3_data["orders"]
    df_li = loaded_cat3_data["line_items"]

    item_counts = df_li.groupby("order_id").agg(
        total_items=("quantity", "sum"),
        returned_items=("is_returned", "sum")
    ).reset_index()

    df_ord_merged = df_ord.merge(item_counts, on="order_id", how="left")
    df_ord_merged["total_items"] = df_ord_merged["total_items"].fillna(1).astype(int)
    df_ord_merged["returned_items"] = df_ord_merged["returned_items"].fillna(0).astype(int)

    orders = []
    for _, row in df_ord_merged.iterrows():
        o_date = date.fromisoformat(str(row["order_date"]).split(" ")[0])
        orders.append(
            SyntheticOrder(
                order_id=row["order_id"],
                customer_id=row["customer_id"],
                order_date=o_date,
                completed_order_status=row["completed_order_status"],
                net_paid_amount=float(row["net_paid_amount"]),
                refund_amount=float(row["total_refunded_amount"]),
                dispute_status=row["dispute_status"] if pd.notna(row["dispute_status"]) else None,
                total_items=int(row["total_items"]),
                returned_items=int(row["returned_items"]),
            )
        )

    c03_res = evaluate_c03_population(orders, EVAL_DATE, vip_percentile=1.0)
    c11_res = evaluate_c11_high_value_loss(c03_res, EVAL_DATE)

    # Established Lost VIP check
    c11_lost = c11_res.vip_evaluations.get("CUST-C11-LOST-VIP")
    assert c11_lost is not None
    assert c11_lost.is_established_vip is True
    assert c11_lost.is_lost_vip is True
    assert pytest.approx(c11_lost.c11_exposure_dollars, 0.01) == (2000.0 / (361.0 / 90.0))

    # 1-order non-established VIP check
    c11_nonest = c11_res.vip_evaluations.get("CUST-C11-1ORD-NONEST")
    assert c11_nonest is not None
    assert c11_nonest.is_established_vip is False
    assert c11_nonest.c11_exposure_dollars == 0.0

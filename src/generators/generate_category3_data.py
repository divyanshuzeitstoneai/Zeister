"""src/generators/generate_category3_data.py — Synthetic Data Generator for Category 3 (C03, C07, C09, C11).

Generates complete relational datasets and derived tables for testing Category 3:
1. data/category3_customers.csv.gz (dim_customers)
2. data/category3_orders.csv.gz (fact_orders)
3. data/category3_line_items.csv.gz (fact_order_line_items)
4. data/category3_subscriptions.csv.gz (dim_subscriptions)
5. data/category3_subscription_events.csv.gz (fact_subscription_events)
6. data/category3_category_cogs_benchmarks.csv (reference table)
7. data/category3_support_tickets.csv.gz (fact_customer_support_tickets)
8. data/category3_vip_monthly.csv.gz (dim_vip_monthly snapshot)

Contains both realistic stochastic populations and controlled deterministic test cases
with explicit test_case_id tags covering all edge cases.
"""

from __future__ import annotations

import gzip
import logging
import os
from datetime import date, datetime, timedelta
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVALUATION_DATE = date(2026, 8, 1)

# Category benchmarks for COGS fallback
CATEGORY_COGS_BENCHMARKS = {
    "fashion": 35.00,
    "beauty": 18.50,
    "electronics": 120.00,
    "home_goods": 45.00,
    "luxury": 350.00,
    "pet_care": 22.00,
}


def build_controlled_category3_dataset() -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame
]:
    """Builds controlled deterministic test cases and population records for Category 3."""
    customers = []
    orders = []
    line_items = []
    subscriptions = []
    sub_events = []
    support_tickets = []
    
    # -------------------------------------------------------------
    # 1. CONTROLLED TEST SCENARIOS FOR C03 / C11
    # -------------------------------------------------------------
    
    # Scenario C03-VIP-CEIL-15: 15 customers to test CEIL(0.10 * 15) = 2 VIPs
    for i in range(1, 16):
        cid = f"CUST-CEIL-{i:02d}"
        customers.append({
            "customer_id": cid,
            "first_name": f"User{i}",
            "last_name": f"Ceil{i}",
            "email": f"user.ceil{i}@example.com",
            "created_at": "2025-01-01 00:00:00",
            "test_case_id": f"C03-VIP-CEIL-POP-{i:02d}",
        })
        oid = f"ORD-CEIL-{i:02d}"
        net_paid = float(i * 100.0)
        orders.append({
            "order_id": oid,
            "customer_id": cid,
            "order_date": "2026-01-15 10:00:00",
            "completed_order_status": "COMPLETED",
            "net_paid_amount": net_paid,
            "total_refunded_amount": 0.0,
            "dispute_status": "NONE",
            "shipping_charged": 5.00,
            "actual_shipping_cost": 7.50,
            "gateway_fee": round(net_paid * 0.029 + 0.30, 2),
            "is_cancelled": False,
            "test_case_id": f"C03-VIP-CEIL-POP-{i:02d}",
        })
        line_items.append({
            "line_item_id": f"LI-CEIL-{i:02d}",
            "order_id": oid,
            "product_id": "SKU-BEA-101",
            "variant_id": "VAR-BEA-101",
            "category": "beauty",
            "quantity": 1,
            "gross_price": net_paid,
            "discount_amount": 0.0,
            "net_price": net_paid,
            "actual_cogs": round(net_paid * 0.35, 2),
            "category_avg_cogs": CATEGORY_COGS_BENCHMARKS["beauty"],
            "is_returned": False,
            "is_sellable": False,
            "refund_amount": 0.0,
            "restocking_cost": 0.0,
            "test_case_id": f"C03-VIP-CEIL-POP-{i:02d}",
        })

    # Scenario C03-SAME-DAY-001: Same-day 3-order repeat customer (Span=0, Rhythm=0)
    cid_sameday = "CUST-C03-SAMEDAY-001"
    customers.append({
        "customer_id": cid_sameday,
        "first_name": "Sam",
        "last_name": "Sameday",
        "email": "sam.sameday@example.com",
        "created_at": "2026-05-01 08:00:00",
        "test_case_id": "C03-SAME-DAY-001",
    })
    for o_idx in [1, 2, 3]:
        oid = f"ORD-SAMEDAY-{o_idx}"
        orders.append({
            "order_id": oid,
            "customer_id": cid_sameday,
            "order_date": "2026-05-01 12:00:00",
            "completed_order_status": "COMPLETED",
            "net_paid_amount": 1000.00,
            "total_refunded_amount": 0.0,
            "dispute_status": "NONE",
            "shipping_charged": 0.0,
            "actual_shipping_cost": 5.00,
            "gateway_fee": 29.30,
            "is_cancelled": False,
            "test_case_id": "C03-SAME-DAY-001",
        })
        line_items.append({
            "line_item_id": f"LI-SAMEDAY-{o_idx}",
            "order_id": oid,
            "product_id": f"SKU-FAS-{o_idx}",
            "variant_id": f"VAR-FAS-{o_idx}",
            "category": "fashion",
            "quantity": 1,
            "gross_price": 1000.00,
            "discount_amount": 0.0,
            "net_price": 1000.00,
            "actual_cogs": 350.00,
            "category_avg_cogs": CATEGORY_COGS_BENCHMARKS["fashion"],
            "is_returned": False,
            "is_sellable": False,
            "refund_amount": 0.0,
            "restocking_cost": 0.0,
            "test_case_id": "C03-SAME-DAY-001",
        })

    # Scenario C03-ATRISK-BOUNDARIES: Rhythm = 50.0d -> 2*R = 100.0d
    # 99d (Safe), 100d (Safe), 101d (At Risk)
    risk_configs = [
        ("CUST-RISK-99", "2026-04-24", 99, False, "C03-RISK-BOUNDARY-99D"),
        ("CUST-RISK-100", "2026-04-23", 100, False, "C03-RISK-BOUNDARY-100D"),
        ("CUST-RISK-101", "2026-04-22", 101, True, "C03-RISK-BOUNDARY-101D"),
    ]
    for cid, last_d_str, days_since, is_risk, t_id in risk_configs:
        customers.append({
            "customer_id": cid,
            "first_name": "Risk",
            "last_name": f"Test{days_since}",
            "email": f"risk{days_since}@example.com",
            "created_at": "2025-10-01 00:00:00",
            "test_case_id": t_id,
        })
        last_dt = datetime.strptime(last_d_str, "%Y-%m-%d")
        d4 = last_dt
        d3 = d4 - timedelta(days=50)
        d2 = d3 - timedelta(days=50)
        d1 = d2 - timedelta(days=50)
        for idx, odt in enumerate([d1, d2, d3, d4], start=1):
            oid = f"ORD-{cid}-{idx}"
            orders.append({
                "order_id": oid,
                "customer_id": cid,
                "order_date": odt.strftime("%Y-%m-%d %H:%M:%S"),
                "completed_order_status": "COMPLETED",
                "net_paid_amount": 500.00,
                "total_refunded_amount": 0.0,
                "dispute_status": "NONE",
                "shipping_charged": 10.00,
                "actual_shipping_cost": 12.00,
                "gateway_fee": 14.80,
                "is_cancelled": False,
                "test_case_id": t_id,
            })
            line_items.append({
                "line_item_id": f"LI-{cid}-{idx}",
                "order_id": oid,
                "product_id": "SKU-LUX-500",
                "variant_id": "VAR-LUX-500",
                "category": "luxury",
                "quantity": 1,
                "gross_price": 500.00,
                "discount_amount": 0.0,
                "net_price": 500.00,
                "actual_cogs": 180.00,
                "category_avg_cogs": CATEGORY_COGS_BENCHMARKS["luxury"],
                "is_returned": False,
                "is_sellable": False,
                "refund_amount": 0.0,
                "restocking_cost": 0.0,
                "test_case_id": t_id,
            })

    # Scenario C03-ELIGIBILITY-EXCLUSIONS: Return Rate 40.0% vs 40.1%, Disputes
    elig_configs = [
        ("CUST-RR-400", 10, 4, "NONE", True, "C03-ELIG-RR-40-IN"),
        ("CUST-RR-401", 100, 41, "NONE", False, "C03-ELIG-RR-41-OUT"),
        ("CUST-DISP-OPEN", 2, 0, "OPEN", False, "C03-ELIG-DISP-OPEN-OUT"),
        ("CUST-DISP-LOST", 2, 0, "LOST", False, "C03-ELIG-DISP-LOST-OUT"),
        ("CUST-DISP-WON", 2, 0, "WON", True, "C03-ELIG-DISP-WON-IN"),
        ("CUST-ZERO-NET", 1, 0, "NONE", False, "C03-ELIG-ZERO-NET-OUT"),
    ]
    for cid, tot_items, ret_items, disp_st, is_el, t_id in elig_configs:
        customers.append({
            "customer_id": cid,
            "first_name": "Elig",
            "last_name": cid,
            "email": f"{cid.lower()}@example.com",
            "created_at": "2026-01-01 00:00:00",
            "test_case_id": t_id,
        })
        oid = f"ORD-{cid}-1"
        is_zero_net = (cid == "CUST-ZERO-NET")
        net_paid = 1000.00 if not is_zero_net else 200.00
        ref_amt = 1000.00 * (ret_items / tot_items) if not is_zero_net else 200.00
        orders.append({
            "order_id": oid,
            "customer_id": cid,
            "order_date": "2026-02-01 10:00:00",
            "completed_order_status": "COMPLETED",
            "net_paid_amount": net_paid,
            "total_refunded_amount": ref_amt,
            "dispute_status": disp_st,
            "shipping_charged": 0.0,
            "actual_shipping_cost": 8.00,
            "gateway_fee": 29.30,
            "is_cancelled": False,
            "test_case_id": t_id,
        })
        for item_i in range(1, tot_items + 1):
            is_item_ret = item_i <= ret_items
            item_p = net_paid / tot_items
            line_items.append({
                "line_item_id": f"LI-{cid}-{item_i}",
                "order_id": oid,
                "product_id": "SKU-PET-01",
                "variant_id": "VAR-PET-01",
                "category": "pet_care",
                "quantity": 1,
                "gross_price": item_p,
                "discount_amount": 0.0,
                "net_price": item_p,
                "actual_cogs": round(item_p * 0.50, 2),
                "category_avg_cogs": CATEGORY_COGS_BENCHMARKS["pet_care"],
                "is_returned": is_item_ret,
                "is_sellable": False,
                "refund_amount": item_p if is_item_ret else 0.0,
                "restocking_cost": 2.0 if is_item_ret else 0.0,
                "test_case_id": t_id,
            })

    # -------------------------------------------------------------
    # 2. CONTROLLED TEST SCENARIOS FOR C07 (Subscriptions & Retries)
    # -------------------------------------------------------------
    
    # Register subscriber customer profiles in dim_customers
    for s_idx in range(1, 6):
        cid_sub = f"CUST-SUB-{s_idx:03d}"
        customers.append({
            "customer_id": cid_sub,
            "first_name": "Subscriber",
            "last_name": f"User{s_idx}",
            "email": f"subscriber{s_idx}@example.com",
            "created_at": "2025-12-01 00:00:00",
            "test_case_id": f"C07-SUBSCRIBER-{s_idx}",
        })

    # C07-DEDUP-001: 3 failed retries for same subscription + same billing cycle
    subscriptions.append({
        "subscription_id": "SUB-DEDUP-001",
        "customer_id": "CUST-SUB-001",
        "plan_id": "PLAN-MONTHLY-50",
        "plan_type": "MONTHLY",
        "plan_billing_interval": "MONTHLY",
        "status": "IN_RETRY",
        "start_date": "2026-01-01",
        "average_plan_tenure_months": 10.0,
        "months_completed_before_churn": 4.0,
        "is_voluntary_cancelled": False,
        "cancellation_timestamp": None,
        "test_case_id": "C07-DEDUP-3-RETRIES-1-EVENT",
    })
    for r_num, ev_d in [(1, "2026-07-10"), (2, "2026-07-13"), (3, "2026-07-16")]:
        sub_events.append({
            "event_id": f"EV-DEDUP-{r_num}",
            "subscription_id": "SUB-DEDUP-001",
            "billing_cycle_id": "CYCLE-2026-07",
            "event_date": ev_d,
            "invoice_amount": 50.00,
            "retry_number": r_num,
            "payment_status": "FAILED",
            "is_terminal_failure": (r_num == 3),
            "is_voluntary_cancelled": False,
            "test_case_id": "C07-DEDUP-3-RETRIES-1-EVENT",
        })

    # C07-RECOVER-001: Succeeded on retry 3 -> $0 exposure
    subscriptions.append({
        "subscription_id": "SUB-RECOVER-001",
        "customer_id": "CUST-SUB-002",
        "plan_id": "PLAN-MONTHLY-80",
        "plan_type": "MONTHLY",
        "plan_billing_interval": "MONTHLY",
        "status": "ACTIVE",
        "start_date": "2026-01-01",
        "average_plan_tenure_months": 10.0,
        "months_completed_before_churn": 3.0,
        "is_voluntary_cancelled": False,
        "cancellation_timestamp": None,
        "test_case_id": "C07-RETRY-SUCCESS-RECOVERY",
    })
    sub_events.append({
        "event_id": "EV-REC-1", "subscription_id": "SUB-RECOVER-001", "billing_cycle_id": "CYCLE-2026-07",
        "event_date": "2026-07-10", "invoice_amount": 80.00, "retry_number": 1, "payment_status": "FAILED",
        "is_terminal_failure": False, "is_voluntary_cancelled": False, "test_case_id": "C07-RETRY-SUCCESS-RECOVERY",
    })
    sub_events.append({
        "event_id": "EV-REC-2", "subscription_id": "SUB-RECOVER-001", "billing_cycle_id": "CYCLE-2026-07",
        "event_date": "2026-07-13", "invoice_amount": 80.00, "retry_number": 2, "payment_status": "FAILED",
        "is_terminal_failure": False, "is_voluntary_cancelled": False, "test_case_id": "C07-RETRY-SUCCESS-RECOVERY",
    })
    sub_events.append({
        "event_id": "EV-REC-3", "subscription_id": "SUB-RECOVER-001", "billing_cycle_id": "CYCLE-2026-07",
        "event_date": "2026-07-16", "invoice_amount": 80.00, "retry_number": 3, "payment_status": "SUCCESS",
        "is_terminal_failure": False, "is_voluntary_cancelled": False, "test_case_id": "C07-RETRY-SUCCESS-RECOVERY",
    })

    # C07-VOLUNTARY-001: Voluntary cancel takes priority
    subscriptions.append({
        "subscription_id": "SUB-VOL-001",
        "customer_id": "CUST-SUB-003",
        "plan_id": "PLAN-MONTHLY-100",
        "plan_type": "MONTHLY",
        "plan_billing_interval": "MONTHLY",
        "status": "CANCELLED",
        "start_date": "2026-01-01",
        "average_plan_tenure_months": 10.0,
        "months_completed_before_churn": 3.0,
        "is_voluntary_cancelled": True,
        "cancellation_timestamp": "2026-07-12 14:00:00",
        "test_case_id": "C07-VOLUNTARY-PRIORITY",
    })
    sub_events.append({
        "event_id": "EV-VOL-1", "subscription_id": "SUB-VOL-001", "billing_cycle_id": "CYCLE-2026-07",
        "event_date": "2026-07-10", "invoice_amount": 100.00, "retry_number": 1, "payment_status": "FAILED",
        "is_terminal_failure": True, "is_voluntary_cancelled": True, "test_case_id": "C07-VOLUNTARY-PRIORITY",
    })

    # C07-FALLBACK-MONTHLY & ANNUAL: Missing average plan tenure
    subscriptions.append({
        "subscription_id": "SUB-FALLBACK-M", "customer_id": "CUST-SUB-004", "plan_id": "PLAN-M",
        "plan_type": "MONTHLY", "plan_billing_interval": "MONTHLY", "status": "TERMINATED_PAYMENT_FAILED",
        "start_date": "2026-01-01", "average_plan_tenure_months": None, "months_completed_before_churn": 2.0,
        "is_voluntary_cancelled": False, "cancellation_timestamp": None, "test_case_id": "C07-FALLBACK-MONTHLY-6M",
    })
    sub_events.append({
        "event_id": "EV-FBM-1", "subscription_id": "SUB-FALLBACK-M", "billing_cycle_id": "CYCLE-2026-07",
        "event_date": "2026-07-15", "invoice_amount": 100.00, "retry_number": 3, "payment_status": "FAILED",
        "is_terminal_failure": True, "is_voluntary_cancelled": False, "test_case_id": "C07-FALLBACK-MONTHLY-6M",
    })
    subscriptions.append({
        "subscription_id": "SUB-FALLBACK-A", "customer_id": "CUST-SUB-005", "plan_id": "PLAN-A",
        "plan_type": "ANNUAL", "plan_billing_interval": "ANNUAL", "status": "TERMINATED_PAYMENT_FAILED",
        "start_date": "2025-07-01", "average_plan_tenure_months": None, "months_completed_before_churn": 12.0,
        "is_voluntary_cancelled": False, "cancellation_timestamp": None, "test_case_id": "C07-FALLBACK-ANNUAL-1CYCLE",
    })
    sub_events.append({
        "event_id": "EV-FBA-1", "subscription_id": "SUB-FALLBACK-A", "billing_cycle_id": "CYCLE-2026-07",
        "event_date": "2026-07-15", "invoice_amount": 1000.00, "retry_number": 3, "payment_status": "FAILED",
        "is_terminal_failure": True, "is_voluntary_cancelled": False, "test_case_id": "C07-FALLBACK-ANNUAL-1CYCLE",
    })

    # -------------------------------------------------------------
    # 3. CONTROLLED TEST SCENARIOS FOR C09 (Profitability, Sellable Returns, Missing COGS)
    # -------------------------------------------------------------
    
    # C09-SELLABLE vs DAMAGED: Restocking condition
    for is_sell, cid, t_id in [(True, "CUST-C09-SELLABLE", "C09-RESTOCK-SELLABLE-CREDIT"),
                               (False, "CUST-C09-DAMAGED", "C09-RESTOCK-DAMAGED-LOSS")]:
        customers.append({
            "customer_id": cid, "first_name": "Return", "last_name": cid,
            "email": f"{cid.lower()}@example.com", "created_at": "2026-01-01 00:00:00", "test_case_id": t_id,
        })
        oid = f"ORD-{cid}-1"
        orders.append({
            "order_id": oid, "customer_id": cid, "order_date": "2026-01-10 10:00:00",
            "completed_order_status": "COMPLETED", "net_paid_amount": 100.00, "total_refunded_amount": 100.00,
            "dispute_status": "NONE", "shipping_charged": 0.0, "actual_shipping_cost": 10.00,
            "gateway_fee": 3.00, "is_cancelled": False, "test_case_id": t_id,
        })
        line_items.append({
            "line_item_id": f"LI-{cid}-1", "order_id": oid, "product_id": "SKU-HOM-10", "variant_id": "VAR-HOM-10",
            "category": "home_goods", "quantity": 1, "gross_price": 100.00, "discount_amount": 0.0,
            "net_price": 100.00, "actual_cogs": 40.00, "category_avg_cogs": CATEGORY_COGS_BENCHMARKS["home_goods"],
            "is_returned": True, "is_sellable": is_sell, "refund_amount": 100.00, "restocking_cost": 5.00, "test_case_id": t_id,
        })

    # C09-MISSING-COGS-UNCERTAIN: Missing actual & category COGS
    cid_nocogs = "CUST-C09-NOCOGS"
    customers.append({
        "customer_id": cid_nocogs, "first_name": "NoCogs", "last_name": "Test",
        "email": "nocogs@example.com", "created_at": "2026-01-01 00:00:00", "test_case_id": "C09-MISSING-CATEGORY-COGS-UNRESOLVED",
    })
    oid_nocogs = "ORD-NOCOGS-1"
    orders.append({
        "order_id": oid_nocogs, "customer_id": cid_nocogs, "order_date": "2026-01-15 10:00:00",
        "completed_order_status": "COMPLETED", "net_paid_amount": 100.00, "total_refunded_amount": 0.0,
        "dispute_status": "NONE", "shipping_charged": 5.00, "actual_shipping_cost": 8.00,
        "gateway_fee": 3.20, "is_cancelled": False, "test_case_id": "C09-MISSING-CATEGORY-COGS-UNRESOLVED",
    })
    line_items.append({
        "line_item_id": "LI-NOCOGS-1", "order_id": oid_nocogs, "product_id": "SKU-UNMAPPED-99", "variant_id": "VAR-UNMAPPED-99",
        "category": "unmapped_custom_tier", "quantity": 1, "gross_price": 100.00, "discount_amount": 0.0,
        "net_price": 100.00, "actual_cogs": None, "category_avg_cogs": None,
        "is_returned": False, "is_sellable": False, "refund_amount": 0.0, "restocking_cost": 0.0,
        "test_case_id": "C09-MISSING-CATEGORY-COGS-UNRESOLVED",
    })

    # Support Tickets
    support_tickets.append({
        "ticket_id": "TICK-001", "customer_id": "CUST-CEIL-01", "order_id": "ORD-CEIL-01",
        "ticket_date": "2026-02-01 11:00:00", "support_cost": 15.00, "status": "CLOSED",
    })

    # -------------------------------------------------------------
    # 4. CONTROLLED TEST SCENARIOS FOR C11 (Established VIP & Inactivity)
    # -------------------------------------------------------------
    
    # C11-ESTABLISHED: 4 orders spanning 150 days ($2000 spend) -> Established VIP
    cid_c11_lost = "CUST-C11-LOST-VIP"
    customers.append({
        "customer_id": cid_c11_lost, "first_name": "Lost", "last_name": "VIP",
        "email": "lost.vip@example.com", "created_at": "2025-08-05 00:00:00", "test_case_id": "C11-LOST-ESTABLISHED-VIP",
    })
    c11_dates = ["2025-08-05", "2025-11-03", "2026-01-02", "2026-04-01"] # span=239d, last order 122d ago > 90d -> LOST
    for idx, d_s in enumerate(c11_dates, start=1):
        oid = f"ORD-C11LOST-{idx}"
        orders.append({
            "order_id": oid, "customer_id": cid_c11_lost, "order_date": f"{d_s} 10:00:00",
            "completed_order_status": "COMPLETED", "net_paid_amount": 500.00, "total_refunded_amount": 0.0,
            "dispute_status": "NONE", "shipping_charged": 0.0, "actual_shipping_cost": 10.00,
            "gateway_fee": 14.80, "is_cancelled": False, "test_case_id": "C11-LOST-ESTABLISHED-VIP",
        })
        line_items.append({
            "line_item_id": f"LI-C11LOST-{idx}", "order_id": oid, "product_id": "SKU-LUX-01", "variant_id": "VAR-LUX-01",
            "category": "luxury", "quantity": 1, "gross_price": 500.00, "discount_amount": 0.0,
            "net_price": 500.00, "actual_cogs": 175.00, "category_avg_cogs": CATEGORY_COGS_BENCHMARKS["luxury"],
            "is_returned": False, "is_sellable": False, "refund_amount": 0.0, "restocking_cost": 0.0,
            "test_case_id": "C11-LOST-ESTABLISHED-VIP",
        })

    # C11-NON-ESTABLISHED: 1 order of $5000 -> High spend VIP but NOT established (<3 orders)
    cid_c11_nonest = "CUST-C11-1ORD-NONEST"
    customers.append({
        "customer_id": cid_c11_nonest, "first_name": "OneTime", "last_name": "BigSpender",
        "email": "bigspender@example.com", "created_at": "2026-01-01 00:00:00", "test_case_id": "C11-NON-ESTABLISHED-1ORDER",
    })
    orders.append({
        "order_id": "ORD-C11NONEST-1", "customer_id": cid_c11_nonest, "order_date": "2026-01-01 10:00:00",
        "completed_order_status": "COMPLETED", "net_paid_amount": 5000.00, "total_refunded_amount": 0.0,
        "dispute_status": "NONE", "shipping_charged": 0.0, "actual_shipping_cost": 25.00,
        "gateway_fee": 145.30, "is_cancelled": False, "test_case_id": "C11-NON-ESTABLISHED-1ORDER",
    })
    line_items.append({
        "line_item_id": "LI-C11NONEST-1", "order_id": "ORD-C11NONEST-1", "product_id": "SKU-LUX-99", "variant_id": "VAR-LUX-99",
        "category": "luxury", "quantity": 1, "gross_price": 5000.00, "discount_amount": 0.0,
        "net_price": 5000.00, "actual_cogs": 1750.00, "category_avg_cogs": CATEGORY_COGS_BENCHMARKS["luxury"],
        "is_returned": False, "is_sellable": False, "refund_amount": 0.0, "restocking_cost": 0.0,
        "test_case_id": "C11-NON-ESTABLISHED-1ORDER",
    })

    # Convert to DataFrames
    df_customers = pd.DataFrame(customers)
    df_orders = pd.DataFrame(orders)
    df_line_items = pd.DataFrame(line_items)
    df_subscriptions = pd.DataFrame(subscriptions)
    df_sub_events = pd.DataFrame(sub_events)
    df_support = pd.DataFrame(support_tickets)
    
    # Category benchmarks DataFrame
    benchmarks_data = [{"category": k, "benchmark_cogs_amount": v} for k, v in CATEGORY_COGS_BENCHMARKS.items()]
    df_benchmarks = pd.DataFrame(benchmarks_data)

    # Derived Monthly VIP snapshot table (for evaluation date 2026-08-01)
    vip_records = [
        {"snapshot_date": "2026-08-01", "customer_id": cid_c11_lost, "vip_rank": 1, "is_vip": True, "retained_spend_365d": 2000.00},
        {"snapshot_date": "2026-08-01", "customer_id": "CUST-CEIL-15", "vip_rank": 2, "is_vip": True, "retained_spend_365d": 1500.00},
        {"snapshot_date": "2026-08-01", "customer_id": "CUST-CEIL-14", "vip_rank": 3, "is_vip": True, "retained_spend_365d": 1400.00},
    ]
    df_vip_monthly = pd.DataFrame(vip_records)

    return (
        df_customers,
        df_orders,
        df_line_items,
        df_subscriptions,
        df_sub_events,
        df_benchmarks,
        df_support,
        df_vip_monthly,
    )


def save_category3_datasets() -> None:
    """Generates and persists Category 3 datasets."""
    os.makedirs("data", exist_ok=True)
    
    (
        df_customers,
        df_orders,
        df_line_items,
        df_subscriptions,
        df_sub_events,
        df_benchmarks,
        df_support,
        df_vip_monthly,
    ) = build_controlled_category3_dataset()

    logger.info("Saving Category 3 datasets...")
    df_customers.to_csv("data/category3_customers.csv.gz", index=False, compression="gzip")
    df_orders.to_csv("data/category3_orders.csv.gz", index=False, compression="gzip")
    df_line_items.to_csv("data/category3_line_items.csv.gz", index=False, compression="gzip")
    df_subscriptions.to_csv("data/category3_subscriptions.csv.gz", index=False, compression="gzip")
    df_sub_events.to_csv("data/category3_subscription_events.csv.gz", index=False, compression="gzip")
    df_benchmarks.to_csv("data/category3_category_cogs_benchmarks.csv", index=False)
    df_support.to_csv("data/category3_support_tickets.csv.gz", index=False, compression="gzip")
    df_vip_monthly.to_csv("data/category3_vip_monthly.csv.gz", index=False, compression="gzip")
    
    logger.info("Category 3 datasets generated successfully!")


if __name__ == "__main__":
    save_category3_datasets()

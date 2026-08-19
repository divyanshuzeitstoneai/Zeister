"""src/shopify/parser.py — Shopify GraphQL Response Parser & Schema Mapper.

Maps raw nested GraphQL responses from Shopify Admin API (2024-10+) directly
into our flat relational data structures (df_orders and df_line_items).

GraphQL Query Reference:
-------------------------
query GetOrdersForScoring($cursor: String) {
  orders(first: 50, after: $cursor, sortKey: CREATED_AT, reverse: true) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      id
      name
      createdAt
      currencyCode
      cancelledAt
      totalPriceSet { shopMoney { amount } }
      totalDiscountsSet { shopMoney { amount } }
      shippingLines(first: 5) {
        nodes {
          originalPriceSet { shopMoney { amount } }
        }
      }
      transactions(first: 10) {
        fees {
          amount { amount }
        }
      }
      refunds {
        totalRefundedSet { shopMoney { amount } }
        refundLineItems(first: 20) {
          nodes {
            lineItem { id }
            subtotalSet { shopMoney { amount } }
          }
        }
      }
      lineItems(first: 50) {
        nodes {
          id
          quantity
          originalTotalSet { shopMoney { amount } }
          discountedTotalSet { shopMoney { amount } }
          product {
            productType
            tags
          }
          variant {
            id
            sku
            weight
            weightUnit
            inventoryItem {
              unitCost { amount }
            }
            metafields(first: 5, namespace: "dimensions") {
              nodes {
                key
                value
              }
            }
          }
        }
      }
    }
  }
}
"""

from __future__ import annotations
from typing import Any
import pandas as pd
import numpy as np


def parse_shopify_graphql_order_node(order_node: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parses a single GraphQL Order node into order-level and line-item-level dictionaries."""
    order_id = order_node.get("name") or order_node.get("id", "").split("/")[-1]
    created_at = order_node.get("createdAt")
    currency = order_node.get("currencyCode", "USD")
    is_cancelled = order_node.get("cancelledAt") is not None
    
    # Gross & Net revenue
    gross_sales = float(order_node.get("totalPriceSet", {}).get("shopMoney", {}).get("amount", 0.0))
    
    # Shipping charged
    shipping_lines = order_node.get("shippingLines", {}).get("nodes", [])
    shipping_charged = sum(
        float(sl.get("originalPriceSet", {}).get("shopMoney", {}).get("amount", 0.0))
        for sl in shipping_lines
    )
    
    # Payment gateway fee
    transactions = order_node.get("transactions", [])
    gateway_fee = 0.0
    has_gw_fee = False
    for tx in transactions:
        fees = tx.get("fees", [])
        if fees:
            has_gw_fee = True
            for fee in fees:
                gateway_fee += float(fee.get("amount", {}).get("amount", 0.0))
    
    order_gw_fee = gateway_fee if has_gw_fee else np.nan

    # Refund details
    refunds = order_node.get("refunds", [])
    refunded_line_item_ids = set()
    for ref in refunds:
        for rli in ref.get("refundLineItems", {}).get("nodes", []):
            li_id = rli.get("lineItem", {}).get("id")
            if li_id:
                refunded_line_item_ids.add(li_id)

    order_record = {
        "order_id": order_id,
        "created_at": created_at,
        "channel": "web",  # Default unless populated by custom tags or marketplace app
        "currency": currency,
        "gross_sales": gross_sales,
        "net_sales": gross_sales,  # refined by line items
        "shipping_charged_to_customer": shipping_charged,
        "actual_shipping_cost": np.nan,  # Must be joined from Courier API (Shiprocket/EasyPost)
        "gateway_fee": order_gw_fee,
        "free_shipping_applied": shipping_charged == 0.0,
        "is_cancelled": is_cancelled,
        "chargeback_amount": 0.0,
    }

    # Parse Line Items
    line_item_records = []
    raw_line_items = order_node.get("lineItems", {}).get("nodes", [])

    for li in raw_line_items:
        li_id = li.get("id", "").split("/")[-1]
        qty = li.get("quantity", 1)
        orig_price = float(li.get("originalTotalSet", {}).get("shopMoney", {}).get("amount", 0.0))
        net_price = float(li.get("discountedTotalSet", {}).get("shopMoney", {}).get("amount", orig_price))
        discount_given = max(0.0, orig_price - net_price)
        
        variant = li.get("variant") or {}
        sku = variant.get("sku") or variant.get("id", "").split("/")[-1]
        
        # Product Category
        product = li.get("product") or {}
        category = product.get("productType") or "other"
        
        # COGS (unit cost)
        inv_item = variant.get("inventoryItem") or {}
        unit_cost_obj = inv_item.get("unitCost")
        cogs_val = float(unit_cost_obj.get("amount", 0.0)) * qty if unit_cost_obj else np.nan
        
        # Weight
        weight_raw = variant.get("weight", 0.0)
        weight_unit = variant.get("weightUnit", "KILOGRAMS")
        if weight_unit == "GRAMS":
            weight_kg = weight_raw / 1000.0
        elif weight_unit == "OUNCES":
            weight_kg = weight_raw * 0.0283495
        elif weight_unit == "POUNDS":
            weight_kg = weight_raw * 0.453592
        else:
            weight_kg = weight_raw
            
        weight_kg = weight_kg * qty

        # Custom Metafield Dimensions (Length, Width, Height)
        len_cm, wid_cm, hgt_cm = np.nan, np.nan, np.nan
        metafields = variant.get("metafields", {}).get("nodes", [])
        for mf in metafields:
            k = mf.get("key", "").lower()
            v = mf.get("value")
            try:
                if "length" in k:
                    len_cm = float(v)
                elif "width" in k:
                    wid_cm = float(v)
                elif "height" in k:
                    hgt_cm = float(v)
            except (ValueError, TypeError):
                pass

        is_returned = (li.get("id") in refunded_line_item_ids) or (li_id in refunded_line_item_ids)

        line_item_records.append({
            "order_id": order_id,
            "line_item_id": li_id,
            "product_id": sku,
            "category": category.lower(),
            "quantity": qty,
            "selling_price": orig_price,
            "discount_given": discount_given,
            "net_selling_price": net_price,
            "is_discounted": discount_given > 0,
            "cogs_total": cogs_val,
            "product_weight_kg": weight_kg,
            "length_cm": len_cm,
            "width_cm": wid_cm,
            "height_cm": hgt_cm,
            "is_returned": is_returned,
            "return_reason": None,
            "refund_amount": net_price if is_returned else 0.0,
            "restocking_cost": 0.0,
            "channel_fee_pct": 0.0,
        })

    return order_record, line_item_records


def parse_graphql_orders_payload(payload: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Transforms a full GraphQL response payload into Orders and Line Items DataFrames."""
    order_nodes = payload.get("data", {}).get("orders", {}).get("nodes", [])
    all_orders = []
    all_line_items = []

    for node in order_nodes:
        ord_rec, li_recs = parse_shopify_graphql_order_node(node)
        all_orders.append(ord_rec)
        all_line_items.extend(li_recs)

    df_orders = pd.DataFrame(all_orders)
    df_line_items = pd.DataFrame(all_line_items)
    return df_orders, df_line_items

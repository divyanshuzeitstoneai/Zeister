"""tests/test_shopify_parser.py — Tests Shopify GraphQL parser and schema mapping."""

import pytest
import pandas as pd
from src.shopify.parser import parse_shopify_graphql_order_node, parse_graphql_orders_payload


@pytest.fixture
def mock_shopify_graphql_payload():
    """Realistic mock response node from Shopify GraphQL Admin API (2024-10)."""
    return {
        "data": {
            "orders": {
                "nodes": [
                    {
                        "id": "gid://shopify/Order/1001",
                        "name": "ORD-1001",
                        "createdAt": "2025-06-15T14:30:00Z",
                        "currencyCode": "USD",
                        "cancelledAt": None,
                        "totalPriceSet": {"shopMoney": {"amount": "145.00"}},
                        "totalDiscountsSet": {"shopMoney": {"amount": "15.00"}},
                        "shippingLines": {
                            "nodes": [
                                {"originalPriceSet": {"shopMoney": {"amount": "5.00"}}}
                            ]
                        },
                        "transactions": [
                            {"fees": [{"amount": {"amount": "4.20"}}]}
                        ],
                        "refunds": [
                            {
                                "totalRefundedSet": {"shopMoney": {"amount": "45.00"}},
                                "refundLineItems": {
                                    "nodes": [
                                        {"lineItem": {"id": "gid://shopify/LineItem/202"}}
                                    ]
                                }
                            }
                        ],
                        "lineItems": {
                            "nodes": [
                                {
                                    "id": "gid://shopify/LineItem/201",
                                    "quantity": 1,
                                    "originalTotalSet": {"shopMoney": {"amount": "100.00"}},
                                    "discountedTotalSet": {"shopMoney": {"amount": "95.00"}},
                                    "product": {"productType": "Electronics", "tags": ["gadget"]},
                                    "variant": {
                                        "id": "gid://shopify/ProductVariant/501",
                                        "sku": "SKU-ELEC-501",
                                        "weight": 500,
                                        "weightUnit": "GRAMS",
                                        "inventoryItem": {"unitCost": {"amount": "40.00"}},
                                        "metafields": {
                                            "nodes": [
                                                {"key": "length", "value": "20"},
                                                {"key": "width", "value": "15"},
                                                {"key": "height", "value": "10"}
                                            ]
                                        }
                                    }
                                },
                                {
                                    "id": "gid://shopify/LineItem/202",
                                    "quantity": 1,
                                    "originalTotalSet": {"shopMoney": {"amount": "50.00"}},
                                    "discountedTotalSet": {"shopMoney": {"amount": "45.00"}},
                                    "product": {"productType": "Fashion", "tags": ["apparel"]},
                                    "variant": {
                                        "id": "gid://shopify/ProductVariant/502",
                                        "sku": "SKU-FASH-502",
                                        "weight": 1.2,
                                        "weightUnit": "KILOGRAMS",
                                        "inventoryItem": None,  # Missing COGS simulation
                                        "metafields": {"nodes": []}
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }
    }


def test_parser_transforms_graphql_payload_to_relational_tables(mock_shopify_graphql_payload):
    df_orders, df_line_items = parse_graphql_orders_payload(mock_shopify_graphql_payload)
    
    # 1. Verify Orders Table
    assert len(df_orders) == 1
    ord_row = df_orders.iloc[0]
    assert ord_row["order_id"] == "ORD-1001"
    assert ord_row["currency"] == "USD"
    assert ord_row["gross_sales"] == 145.00
    assert ord_row["shipping_charged_to_customer"] == 5.00
    assert ord_row["gateway_fee"] == 4.20
    assert not ord_row["is_cancelled"]
    
    # 2. Verify Line Items Table
    assert len(df_line_items) == 2
    
    # First line item: Electronics with dimensions and weight in grams -> kg
    li_1 = df_line_items[df_line_items["line_item_id"] == "201"].iloc[0]
    assert li_1["category"] == "electronics"
    assert li_1["selling_price"] == 100.00
    assert li_1["discount_given"] == 5.00
    assert li_1["net_selling_price"] == 95.00
    assert li_1["cogs_total"] == 40.00
    assert li_1["product_weight_kg"] == pytest.approx(0.5)  # 500 grams = 0.5 kg
    assert li_1["length_cm"] == 20.0
    assert li_1["width_cm"] == 15.0
    assert li_1["height_cm"] == 10.0
    assert not li_1["is_returned"]
    
    # Second line item: Fashion, missing COGS, returned
    li_2 = df_line_items[df_line_items["line_item_id"] == "202"].iloc[0]
    assert li_2["category"] == "fashion"
    assert pd.isna(li_2["cogs_total"])  # Missing COGS preserved as NaN
    assert bool(li_2["is_returned"]) is True  # Detected from refunds node
    assert li_2["refund_amount"] == 45.00

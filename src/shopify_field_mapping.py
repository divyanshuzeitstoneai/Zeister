"""src/shopify_field_mapping.py — Shopify GraphQL field mapping reference.

Documents where each internal column comes from in Shopify's Admin API.
Used for validation when connecting to a real store.

Availability statuses:
    native          — standard Shopify field, reliably available
    conditional     — native field but frequently null (depends on store config)
    external_only   — not available from Shopify; requires external data source
    metafield       — only available if merchant configured custom metafields
    derived         — computed from other fields, not directly stored

References:
    - Shopify Admin API GraphQL: Order, LineItem, ProductVariant, InventoryItem
    - Community forum: dimensions not natively supported (merchants request this)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldMapping:
    """Maps an internal column to its Shopify GraphQL source."""
    internal_name: str
    shopify_path: str
    availability: str  # native | conditional | external_only | metafield | derived
    needed_by: tuple[str, ...]
    notes: str = ""


FIELD_MAPPINGS: list[FieldMapping] = [
    # --- Revenue / Price ---
    FieldMapping(
        internal_name="selling_price",
        shopify_path="Order.lineItems.nodes.originalTotalSet.shopMoney.amount",
        availability="native",
        needed_by=("F01", "F03", "F04", "F05"),
        notes="Original price before discounts",
    ),
    FieldMapping(
        internal_name="net_selling_price",
        shopify_path="Order.lineItems.nodes.discountedTotalSet.shopMoney.amount",
        availability="native",
        needed_by=("F01", "F03", "F04", "F05"),
        notes="Price after all discounts applied; reliable",
    ),
    FieldMapping(
        internal_name="discount_given",
        shopify_path="Order.totalDiscountsSet.shopMoney.amount",
        availability="native",
        needed_by=("F01",),
        notes="Order-level total discount amount",
    ),

    # --- COGS ---
    FieldMapping(
        internal_name="cogs_total",
        shopify_path="ProductVariant.inventoryItem.unitCost.amount",
        availability="conditional",
        needed_by=("F01", "F03"),
        notes="Native field but frequently null — many stores don't populate unitCost. "
              "Expect ~20%+ null rate in real data.",
    ),

    # --- Shipping ---
    FieldMapping(
        internal_name="shipping_charged_to_customer",
        shopify_path="Order.shippingLines.nodes.originalPriceSet.shopMoney.amount",
        availability="native",
        needed_by=("F04", "F05"),
        notes="What was CHARGED to the customer, not actual courier cost",
    ),
    FieldMapping(
        internal_name="actual_shipping_cost",
        shopify_path="N/A — not available from Shopify",
        availability="external_only",
        needed_by=("F04", "F05"),
        notes="Requires courier API integration (Shiprocket/Delhivery/EasyPost/ShipStation). "
              "Must be joined in from an external data source.",
    ),

    # --- Gateway Fee ---
    FieldMapping(
        internal_name="gateway_fee",
        shopify_path="Order.transactions.fees.amount",
        availability="conditional",
        needed_by=("F01", "F03"),
        notes="Only populated if store uses Shopify Payments. Null for stores using "
              "external payment gateways (Stripe, PayPal, Razorpay, etc). "
              "External gateway APIs needed for non-Shopify-Payments stores.",
    ),

    # --- Product Weight & Dimensions ---
    FieldMapping(
        internal_name="product_weight_kg",
        shopify_path="ProductVariant.weight + ProductVariant.weightUnit",
        availability="native",
        needed_by=("F04",),
        notes="Generally reliable; may need unit conversion from grams/ounces/pounds",
    ),
    FieldMapping(
        internal_name="length_cm",
        shopify_path="ProductVariant.metafields (custom)",
        availability="metafield",
        needed_by=("F04",),
        notes="No native Shopify field. ~5-10% of catalogs have this via custom metafields. "
              "Structural limitation, not a data-cleaning problem.",
    ),
    FieldMapping(
        internal_name="width_cm",
        shopify_path="ProductVariant.metafields (custom)",
        availability="metafield",
        needed_by=("F04",),
        notes="Same as length_cm — requires merchant to set up custom metafields",
    ),
    FieldMapping(
        internal_name="height_cm",
        shopify_path="ProductVariant.metafields (custom)",
        availability="metafield",
        needed_by=("F04",),
        notes="Same as length_cm — requires merchant to set up custom metafields",
    ),

    # --- Free-Shipping Threshold ---
    FieldMapping(
        internal_name="free_shipping_threshold",
        shopify_path="DiscountAutomaticNode or app-side configuration",
        availability="conditional",
        needed_by=("F04",),
        notes="Not a standard Shopify object. May live in automatic discount rules, "
              "shipping profile overrides, or third-party app config. "
              "Needs per-store confirmation of where this is configured.",
    ),

    # --- Returns ---
    FieldMapping(
        internal_name="is_returned",
        shopify_path="Order.refunds + RefundLineItem",
        availability="native",
        needed_by=("F01", "F03", "F10"),
        notes="Reliable for the fact of a return. Restocking cost is NOT in Shopify — "
              "it's an operational cost tracked outside the platform.",
    ),
    FieldMapping(
        internal_name="refund_amount",
        shopify_path="Order.refunds.totalRefundedSet.shopMoney.amount",
        availability="native",
        needed_by=("F01", "F03"),
    ),

    # --- Order Structure ---
    FieldMapping(
        internal_name="order_id",
        shopify_path="Order.id (or Order.name for display)",
        availability="native",
        needed_by=("F01", "F03", "F04", "F05"),
    ),
    FieldMapping(
        internal_name="category",
        shopify_path="Product.productType or Product.tags",
        availability="native",
        needed_by=("F01", "F03"),
        notes="Mapping depends on how merchant categorizes products — "
              "productType is most common but not standardized across stores.",
    ),
]


def get_fields_for_score(score: str) -> list[FieldMapping]:
    """Return all field mappings needed by a given score (e.g., 'F01')."""
    return [f for f in FIELD_MAPPINGS if score in f.needed_by]


def get_external_dependencies() -> list[FieldMapping]:
    """Return fields that require external (non-Shopify) data sources."""
    return [f for f in FIELD_MAPPINGS if f.availability in ("external_only", "metafield")]


def print_mapping_table():
    """Print a formatted summary table of all field mappings."""
    print(f"{'Internal Name':<35} {'Availability':<15} {'Scores':<20} {'Shopify Path'}")
    print("-" * 120)
    for f in FIELD_MAPPINGS:
        scores = ", ".join(f.needed_by)
        print(f"{f.internal_name:<35} {f.availability:<15} {scores:<20} {f.shopify_path}")


if __name__ == "__main__":
    print_mapping_table()
    print()
    print("=== External Dependencies ===")
    for f in get_external_dependencies():
        print(f"  {f.internal_name}: {f.notes}")

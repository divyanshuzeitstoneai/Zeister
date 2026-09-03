# Zeitster Synthetic Test Dataset — Generation Prompt

Paste this to your data-generation agent as-is. It defines the full multi-table
schema, realism requirements, and edge-case coverage needed to test any
formula in the Zeitster formula catalog (not just F01–F12 — this schema is
built to support the full ~120-formula set as more formulas get added).

---

## ROLE

You are generating a realistic, multi-table synthetic dataset that simulates
what Zeitster would actually ingest from Shopify + external sources (3PL,
payment gateways, marketplaces) for MULTIPLE merchants over time. This dataset
will be used to test business-scoring formulas end-to-end — not just formula
math in isolation, but the full pipeline: ingestion → reconciliation →
normalization → fallback logic → scoring.

## CORE PRINCIPLES

1. **Multi-tenant realism** — generate data for at least 8–10 distinct
   merchants, each with a different primary category (fashion, beauty,
   electronics, home_goods, pet_care, food_bev, etc.), different order volume,
   and different data completeness (some merchants have clean data, some have
   messy/missing data — this is realistic and required for fallback testing).

2. **Time realism** — orders should span at least 18 months, with a clear
   **cutover_date** per merchant (the date Zeitster metafield tracking began).
   Orders before cutover_date should have NO metafield history (simulating
   the bulk-load gap we discussed). Orders after cutover_date should have
   full metafield history with realistic update patterns.

3. **Referential integrity** — every foreign key must resolve. order_id in
   line_items must exist in orders. customer_id in orders must exist in
   customers. No orphan rows unless a test case explicitly requires simulating
   a broken/orphan record (tag those clearly).

4. **Field status realism** — every field must reflect its real-world
   reliability, matching this classification (from our Phase 4 mapping doc):
   - ✅ VERIFIED — always present on valid orders, never null
   - ⚠️ PARTIAL — null on manual/offline orders, populated on online-gateway
     orders (simulate both — target ~15-20% null rate)
   - ⚙️ METAFIELD — present only after merchant's cutover_date, and even then
     only ~70-85% of the time (some merchants never configure it)
   - ❌ EXTERNAL — present only if a matching 3PL/gateway/marketplace record
     exists; simulate ~5-10% of orders where the external record hasn't
     arrived yet (late/missing data, not an error)
   - 🧮 DERIVED — never generate this directly; it must be computable from
     other fields in the dataset (used to verify pipeline logic, not stored)

5. **No silent zeros** — never use 0 as a stand-in for missing/unknown data.
   Missing data must be represented as null/empty, with a separate flag
   column where applicable (e.g. is_cogs_estimated).

---

## TABLES TO GENERATE

### 1. `merchants` (dim_merchant)
merchant_id, merchant_name, primary_category, region, subscription_start_date,
cutover_date (metafield tracking start), data_quality_tier (clean/messy/mixed)

### 2. `customers`
customer_id, merchant_id, first_name, last_name, email, created_at,
is_vip (bool), lifetime_orders

### 3. `orders`
order_id, merchant_id, customer_id, created_at, channel (web/amazon/tiktok/
retail), currency, gross_sales, net_sales, total_discounts, current_subtotal,
subtotal_price, discount_pct, shipping_charged_to_customer,
actual_shipping_cost (❌ external, nullable), gateway_fee (⚠️ partial,
nullable), total_received, total_refunded, dispute_status, chargeback_amount,
completed_order_status, is_cancelled, source_name

### 4. `line_items`
line_item_id, order_id, product_id, variant_id, category, sku, quantity,
current_quantity (post-refund active qty), gross_price, discount_amount,
net_price, cogs (✅ verified but ~10% null to simulate unitCost gaps),
category_avg_cogs (fallback reference value), product_weight_kg,
length_cm/width_cm/height_cm (⚙️ metafield, nullable pre-cutover),
is_returned, refund_amount, restocking_cost, channel_fee_pct

### 5. `transactions`
transaction_id, order_id, gateway_name, status (SUCCESS/FAILED/PENDING),
fees_amount (⚠️ partial — null on manual orders), captured_at

### 6. `refunds`
refund_id, order_id, refund_line_item_ids, refund_amount, refund_date, reason

### 7. `shipping_fulfillments`
fulfillment_id, order_id, tracking_carrier, tracking_number,
actual_shipping_cost (❌ external — from 3PL invoice, ~8% missing/late),
delivery_status

### 8. `disputes`
dispute_id, order_id, status (NEEDS_RESPONSE/UNDER_REVIEW/WON/LOST),
amount, created_at

### 9. `subscriptions`
subscription_id, customer_id, merchant_id, plan_id, plan_type,
billing_interval, status, start_date, months_completed_before_churn,
is_voluntary_cancelled, cancellation_timestamp

### 10. `subscription_events`
event_id, subscription_id, billing_cycle_id, event_date, invoice_amount,
retry_number, payment_status, is_terminal_failure

### 11. `products_variants`
product_id, variant_id, merchant_id, category, sku, unit_cost,
weight_kg, is_sellable

### 12. `metafields` (current state — mirrors what Shopify API returns today)
entity_type (shop/product/customer/variant), entity_id, namespace, key,
value, value_type, updated_at

### 13. `metafield_history` (Zeitster's own append-only log — NOT from Shopify)
entity_id, field_name, value, recorded_at, source (webhook/backfill)
— only populate this AFTER each merchant's cutover_date, to correctly
simulate the history gap problem.

### 14. `support_tickets`
ticket_id, customer_id, order_id, ticket_date, support_cost, status

### 15. `category_cogs_benchmarks`
category, benchmark_cogs_amount (used as F01/F03 fallback reference)

### 16. `category_margin_targets` (metafield-backed config table)
merchant_id, category, target_margin_pct, is_configured (bool — some
merchants never set this, forcing global fallback)

---

## EDGE CASES TO GUARANTEE ARE PRESENT (tag with test_case_id)

For EVERY table above, include rows covering:
- Normal / clean case
- Boundary case (0%, 100%, exactly-zero-margin, exactly-at-threshold)
- Missing field WITH approved fallback available
- Missing field WITH NO fallback available (must resolve to "Unresolved")
- Pre-cutover order (no metafield history possible — expected gap, not error)
- Post-cutover order with full metafield history
- Partial refund (mixed active/refunded line items in one order)
- Full order cancellation
- Multi-line-item order (3+ items, different categories, for allocation
  testing)
- Cross-channel order (web vs marketplace, for channel-fee formulas)
- Late-arriving external data (3PL cost/gateway fee not yet available)
- Subscription churn (voluntary vs involuntary/failed payment)
- Disputed/charged-back order
- Orphan/broken reference (tag explicitly — e.g. line_item pointing to a
  deleted order) to test ingestion exception handling

---

## VOLUME

- ~500–1,000 orders per merchant (not millions — this is for thorough
  pipeline/edge-case testing, not load testing)
- Every edge case above must appear at least 5–10 times per merchant where
  applicable, not just once globally

## OUTPUT FORMAT

- One CSV per table, consistent snake_case column names as listed above
- Every row tagged with `test_case_id` describing what it's testing
  (e.g. "F04-DIMENSIONS-MISSING-PRECUTOVER", "SUB-CHURN-INVOLUNTARY-RETRY3")
- Provide a short data dictionary (one line per column) alongside the CSVs

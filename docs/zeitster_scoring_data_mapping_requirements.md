# Zeitster Scoring Data Mapping & Database Requirements
## Technical Specification for WebDev & Database Engineering Teams

> **Document Scope:** Data Ingestion, Relational Schema Requirements, and Source-to-Database Mapping for Active Scoring Formulas (F01–F05, F09–F12).  
> **Target Audience:** Backend Engineers, Database Architects, and Ingestion Pipeline Developers.  
> **Source of Truth:** Validated Formula Specifications (`src/scoring/`), Shopify GraphQL Admin API (2024-10+), and Relational Testing Schemas (`docs/`).  
> **Version:** 1.0 (Production Implementation Specification)

---

# 1. Technical Objective & End-to-End Pipeline

The Zeitster scoring engine quantifies operational margin leaks, promotional waste, shipping deficits, channel margin divergence, return drag, and net order/SKU profitability. To execute the validated formulas deterministically, the ingestion and data pipeline must ingest data from Shopify and external operational systems, persist it in a normalized relational schema, compute derived intermediate measures, and supply clean inputs to the scoring engine.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       1. SOURCE DATA LAYER                                           │
│                                                                                                      │
│  ┌───────────────────────┐  ┌──────────────────────┐  ┌─────────────────────┐  ┌──────────────────┐  │
│  │     Shopify Admin     │  │   Courier / 3PL API  │  │  Payment Gateways   │  │   Marketplaces   │  │
│  │      GraphQL API      │  │ (Shiprocket, EasyPost│  │  (Stripe, Razorpay, │  │ (Amazon SP-API,  │  │
│  │ (Orders, LineItems,   │  │  Delhivery, Bluedart)│  │   PayPal, Adyen)    │  │  TikTok, Walmart)│  │
│  │  Variants, Refunds)   │  │                      │  │                     │  │                  │  │
│  └───────────┬───────────┘  └──────────┬───────────┘  └──────────┬──────────┘  └────────┬─────────┘  │
│              │                         │                         │                      │            │
│  ┌───────────┴─────────────────────────┴─────────────────────────┴──────────────────────┴─────────┐  │
│  │  Returns App (Loop / Return Prime) & ERP / Inventory Cost (SOURCE TO BE CONFIRMED)             │  │
│  └──────────────────────────────────────────────────┬─────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┼────────────────────────────────────────────────┘
                                                      │ Webhooks / REST / GraphQL ETL Ingestion
                                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    2. ZEITSTER RAW / STAGING LAYER                                   │
│  - Raw payload persistence (JSONB / Staging tables)                                                  │
│  - Deduplication on source event IDs (`order_id`, `line_item_id`, `transaction_id`)                  │
│  - UTC timestamp normalization and multi-currency exchange rate capture                              │
└─────────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                      │ Idempotent Relational Transformation
                                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  3. NORMALIZED RELATIONAL DATA MODEL                                 │
│  ┌─────────────────────────┐     1:N     ┌───────────────────────────┐     N:1    ┌───────────────┐  │
│  │         orders          ├────────────►│     order_line_items      ├───────────►│  products /   │  │
│  └───────────┬─────────────┘             └─────────────┬─────────────┘            │   variants    │  │
│              │ 1:N                                     │ 1:1                      └───────────────┘  │
│              ├─────────────► payments_transactions     ├─────────────► return_items                  │
│              ├─────────────► shipments / packages      └─────────────► cogs_history                  │
│              └─────────────► refunds / refund_items                                                  │
└─────────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                      │ Materialized / SQL View / In-Memory
                                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  4. DERIVED MEASURES & ALLOCATION LAYER                              │
│  - Revenue-weighted outbound shipping allocation: `actual_shipping_cost * (net_price / order_total)` │
│  - Revenue-weighted gateway fee allocation: `gateway_fee * (net_price / order_total)`                │
│  - Volumetric weight calculation: `(L * W * H) / 5000` vs `product_weight_kg`                        │
│  - Active vs Returned item margin segregation                                                        │
└─────────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                      │ Clean Input Vectors
                                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       5. SCORING ENGINE (F01–F12)                                    │
│  - Order Level: F01 (Promo Margin), F03 (Margin Floor), F04 (Free Shipping), F05 (Shipping Recovery) │
│  - Product / SKU Level: F10 (Product Contribution), F11 (Product / Order Net Profit)                 │
│  - Store / Channel Level: F02 (Discount Dependency), F09 (Channel Divergence), F12 (Revenue Quality) │
└─────────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                      │ Scored Outputs
                                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   6. DASHBOARD & WRITE-BACK LAYER                                    │
│  - Merchant Analytics Dashboard UI                                                                   │
│  - Shopify GraphQL Metafield Mutation (`zeitster_scores.*`)                                          │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

# 2. Active Formula Scope

This specification strictly applies to the 9 active, validated scoring formulas. Formulas **F06**, **F07**, and **F08** are excluded from scope.

| Formula Code | Official Formula Name | Evaluation Level | Business Question Answered |
|---|---|---|---|
| **F01** | Promotion Margin Leakage | Order (Discounted) | Did promotional discounts erode gross margin below the category target margin floor? |
| **F02** | Discount Dependency Score | Store (Aggregated) | What proportion of store sales is addicted to promotional discounting beyond healthy limits (20%)? |
| **F03** | Margin Floor Breach | Order (All Active) | Which orders resulted in negative net contribution margin (cash losses)? |
| **F04** | Free-Shipping Leakage | Order (All Active) | Where did free/subsidized shipping exceed the profit margin generated by the merchandise? |
| **F05** | Shipping Cost Recovery | Order & Store | What percentage of actual carrier delivery expenses was recovered from customer shipping fees? |
| **F09** | Channel Margin Divergence | Sales Channel | How much unit profit is eroded on third-party marketplaces (Amazon, TikTok, Walmart) vs Direct Web? |
| **F10** | Product Contribution | SKU / Variant | What is the net contribution margin of each SKU after accounting for COGS, returns, shipping, and gateway fees? |
| **F11** | Order Profitability | Order (All Active) | What is the true bottom-line dollar profit and margin percentage per order after all direct costs? |
| **F12** | Revenue Quality Score | Store (Master Rollup) | What percentage of top-line gross merchandise revenue is retained after all operational leaks? |

---

# 3. Master Formula Input Requirements Matrix

The table below catalogs every raw data input required by the active formulas.

> **Crucial Financial Distinction Rules:**
> 1. **Gross Revenue / Selling Price:** Full pre-discount, pre-tax merchandise list price (`LineItem.originalTotalSet` / `selling_price`).
> 2. **Net Revenue / Selling Price:** Cash collected for merchandise after promotional discounts (`LineItem.discountedTotalSet` / `net_selling_price`).
> 3. **Subtotal / Order Total:** Shopify `totalPriceSet` includes taxes and shipping; scoring requires isolating pure merchandise revenue from shipping fees.
> 4. **Shipping Charged:** Fee billed to the customer for freight (`Order.shippingLines` / `shipping_charged_to_customer`).
> 5. **Actual Shipping Cost:** Courier/3PL carrier invoice expense (`actual_shipping_cost`). **Never available in Shopify.**
> 6. **COGS:** Inventory unit product cost multiplied by quantity (`cogs_total`).
> 7. **Refund Amount:** Cash refunded to customer on return (`RefundLineItem.subtotalSet` / `refund_amount`).
> 8. **Restocking Cost:** Reverse logistics inspection and handling expense. **Never available in Shopify.**
> 9. **Gateway Fee:** Credit card merchant processing fee (`Order.transactions.fees`). Native only for Shopify Payments.
> 10. **Channel Fee:** Marketplace referral fee percentage or dollar commission. **Never available in Shopify.**

| Formula | Required Input | Required Grain | Current Zeitster DB Field | Current DB Table | Shopify Source / Object | Shopify Field | Source Available? | Currently Persisted? | Derived? | Additional Source Required? | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **F01** | `order_id` | Order | `order_id` | `orders` | `Order` | `id` / `name` | Yes | Yes | No | No | Unique order reference |
| **F01** | `net_selling_price` | Line Item | Not Persisted | N/A | `LineItem` | `discountedTotalSet.shopMoney.amount` | Yes | No | No | No | Line item price after discounts |
| **F01** | `selling_price` | Line Item | Not Persisted | N/A | `LineItem` | `originalTotalSet.shopMoney.amount` | Yes | No | No | No | Undiscounted list price |
| **F01** | `discount_given` | Line Item / Order | Not Persisted | N/A | `LineItem` / `Order` | `totalDiscountsSet.shopMoney.amount` | Yes | No | Partially | No | `selling_price - net_selling_price` |
| **F01** | `cogs_total` | Line Item | Not Persisted | N/A | `InventoryItem` | `unitCost.amount * quantity` | Conditional (80%) | No | No | ERP / Accounting fallback | ~20% missing in Shopify catalogs |
| **F01** | `category` | Line Item / Product | Not Persisted | N/A | `Product` | `productType` or `tags` | Yes | No | No | No | Determines target margin % |
| **F01** | `actual_shipping_cost`| Order | Not Persisted | N/A | N/A | N/A | No | No | No | Courier / 3PL API | Billed carrier freight invoice |
| **F01** | `gateway_fee` | Order | Not Persisted | N/A | `OrderTransaction` | `fees.amount.amount` | Conditional (70%) | No | No | Gateway API (Stripe, etc.) | Available natively only for Shopify Payments |
| **F01** | `is_returned` | Line Item | Not Persisted | N/A | `RefundLineItem` | `lineItem.id` presence | Yes | No | No | No | Returned items excluded from active margin |
| **F02** | `selling_price` (GMV) | Line Item / Order | `gross_sales` (approx) | `orders` | `Order` / `LineItem` | `originalTotalSet.shopMoney.amount` | Yes | Partially | No | No | Pre-discount sales total |
| **F02** | `discount_given` | Line Item / Order | Not Persisted | N/A | `Order` / `LineItem` | `totalDiscountsSet.shopMoney.amount` | Yes | No | No | No | Cumulative promo discounts |
| **F02** | `is_discounted` | Order | Not Persisted | N/A | Derived | `discount_given > 0` | Yes | No | Yes | No | Flag indicating promo order |
| **F02** | `created_at` | Order | `created_at` | `orders` | `Order` | `createdAt` | Yes | Yes | No | No | Timestamp for rolling windows |
| **F02** | `is_cancelled` | Order | `is_cancelled` | `orders` | `Order` | `cancelledAt != null` | Yes | Yes | No | No | Exclude cancelled orders |
| **F03** | `order_id` | Order | `order_id` | `orders` | `Order` | `id` / `name` | Yes | Yes | No | No | Order identifier |
| **F03** | `net_selling_price` | Line Item | Not Persisted | N/A | `LineItem` | `discountedTotalSet.shopMoney.amount` | Yes | No | No | No | Post-discount line revenue |
| **F03** | `cogs_total` | Line Item | Not Persisted | N/A | `InventoryItem` | `unitCost.amount * quantity` | Conditional (80%) | No | No | ERP / Accounting fallback | Line-item inventory cost |
| **F03** | `actual_shipping_cost`| Order | Not Persisted | N/A | N/A | N/A | No | No | No | Courier / 3PL API | Billed carrier delivery cost |
| **F03** | `gateway_fee` | Order | Not Persisted | N/A | `OrderTransaction` | `fees.amount.amount` | Conditional (70%) | No | No | Gateway API | Merchant processing fee |
| **F03** | `is_returned` | Line Item | Not Persisted | N/A | `RefundLineItem` | `lineItem.id` presence | Yes | No | No | No | Segregates active vs returned items |
| **F04** | `order_id` | Order | `order_id` | `orders` | `Order` | `id` / `name` | Yes | Yes | No | No | Order identifier |
| **F04** | `net_selling_price` | Line Item | Not Persisted | N/A | `LineItem` | `discountedTotalSet.shopMoney.amount` | Yes | No | No | No | Line item price |
| **F04** | `cogs_total` | Line Item | Not Persisted | N/A | `InventoryItem` | `unitCost.amount * quantity` | Conditional (80%) | No | No | ERP fallback | Product cost for item profit |
| **F04** | `shipping_charged` | Order | `shipping_amount` | `orders` | `Order.shippingLines` | `originalPriceSet.shopMoney.amount`| Yes | Yes | No | No | Freight billed to customer |
| **F04** | `actual_shipping_cost`| Order | Not Persisted | N/A | N/A | N/A | No | No | No | Courier / 3PL API | True carrier freight cost |
| **F04** | `product_weight_kg` | Line Item / Variant | Not Persisted | N/A | `ProductVariant` | `weight` + `weightUnit` | Yes | No | No | No | Scale weight (converted to kg) |
| **F04** | `length_cm`, `width_cm`, `height_cm`| Variant | Not Persisted | N/A | `Metafield` | `namespace: "dimensions"` | Conditional (10%) | No | No | Metafield / PIM | Volumetric weight calculation |
| **F05** | `order_id` | Order | `order_id` | `orders` | `Order` | `id` / `name` | Yes | Yes | No | No | Order identifier |
| **F05** | `shipping_charged` | Order | `shipping_amount` | `orders` | `Order.shippingLines` | `originalPriceSet.shopMoney.amount`| Yes | Yes | No | No | Customer shipping charge |
| **F05** | `actual_shipping_cost`| Order | Not Persisted | N/A | N/A | N/A | No | No | No | Courier / 3PL API | Billed carrier freight fee |
| **F09** | `channel` | Order / Transaction| Not Persisted | N/A | `Order` | `sourceName` / custom tags | Conditional | No | No | Marketplace APIs | `web`, `amazon`, `tiktok`, `walmart` |
| **F09** | `net_selling_price` | Line Item | Not Persisted | N/A | `LineItem` | `discountedTotalSet.shopMoney.amount` | Yes | No | No | No | Line price collected |
| **F09** | `quantity` | Line Item | Not Persisted | N/A | `LineItem` | `quantity` | Yes | No | No | No | Number of units sold |
| **F09** | `cogs_total` | Line Item | Not Persisted | N/A | `InventoryItem` | `unitCost.amount * quantity` | Conditional (80%) | No | No | ERP fallback | Cost of goods sold |
| **F09** | `channel_fee_pct` / `fee`| Line Item / Order | Not Persisted | N/A | N/A | N/A | No | No | No | Marketplace Seller APIs | Amazon 15%, TikTok 8%, etc. |
| **F10** | `product_id` (SKU) | Line Item / Variant | Not Persisted | N/A | `ProductVariant` | `sku` / `id` | Yes | No | No | No | SKU level aggregation key |
| **F10** | `category` | Product | Not Persisted | N/A | `Product` | `productType` / `tags` | Yes | No | No | No | Product taxonomy |
| **F10** | `quantity` | Line Item | Not Persisted | N/A | `LineItem` | `quantity` | Yes | No | No | No | Units sold |
| **F10** | `net_selling_price` | Line Item | Not Persisted | N/A | `LineItem` | `discountedTotalSet.shopMoney.amount` | Yes | No | No | No | Collected net revenue |
| **F10** | `cogs_total` | Line Item | Not Persisted | N/A | `InventoryItem` | `unitCost.amount * quantity` | Conditional (80%) | No | No | ERP fallback | Cost of goods sold |
| **F10** | `is_returned` | Line Item | Not Persisted | N/A | `RefundLineItem` | `lineItem.id` presence | Yes | No | No | No | Item return flag |
| **F10** | `refund_amount` | Line Item | Not Persisted | N/A | `RefundLineItem` | `subtotalSet.shopMoney.amount` | Yes | No | No | No | Cash refunded for line item |
| **F10** | `restocking_cost` | Line Item | Not Persisted | N/A | N/A | N/A | No | No | No | Returns App (Loop) | Warehouse handling fee |
| **F10** | `return_shipping_cost`| Line Item | Not Persisted | N/A | N/A | N/A | No | No | No | 3PL / Carrier API | Reverse logistics freight cost |
| **F10** | `actual_shipping_cost`| Order | Not Persisted | N/A | N/A | N/A | No | No | No | Courier API | Allocated outbound shipping |
| **F10** | `gateway_fee` | Order | Not Persisted | N/A | `OrderTransaction` | `fees.amount.amount` | Conditional (70%) | No | No | Gateway API | Allocated merchant fee |
| **F11** | `order_id` | Order | `order_id` | `orders` | `Order` | `id` / `name` | Yes | Yes | No | No | Order identifier |
| **F11** | `net_selling_price` | Line Item | Not Persisted | N/A | `LineItem` | `discountedTotalSet.shopMoney.amount` | Yes | No | No | No | Merchandise collected |
| **F11** | `shipping_charged` | Order | `shipping_amount` | `orders` | `Order.shippingLines` | `originalPriceSet.shopMoney.amount`| Yes | Yes | No | No | Customer shipping charge |
| **F11** | `cogs_total` | Line Item | Not Persisted | N/A | `InventoryItem` | `unitCost.amount * quantity` | Conditional (80%) | No | No | ERP fallback | Inventory cost |
| **F11** | `actual_shipping_cost`| Order | Not Persisted | N/A | N/A | N/A | No | No | No | Courier API | Delivery freight cost |
| **F11** | `gateway_fee` | Order | Not Persisted | N/A | `OrderTransaction` | `fees.amount.amount` | Conditional (70%) | No | No | Gateway API | Payment processing fee |
| **F11** | `refund_amount` | Line Item / Order | `refund_amount` (order) | `orders` / `refunds` | `Refund` | `totalRefundedSet.shopMoney.amount`| Yes | Partially | No | No | Cash refunded |
| **F11** | `restocking_cost` | Line Item | Not Persisted | N/A | N/A | N/A | No | No | No | Returns App | Return handling expense |
| **F12** | `selling_price` (GMV) | Line Item / Order | `gross_sales` (approx) | `orders` | `Order` / `LineItem` | `originalTotalSet.shopMoney.amount` | Yes | Partially | No | No | Pre-discount gross sales |
| **F12** | `discount_given` | Line Item / Order | Not Persisted | N/A | `Order` / `LineItem` | `totalDiscountsSet.shopMoney.amount` | Yes | No | No | No | Promo discounts given |
| **F12** | `refund_amount` + restock| Line Item / Order | `refund_amount` (partial)| `orders` / `refunds` | `Refund` | `totalRefundedSet` + Returns App | Yes (refund) | Partially | No | Returns App (restock) | Total reverse logistics loss |
| **F12** | `actual_shipping_cost`| Order | Not Persisted | N/A | N/A | N/A | No | No | No | Courier API | Carrier delivery cost |
| **F12** | `shipping_charged` | Order | `shipping_amount` | `orders` | `Order.shippingLines` | `originalPriceSet.shopMoney.amount`| Yes | Yes | No | No | Customer shipping paid |
| **F12** | `gateway_fee` | Order | Not Persisted | N/A | `OrderTransaction` | `fees.amount.amount` | Conditional (70%) | No | No | Gateway API | Merchant fee |
| **F12** | `chargeback_amount` | Order | Not Persisted | N/A | `Dispute` | `amount.amount` | Conditional (Shopify) | No | No | Gateway Dispute API | Chargeback loss + penalty |

---

# 4. Formula-by-Formula Mapping & Data Flow

## 4.1 F01 — Promotion Margin Leakage

### Mathematical Definition
$$\text{Line Gross Profit} = \text{Net Selling Price} - \text{COGS}$$
$$\text{Order Profit} = \sum_{\text{active line items}} (\text{Line Gross Profit}) - \text{Actual Courier Shipping Cost} - \text{Gateway Fee}$$
$$\text{Order Target Minimum Profit} = \sum_{\text{active line items}} \left(\text{Net Selling Price} \times \text{Category Target Margin \%}\right)$$
$$\text{F01 Loss} = \begin{cases} \max(0, \text{Order Target Minimum Profit} - \text{Order Profit}), & \text{if Order is Discounted and Order Profit} < \text{Target Profit} \\ 0.0, & \text{otherwise} \end{cases}$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `order_id` | `Order.id` / `Order.name` | `orders.order_id` | Yes | Yes | Raw Key | No |
| `line_item_id` | `LineItem.id` | Not Persisted | Yes | No | Raw Key | No |
| `net_selling_price` | `LineItem.discountedTotalSet` | Not Persisted | Yes | No | Raw Metric | No |
| `discount_given` | `LineItem.originalTotalSet - discountedTotalSet` | Not Persisted | Yes | No | Derived Metric | No |
| `is_discounted` | `discount_given > 0` | Not Persisted | Yes | No | Derived Flag | No |
| `cogs_total` | `InventoryItem.unitCost * quantity` | Not Persisted | Conditional (80%) | No | Raw Metric | ERP / Accounting fallback |
| `category` | `Product.productType` / `tags` | Not Persisted | Yes | No | Raw Attribute | No |
| `actual_shipping_cost`| N/A | Not Persisted | No | No | Raw Metric | Courier / 3PL API |
| `gateway_fee` | `OrderTransaction.fees.amount` | Not Persisted | Conditional (70%) | No | Raw Metric | Gateway API |
| `is_returned` | `RefundLineItem.lineItem.id` match | Not Persisted | Yes | No | Derived Flag | No |
| `target_min_profit` | Derived (`net_selling_price * target_margin_pct`) | N/A | N/A | N/A | Derived Measure | Target margin table |
| `order_profit` | Derived (`sum(line_profit) - shipping - gw_fee`)| N/A | N/A | N/A | Derived Measure | No |
| `f01_loss` | Derived (`max(0, target_profit - order_profit)`)| N/A | N/A | N/A | Scoring Engine Output| No |

---

## 4.2 F02 — Discount Dependency Score

### Mathematical Definition
$$\text{Discounted Sales Share} = \frac{\sum_{\text{discounted orders}} \text{Gross Selling Price}}{\sum_{\text{all active orders}} \text{Gross Selling Price}}$$
$$\text{Excess Discount Share} = \max(0.0, \text{Discounted Sales Share} - \text{Healthy Benchmark (0.20)})$$
$$\text{Average Discount Depth} = \frac{\sum_{\text{all items}} \text{Discount Given}}{\sum_{\text{discounted orders}} \text{Gross Selling Price}}$$
$$\text{F02 Loss} = \text{Total Store Gross Sales} \times \text{Excess Discount Share} \times \text{Average Discount Depth}$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `order_id` | `Order.id` | `orders.order_id` | Yes | Yes | Raw Key | No |
| `created_at` | `Order.createdAt` | `orders.created_at` | Yes | Yes | Raw Timestamp | No |
| `is_cancelled` | `Order.cancelledAt != null` | `orders.is_cancelled` | Yes | Yes | Raw Flag | No |
| `selling_price` (GMV) | `LineItem.originalTotalSet` | `orders.gross_sales` (approx) | Yes | Partially | Raw Metric | No |
| `discount_given` | `LineItem.originalTotalSet - discountedTotalSet` | Not Persisted | Yes | No | Derived Metric | No |
| `discounted_sales_share`| Aggregated ratio | N/A | N/A | N/A | Derived Measure | No |
| `avg_discount_depth` | Aggregated ratio | N/A | N/A | N/A | Derived Measure | No |
| `f02_loss` | Aggregated dollar loss | N/A | N/A | N/A | Scoring Engine Output| Benchmark configs |

---

## 4.3 F03 — Margin Floor Breach Score

### Mathematical Definition
$$\text{Order Contribution Margin} = \sum_{\text{active line items}} (\text{Net Selling Price} - \text{COGS}) - \text{Actual Courier Shipping Cost} - \text{Gateway Fee}$$
$$\text{F03 Breach} = \text{Order Contribution Margin} < 0.0$$
$$\text{F03 Loss} = \begin{cases} -\text{Order Contribution Margin}, & \text{if F03 Breach is True} \\ 0.0, & \text{otherwise} \end{cases}$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `order_id` | `Order.id` | `orders.order_id` | Yes | Yes | Raw Key | No |
| `net_selling_price` | `LineItem.discountedTotalSet` | Not Persisted | Yes | No | Raw Metric | No |
| `cogs_total` | `InventoryItem.unitCost * quantity` | Not Persisted | Conditional (80%) | No | Raw Metric | ERP / Accounting fallback |
| `actual_shipping_cost`| N/A | Not Persisted | No | No | Raw Metric | Courier / 3PL API |
| `gateway_fee` | `OrderTransaction.fees.amount` | Not Persisted | Conditional (70%) | No | Raw Metric | Gateway API |
| `is_returned` | `RefundLineItem.lineItem.id` match | Not Persisted | Yes | No | Derived Flag | No |
| `net_contribution_margin`| Derived (`sum(net_price - cogs) - ship - gw`)| N/A | N/A | N/A | Derived Measure | No |
| `f03_loss` | Derived (`max(0, -net_contribution_margin)`) | N/A | N/A | N/A | Scoring Engine Output| No |

---

## 4.4 F04 — Free-Shipping Leakage Score

### Mathematical Definition (Formula B — Cash Loss)
$$\text{Volumetric Weight (kg)} = \frac{\text{Length (cm)} \times \text{Width (cm)} \times \text{Height (cm)}}{5000}$$
$$\text{Chargeable Weight (kg)} = \max(\text{Scale Weight (kg)}, \text{Volumetric Weight (kg)})$$
$$\text{Uncovered Shipping Cost} = \max(0.0, \text{Actual Courier Cost} - \text{Shipping Charged to Customer})$$
$$\text{Product Gross Profit} = \sum_{\text{active line items}} (\text{Net Selling Price} - \text{COGS})$$
$$\text{F04 Leakage} = \max(0.0, \text{Uncovered Shipping Cost} - \text{Product Gross Profit})$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `order_id` | `Order.id` | `orders.order_id` | Yes | Yes | Raw Key | No |
| `shipping_charged_to_customer`| `Order.shippingLines.originalPriceSet` | `orders.shipping_amount` | Yes | Yes | Raw Metric | No |
| `actual_shipping_cost`| N/A | Not Persisted | No | No | Raw Metric | Courier / 3PL API |
| `product_weight_kg` | `ProductVariant.weight` + `weightUnit` | Not Persisted | Yes | No | Raw Metric (converted)| No |
| `length_cm`, `width_cm`, `height_cm`| `ProductVariant.metafields` (namespace: `dimensions`)| Not Persisted | Conditional (10%) | No | Raw Dimensions | Metafield / PIM |
| `net_selling_price` | `LineItem.discountedTotalSet` | Not Persisted | Yes | No | Raw Metric | No |
| `cogs_total` | `InventoryItem.unitCost * quantity` | Not Persisted | Conditional (80%) | No | Raw Metric | ERP fallback |
| `uncovered_shipping` | Derived (`max(0, actual - charged)`) | N/A | N/A | N/A | Derived Measure | No |
| `f04_leakage` | Derived (`max(0, uncovered_ship - product_profit)`)| N/A | N/A | N/A | Scoring Engine Output| No |

---

## 4.5 F05 — Shipping Cost Recovery Score

### Mathematical Definition
$$\text{Per-Order Shipping Delta} = \text{Shipping Fee Charged to Customer} - \text{Actual Courier Cost}$$
$$\text{Normalized Recovery Score} = \begin{cases} \left(\frac{\text{Shipping Fee Charged to Customer}}{\text{Actual Courier Cost}}\right) \times 100.0, & \text{if Actual Courier Cost} > 0 \\ 100.0, & \text{if Actual Courier Cost} = 0 \text{ (Technical Fallback)} \end{cases}$$
$$\text{Storewide Net Shipping Position} = \sum_{\text{all orders}} (\text{Shipping Fee Charged} - \text{Actual Courier Cost})$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `order_id` | `Order.id` | `orders.order_id` | Yes | Yes | Raw Key | No |
| `shipping_charged_to_customer`| `Order.shippingLines.originalPriceSet` | `orders.shipping_amount` | Yes | Yes | Raw Metric | No |
| `actual_shipping_cost`| N/A | Not Persisted | No | No | Raw Metric | Courier / 3PL API |
| `shipping_delta` | Derived (`charged - actual`) | N/A | N/A | N/A | Derived Measure | No |
| `shipping_recovery_score_pct`| Derived (`(charged / actual) * 100`) | N/A | N/A | N/A | Scoring Engine Output| No |

---

## 4.6 F09 — Channel Margin Divergence Score

### Mathematical Definition
$$\text{Item Margin} = \text{Net Selling Price} - \text{COGS} - (\text{Net Selling Price} \times \text{Channel Fee \%})$$
$$\text{Primary (Direct Web) Unit Profit} = \frac{\sum_{\text{web items}} \text{Item Margin}}{\sum_{\text{web items}} \text{Quantity Sold}}$$
$$\text{Channel } c \text{ Unit Profit} = \frac{\sum_{\text{channel } c \text{ items}} \text{Item Margin}}{\sum_{\text{channel } c \text{ items}} \text{Quantity Sold}}$$
$$\text{Channel Divergence Loss} = \max\left(0.0, \text{Direct Web Unit Profit} - \text{Channel } c \text{ Unit Profit}\right) \times \text{Units Sold on Channel } c$$
$$\text{Normalized Channel Score} = \begin{cases} \left(\frac{\text{Channel } c \text{ Unit Profit}}{\text{Direct Web Unit Profit}}\right) \times 100.0, & \text{if Direct Web Unit Profit} \ne 0 \\ 100.0, & \text{if Both Unit Profits} = 0 \\ 0.0, & \text{if Direct Web Unit Profit} = 0 \text{ and Channel Profit} > 0 \end{cases}$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `order_id` | `Order.id` | `orders.order_id` | Yes | Yes | Raw Key | No |
| `channel` | `Order.sourceName` / tags | Not Persisted | Conditional | No | Raw Attribute | Marketplace APIs |
| `quantity` | `LineItem.quantity` | Not Persisted | Yes | No | Raw Metric | No |
| `net_selling_price` | `LineItem.discountedTotalSet` | Not Persisted | Yes | No | Raw Metric | No |
| `cogs_total` | `InventoryItem.unitCost * quantity` | Not Persisted | Conditional (80%) | No | Raw Metric | ERP fallback |
| `channel_fee_pct` | N/A | Not Persisted | No | No | Raw / Config Metric | Marketplace Seller APIs |
| `unit_profit` | Derived (`sum(item_margin) / sum(qty)`) | N/A | N/A | N/A | Derived Measure | No |
| `channel_divergence_loss`| Derived (`max(0, web_profit - mkt_profit) * units`)| N/A | N/A | N/A | Scoring Engine Output| No |

---

## 4.7 F10 — Product Contribution Score

### Mathematical Definition
$$\text{Revenue Share Ratio} = \frac{\text{Line Item Net Revenue}}{\sum_{\text{all order items}} \text{Line Item Net Revenue}}$$
$$\text{Allocated Outbound Shipping} = \text{Order Actual Shipping Cost} \times \text{Revenue Share Ratio}$$
$$\text{Allocated Gateway Fee} = \text{Order Gateway Fee} \times \text{Revenue Share Ratio}$$
$$\text{Reverse Logistics Loss} = \text{Refund Amount} + \text{Restocking Cost} + (\text{Return Freight Fee} \times \text{Returned Qty})$$
$$\text{SKU Product Contribution} = \sum_{\text{SKU sales}} \left(\text{Net Sales} - \text{COGS} - \text{Reverse Logistics Loss} - \text{Allocated Shipping} - \text{Allocated Gateway}\right)$$
$$\text{Normalized Contribution Score} = \max\left(0.0, \left(\frac{\text{SKU Product Contribution}}{\text{SKU Total Net Sales}}\right) \times 100.0\right)$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `product_id` (SKU) | `ProductVariant.sku` / `id` | Not Persisted | Yes | No | Raw Key | No |
| `category` | `Product.productType` / `tags` | Not Persisted | Yes | No | Raw Attribute | No |
| `quantity` | `LineItem.quantity` | Not Persisted | Yes | No | Raw Metric | No |
| `net_selling_price` | `LineItem.discountedTotalSet` | Not Persisted | Yes | No | Raw Metric | No |
| `cogs_total` | `InventoryItem.unitCost * quantity` | Not Persisted | Conditional (80%) | No | Raw Metric | ERP fallback |
| `is_returned` | `RefundLineItem.lineItem.id` match | Not Persisted | Yes | No | Derived Flag | No |
| `refund_amount` | `RefundLineItem.subtotalSet` | Not Persisted | Yes | No | Raw Metric | No |
| `restocking_cost` | N/A | Not Persisted | No | No | Raw Metric | Returns App (Loop) |
| `return_shipping_cost`| N/A | Not Persisted | No | No | Raw Metric | Carrier API |
| `actual_shipping_cost`| N/A | Not Persisted | No | No | Raw Metric | Courier API |
| `gateway_fee` | `OrderTransaction.fees.amount` | Not Persisted | Conditional (70%) | No | Raw Metric | Gateway API |
| `allocated_shipping` | Derived (`actual_shipping * revenue_ratio`) | N/A | N/A | N/A | Derived Measure | No |
| `allocated_gateway` | Derived (`gateway_fee * revenue_ratio`) | N/A | N/A | N/A | Derived Measure | No |
| `product_contribution`| Derived SKU aggregation | N/A | N/A | N/A | Scoring Engine Output| No |

---

## 4.8 F11 — Order Profitability Score

### Mathematical Definition
$$\text{Total Money Collected} = \sum_{\text{order line items}} (\text{Net Selling Price}) + \text{Shipping Charged to Customer}$$
$$\text{Realized Return Expense} = \sum_{\text{returned line items}} (\text{Refund Amount} + \text{Restocking Cost})$$
$$\text{Order Net Profit} = \text{Total Collected} - \text{Order COGS} - \text{Actual Shipping Cost} - \text{Gateway Fee} - \text{Realized Return Expense}$$
$$\text{Order Net Margin \%} = \left(\frac{\text{Order Net Profit}}{\text{Total Money Collected}}\right) \times 100.0$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `order_id` | `Order.id` | `orders.order_id` | Yes | Yes | Raw Key | No |
| `net_selling_price` | `LineItem.discountedTotalSet` | Not Persisted | Yes | No | Raw Metric | No |
| `shipping_charged_to_customer`| `Order.shippingLines.originalPriceSet` | `orders.shipping_amount` | Yes | Yes | Raw Metric | No |
| `cogs_total` | `InventoryItem.unitCost * quantity` | Not Persisted | Conditional (80%) | No | Raw Metric | ERP fallback |
| `actual_shipping_cost`| N/A | Not Persisted | No | No | Raw Metric | Courier / 3PL API |
| `gateway_fee` | `OrderTransaction.fees.amount` | Not Persisted | Conditional (70%) | No | Raw Metric | Gateway API |
| `refund_amount` | `RefundLineItem.subtotalSet` | `orders.refund_amount` (approx)| Yes | Partially | Raw Metric | No |
| `restocking_cost` | N/A | Not Persisted | No | No | Raw Metric | Returns App |
| `total_money_collected`| Derived (`net_sales + shipping_charged`) | N/A | N/A | N/A | Derived Measure | No |
| `order_net_profit` | Derived | N/A | N/A | N/A | Scoring Engine Output| No |

---

## 4.9 F12 — Revenue Quality Score

### Mathematical Definition
$$\text{Gross Merchandise Sales} = \sum_{\text{all active items}} \text{Selling Price (Original)}$$
$$\text{Total Leaks} = \text{Discounts Given} + \text{Return Losses} + \text{Shipping Deficits} + \text{Gateway Fees} + \text{Chargebacks}$$
$$\text{Net Retained Revenue} = \text{Gross Merchandise Sales} - \text{Total Leaks}$$
$$\text{Revenue Quality Score \%} = \left(\frac{\text{Net Retained Revenue}}{\text{Gross Merchandise Sales}}\right) \times 100.0$$
$$\text{Leakage Ratio \%} = \left(\frac{\text{Total Leaks}}{\text{Gross Merchandise Sales}}\right) \times 100.0$$

### Field Mapping

| Field | Shopify Source | Current DB Table / Column | Shopify Provides? | Persisted in DB? | Calculation Type | External Source Needed? |
|---|---|---|---|---|---|---|
| `selling_price` (GMV) | `LineItem.originalTotalSet` | `orders.gross_sales` (approx) | Yes | Partially | Raw Metric | No |
| `discount_given` | `LineItem.originalTotalSet - discountedTotalSet` | Not Persisted | Yes | No | Derived Metric | No |
| `refund_amount` | `Refund.totalRefundedSet` | `orders.refund_amount` | Yes | Yes | Raw Metric | No |
| `restocking_cost` | N/A | Not Persisted | No | No | Raw Metric | Returns App |
| `actual_shipping_cost`| N/A | Not Persisted | No | No | Raw Metric | Courier / 3PL API |
| `shipping_charged_to_customer`| `Order.shippingLines.originalPriceSet` | `orders.shipping_amount` | Yes | Yes | Raw Metric | No |
| `gateway_fee` | `OrderTransaction.fees.amount` | Not Persisted | Conditional (70%) | No | Raw Metric | Gateway API |
| `chargeback_amount` | `Dispute.amount` | Not Persisted | Conditional (Shopify) | No | Raw Metric | Gateway Dispute API |
| `total_leakage` | Additive sum of leak buckets | N/A | N/A | N/A | Derived Measure | No |
| `revenue_quality_score_pct`| Derived (`(net_retained / gross_sales) * 100`) | N/A | N/A | N/A | Scoring Engine Output| No |

---

# 5. Current Shopify Ingestion & Schema Availability

### 5.1 Available in Current Zeitster Database

The existing production database persists order-grain metadata but lacks line-item, variant, and carrier-cost depth:

| Entity / Field Name | Current DB Table | Current DB Column | Data Type | Shopify Source Mapping | Notes |
|---|---|---|---|---|---|
| Order ID | `orders` | `order_id` | `VARCHAR(64)` | `Order.id` / `Order.name` | Primary Key |
| Created At | `orders` | `created_at` | `TIMESTAMP` | `Order.createdAt` | Order creation timestamp |
| Currency | `orders` | `currency` | `VARCHAR(3)` | `Order.currencyCode` | ISO Currency Code |
| Gross Sales | `orders` | `gross_sales` | `DECIMAL(10,2)`| `Order.totalPriceSet` | Gross order total (order level) |
| Shipping Charged | `orders` | `shipping_charged_to_customer`| `DECIMAL(10,2)`| `Order.shippingLines` | Freight billed to customer |
| Cancelled Status | `orders` | `is_cancelled` | `BOOLEAN` | `Order.cancelledAt != null` | Void/cancellation flag |
| Financial Status | `orders` | `financial_status` | `VARCHAR(32)` | `Order.displayFinancialStatus` | Payment status |
| Fulfillment Status | `orders` | `fulfillment_status` | `VARCHAR(32)` | `Order.displayFulfillmentStatus`| Shipment status |
| Refund Amount | `orders` / `refunds` | `refund_amount` | `DECIMAL(10,2)`| `Order.refunds.totalRefundedSet`| Order-level refund sum |

### 5.2 Shopify Data Available via API but NOT Currently Persisted

The following GraphQL resources exist natively in Shopify Admin API (2024-10+) but are not persisted in the database:

| Field / Object | Shopify GraphQL Path | Why Needed by Formulas | Ingestion Action Required |
|---|---|---|---|
| Order Line Items | `Order.lineItems.nodes` | Required by F01, F03, F04, F09, F10, F11 | Ingest into new `order_line_items` table |
| Line Item ID | `LineItem.id` | Primary key for line items | Persist as `line_item_id` |
| SKU / Variant ID | `ProductVariant.sku`, `ProductVariant.id` | SKU-level rollup (F10) and COGS joins | Persist in `order_line_items` and `product_variants` |
| Line Original Price | `LineItem.originalTotalSet.shopMoney.amount` | Pre-discount list price (F01, F02, F12) | Persist as `selling_price` |
| Line Discounted Price | `LineItem.discountedTotalSet.shopMoney.amount`| Post-discount collected price (F01, F03, F10, F11)| Persist as `net_selling_price` |
| Line Quantity | `LineItem.quantity` | Unit volume weighting (F09, F10) | Persist as `quantity` |
| Inventory Unit Cost | `ProductVariant.inventoryItem.unitCost.amount`| COGS calculations (F01, F03, F04, F10, F11) | Persist as `cogs_unit_cost` (with ERP sync) |
| Product Taxonomy | `Product.productType` / `Product.tags` | Target margin lookup (F01) & category analysis | Persist as `category` |
| Dead Weight & Unit | `ProductVariant.weight` + `ProductVariant.weightUnit`| Chargeable freight weight (F04) | Normalize to kg and persist as `product_weight_kg` |
| Dimensional Metafields| `ProductVariant.metafields(namespace: "dimensions")`| Volumetric weight calculation (F04) | Parse `length`, `width`, `height` (cm) |
| Refund Line Items | `Refund.refundLineItems.nodes` | Partial return revenue/COGS deduction (F01, F10)| Ingest into new `refund_line_items` table |
| Gateway Fees | `Order.transactions.fees.amount` | Gateway processing cost (Shopify Payments stores)| Ingest into new `payments_transactions` table |
| Chargeback Disputes | `Dispute.amount.amount` | Master leakage rollup (F12) | Ingest into new `disputes` / `payments` table |

### 5.3 Data NOT Available from Shopify (Structural External Gaps)

The following operational data points are **never provided by Shopify** and require external integration pipelines:

| Required Data Point | Needed By | Source System Required | Why Shopify Cannot Provide It |
|---|---|---|---|
| **Actual Courier Shipping Cost** | F04, F05, F10, F11, F12 | Courier / 3PL API (Shiprocket, EasyPost, Delhivery, Bluedart, ShipStation) | Shopify only knows what was charged to the customer, never the carrier delivery invoice. |
| **External Gateway Fees** | F01, F03, F10, F11, F12 | Payment Gateways (Stripe, Razorpay, PayPal, Adyen, Authorize.net) | Shopify API only returns fee objects for Shopify Payments transactions (~70% of stores). |
| **Marketplace Channel Fees** | F09 | Marketplace Seller APIs (Amazon SP-API, TikTok Shop, Walmart Seller) | Marketplace commission structures (8%–15%) exist entirely outside Shopify. |
| **Warehouse Restocking Cost** | F10, F11, F12 | Returns App (Loop Returns, Return Prime) / 3PL WMS | Physical inspection, cleaning, and restocking labor fees are not Shopify concepts. |
| **Return Freight Expense** | F10 | Courier Reverse Logistics Rate Card | Reverse shipping fees billed by the carrier for returned packages. |
| **Complete Product Dimensions** | F04 | PIM / WMS / Merchant Metafields | Shopify has no native box dimension fields (~90% of catalogs lack custom metafields). |
| **Catalog-Wide COGS Backup** | F01, F03, F10, F11 | ERP / Accounting Software (NetSuite, QuickBooks, Zoho) | ~20% of Shopify merchants leave `unitCost` null in Shopify Admin. |

---

# 6. Zeitster Database Model Required for Scoring

To support the 9 active scoring formulas without operational bottlenecks, the Zeitster database must implement the following normalized relational schema:

```
┌────────────────────────┐       ┌────────────────────────┐       ┌────────────────────────┐
│        stores          │       │  scoring_configs       │       │    product_variants    │
├────────────────────────┤       ├────────────────────────┤       ├────────────────────────┤
│ PK store_id            │       │ PK config_id           │       │ PK variant_id          │
│    shop_domain         │       │ FK store_id            │       │ FK product_id          │
│    currency_code       │       │    target_margin_json  │       │    sku                 │
│    timezone            │       │    healthy_disc_share  │       │    weight_kg           │
└───────────┬────────────┘       └────────────────────────┘       │    length_cm           │
            │ 1:N                                                 │    width_cm            │
            ▼                                                     │    height_cm           │
┌────────────────────────┐                                        │    cogs_unit_cost      │
│        orders          │                                        └───────────┬────────────┘
├────────────────────────┤                                                    │ 1:N
│ PK order_id            │       ┌────────────────────────┐                   │
│ FK store_id            │       │    order_line_items    │                   │
│    channel             ├──────►├────────────────────────┼───────────────────┘
│    created_at          │ 1:N   │ PK line_item_id        │
│    is_cancelled        │       │ FK order_id            │
│    shipping_charged    │       │ FK variant_id          │
│    actual_shipping_cost│       │    category            │
│    gateway_fee         │       │    quantity            │
│    chargeback_amount   │       │    selling_price       │
└───────────┬────────────┘       │    discount_given      │
            │                    │    net_selling_price   │
            ├─────────────────┐  │    cogs_total          │
            │ 1:N             │  │    is_returned         │
            ▼                 │  └───────────┬────────────┘
┌────────────────────────┐    │              │ 1:1
│ payments_transactions  │    │              ▼
├────────────────────────┤    │  ┌────────────────────────┐
│ PK transaction_id      │    │  │   return_line_items    │
│ FK order_id            │    │  ├────────────────────────┤
│    gateway_name        │    │  │ PK return_item_id      │
│    fee_amount          │    │  │ FK line_item_id        │
└────────────────────────┘    │  │ FK refund_id           │
                              │  │    refund_amount       │
                              │  │    restocking_cost     │
                              │  │    return_shipping_cost│
                              │  └────────────────────────┘
                              │ 1:N
                              ▼
                         ┌────────────────────────┐
                         │        refunds         │
                         ├────────────────────────┤
                         │ PK refund_id           │
                         │ FK order_id            │
                         │    total_refunded      │
                         │    created_at          │
                         └────────────────────────┘
```

### Table Definitions & Specifications

| Table Name | Grain | Why Required | Primary Key | Foreign Keys | Primary Source System |
|---|---|---|---|---|---|
| `stores` | Store / Merchant | Multi-tenant merchant isolation, currency & timezone config | `store_id` | None | Shopify `Shop` object |
| `scoring_configs` | Store | Target margins by category, discount benchmarks, fallback rates | `config_id` | `store_id` references `stores(store_id)` | Zeitster App Config / Merchant Settings |
| `orders` | Order | Master order header for F01, F02, F03, F04, F05, F11, F12 | `order_id` | `store_id` references `stores(store_id)` | Shopify Admin API + Courier API |
| `order_line_items` | Line Item | Core grain for product gross profit, COGS, discounts (F01, F03, F04, F09, F10) | `line_item_id` | `order_id` references `orders(order_id)`, `variant_id` references `product_variants(variant_id)` | Shopify Admin API + ERP COGS |
| `products` | Parent Product | Taxonomy, category, tags for target margin lookup (F01, F10) | `product_id` | `store_id` references `stores(store_id)` | Shopify `Product` object |
| `product_variants` | SKU / Variant | SKU reference, scale weight, box dimensions, default unit COGS | `variant_id` | `product_id` references `products(product_id)` | Shopify `ProductVariant` + Metafields |
| `payments_transactions`| Payment Txn | Multi-gateway fee capture for non-Shopify Payments stores | `transaction_id` | `order_id` references `orders(order_id)` | Shopify Payments / Stripe / Razorpay API |
| `refunds` | Refund Event | Tracks refund events and timestamps | `refund_id` | `order_id` references `orders(order_id)` | Shopify `Refund` object |
| `return_line_items` | Returned Line Item | Item-level refund cash, restocking fee, and return shipping fee (F10, F11, F12) | `return_item_id` | `line_item_id` references `order_line_items(line_item_id)`, `refund_id` references `refunds(refund_id)` | Shopify RefundLineItem + Returns App |
| `shipments` | Fulfillment / Package | Actual carrier shipping cost, tracking number, package weights (F04, F05) | `shipment_id` | `order_id` references `orders(order_id)` | Courier / 3PL API (Shiprocket, EasyPost) |
| `channel_fees` | Channel Txn / Rate | Marketplace commission percentages and fixed fees (F09) | `channel_fee_id` | `order_id` references `orders(order_id)` | Marketplace Seller APIs |
| `cogs_history` | SKU / Variant Snapshot | Point-in-time unit cost tracking to prevent historical score mutation | `cogs_snapshot_id`| `variant_id` references `product_variants(variant_id)` | ERP / Inventory System |

---

# 7. Cross-Table Relational Join Keys

| Relationship Path | Source Table | Source Join Key | Target Table | Target Join Key | Relationship Type | Key Confirmation Status |
|---|---|---|---|---|---|---|
| Store → Orders | `stores` | `store_id` | `orders` | `store_id` | 1 : N | CONFIRMED (`Shop.id`) |
| Store → Scoring Configs | `stores` | `store_id` | `scoring_configs` | `store_id` | 1 : 1 | CONFIRMED |
| Order → Order Line Items | `orders` | `order_id` | `order_line_items` | `order_id` | 1 : N | CONFIRMED (`Order.id` / `Order.name`) |
| Product → Variants | `products` | `product_id` | `product_variants` | `product_id` | 1 : N | CONFIRMED (`Product.id`) |
| Order Line Item → Variant | `order_line_items` | `variant_id` | `product_variants` | `variant_id` | N : 1 | CONFIRMED (`ProductVariant.id`) |
| Order → Payments / Txns | `orders` | `order_id` | `payments_transactions` | `order_id` | 1 : N | CONFIRMED (`Order.id`) |
| Order → Refunds | `orders` | `order_id` | `refunds` | `order_id` | 1 : N | CONFIRMED (`Order.id`) |
| Refund → Return Line Items | `refunds` | `refund_id` | `return_line_items` | `refund_id` | 1 : N | CONFIRMED (`Refund.id`) |
| Line Item → Return Item | `order_line_items`| `line_item_id` | `return_line_items` | `line_item_id` | 1 : 1 | CONFIRMED (`RefundLineItem.lineItemId`)|
| Order → Shipments | `orders` | `order_id` | `shipments` | `order_id` | 1 : N | CONFIRMED (`Order.name` / Tracking #) |
| Order → Channel Fees | `orders` | `order_id` | `channel_fees` | `order_id` | 1 : 1 | JOIN KEY NOT CONFIRMED (Requires Marketplace Order ID mapping)|
| Variant → COGS History | `product_variants`| `variant_id` | `cogs_history` | `variant_id` | 1 : N | CONFIRMED (`ProductVariant.id`) |

---

# 8. Source-to-Database Mapping Matrix

| Business Calculation Input | Formula | Source System | Source Object | Source Field | Zeitster Table | Zeitster Column | Grain | Transformation / Parsing Rule | Join Key | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| Order Reference ID | All | Shopify | `Order` | `id` or `name` | `orders` | `order_id` | Order | Strip GraphQL GID prefix (`gid://shopify/Order/`) | `order_id` | AVAILABLE |
| Order Timestamp | F02, F09, F12 | Shopify | `Order` | `createdAt` | `orders` | `created_at` | Order | Parse ISO8601 to UTC Timestamp | `order_id` | AVAILABLE |
| Sales Channel | F09 | Shopify / Marketplace | `Order` / App | `sourceName` / custom tag | `orders` | `channel` | Order | Normalize to enum (`web`, `amazon`, `tiktok`, `walmart`) | `order_id` | REQUIRES SOURCE FIELD CONFIRMATION |
| Gross Merchandise Value | F02, F12 | Shopify | `LineItem` | `originalTotalSet.shopMoney.amount` | `order_line_items` | `selling_price` | Line Item | Cast to Decimal(10,2) | `line_item_id` | AVAILABLE BUT NOT PERSISTED |
| Net Merchandise Sales | F01, F03, F04, F10, F11 | Shopify | `LineItem` | `discountedTotalSet.shopMoney.amount` | `order_line_items` | `net_selling_price` | Line Item | Cast to Decimal(10,2) | `line_item_id` | AVAILABLE BUT NOT PERSISTED |
| Item Discount Amount | F01, F02, F12 | Shopify | `LineItem` | Calculated | `order_line_items` | `discount_given` | Line Item | `originalTotalSet - discountedTotalSet` | `line_item_id` | DERIVED |
| Product Taxonomy / Category | F01, F10 | Shopify | `Product` | `productType` or `tags` | `order_line_items` | `category` | Line Item | Lowercase string; fallback to `'other'` | `line_item_id` | AVAILABLE BUT NOT PERSISTED |
| Units Purchased | F09, F10 | Shopify | `LineItem` | `quantity` | `order_line_items` | `quantity` | Line Item | Cast to Integer (default 1) | `line_item_id` | AVAILABLE BUT NOT PERSISTED |
| SKU Identifier | F10, F11 | Shopify | `ProductVariant` | `sku` or `id` | `order_line_items` | `product_id` | Line Item | Trim string; fallback to variant ID | `line_item_id` | AVAILABLE BUT NOT PERSISTED |
| Inventory Cost (COGS) | F01, F03, F04, F09, F10, F11 | Shopify / ERP | `InventoryItem` | `unitCost.amount` | `order_line_items` | `cogs_total` | Line Item | `unitCost * quantity`; if null, impute or ERP sync | `line_item_id` | AVAILABLE BUT NOT PERSISTED |
| Physical Dead Weight | F04 | Shopify | `ProductVariant` | `weight` + `weightUnit` | `product_variants` | `product_weight_kg`| Variant | Convert Grams/Ounces/Pounds to Kilograms | `variant_id` | AVAILABLE BUT NOT PERSISTED |
| Box Dimensions (L, W, H) | F04 | Shopify Metafield / PIM| `Metafield` | `namespace: dimensions` | `product_variants` | `length_cm`, `width_cm`, `height_cm` | Variant | Parse Float cm; nullable | `variant_id` | REQUIRES SOURCE FIELD CONFIRMATION |
| Customer Shipping Charge | F04, F05, F11, F12 | Shopify | `Order.shippingLines` | `originalPriceSet.shopMoney.amount` | `orders` | `shipping_charged_to_customer` | Order | Sum of active shipping line prices | `order_id` | AVAILABLE |
| Actual Courier Delivery Fee | F01, F03, F04, F05, F10, F11, F12 | Courier / 3PL API | Carrier Rate / Invoice | Billed freight charge | `orders` / `shipments` | `actual_shipping_cost` | Order / Shipment | Match tracking # / order # to carrier invoice | `order_id` | REQUIRES EXTERNAL SOURCE |
| Payment Gateway Fee | F01, F03, F10, F11, F12 | Shopify / Stripe | `OrderTransaction` | `fees.amount.amount` | `payments_transactions` | `gateway_fee` | Transaction | Sum fees across successful transactions | `order_id` | AVAILABLE BUT NOT PERSISTED |
| Refund Line Item Amount | F01, F10, F11 | Shopify | `RefundLineItem` | `subtotalSet.shopMoney.amount` | `return_line_items` | `refund_amount` | Returned Item | Cash credited back for returned line item | `line_item_id` | AVAILABLE BUT NOT PERSISTED |
| Restocking & Inspection Cost| F10, F11, F12 | Returns App (Loop) | Return Portal Event | `restocking_fee` | `return_line_items` | `restocking_cost` | Returned Item | Fixed fee or % deduction | `line_item_id` | REQUIRES EXTERNAL SOURCE |
| Reverse Shipping Cost | F10 | Courier API | Return Label Charge | Billed return freight | `return_line_items` | `return_shipping_cost` | Returned Item | Carrier invoice for return label | `line_item_id` | REQUIRES EXTERNAL SOURCE |
| Marketplace Referral Fee % | F09 | Marketplace APIs | Commission Schedule | Referral commission rate | `channel_fees` | `channel_fee_pct` | Channel / Item | Decimal rate (e.g. 0.1500 for Amazon) | `order_id` | REQUIRES EXTERNAL SOURCE |
| Chargeback / Dispute Loss | F12 | Shopify Disputes / Stripe| `Dispute` object | `amount.amount` | `orders` | `chargeback_amount` | Order | Total disputed funds + processor fine | `order_id` | AVAILABLE BUT NOT PERSISTED |

---

# 9. Derived Fields & Measures Specification

The table below catalogs every derived measure that must be computed dynamically in the scoring layer or relational view:

| Derived Measure | Formula Consumers | Mathematical Input Fields | Calculation Grain | Persist in Database? | Calculate in Scoring Layer? |
|---|---|---|---|---|---|
| `discount_given` | F01, F02, F12 | `selling_price`, `net_selling_price` | Line Item | No (Compute on read) | Yes (`selling_price - net_selling_price`) |
| `is_discounted` | F01, F02 | `discount_given` | Line Item / Order | No (Virtual Boolean) | Yes (`discount_given > 0`) |
| `volumetric_weight_kg` | F04 | `length_cm`, `width_cm`, `height_cm` | Variant / Line Item | No (Computed) | Yes (`(L * W * H) / 5000`) |
| `chargeable_weight_kg` | F04 | `product_weight_kg`, `volumetric_weight_kg`| Line Item / Order | No (Computed) | Yes (`max(scale_wt, volumetric_wt)`) |
| `product_gross_profit` | F04, F11 | `net_selling_price`, `cogs_total` | Line Item / Order | No | Yes (`sum(net_price - cogs)`) |
| `uncovered_shipping_cost`| F04, F12 | `actual_shipping_cost`, `shipping_charged_to_customer` | Order | No | Yes (`max(0, actual - charged)`) |
| `shipping_delta` | F05 | `shipping_charged_to_customer`, `actual_shipping_cost` | Order | No | Yes (`charged - actual`) |
| `revenue_share_ratio` | F10 | `net_selling_price`, `order_total_net_sales` | Line Item | No | Yes (`net_selling_price / order_total_net_sales`) |
| `allocated_shipping` | F10 | `actual_shipping_cost`, `revenue_share_ratio` | Line Item | No | Yes (`actual_shipping * revenue_share_ratio`) |
| `allocated_gateway` | F10 | `gateway_fee`, `revenue_share_ratio` | Line Item | No | Yes (`gateway_fee * revenue_share_ratio`) |
| `total_reverse_logistics_loss`| F10, F11, F12 | `refund_amount`, `restocking_cost`, `return_shipping_cost` | Line Item / Order | No | Yes (`refund + restocking + return_shipping`) |
| `order_profit` / CM | F01, F03, F11 | `net_selling_price`, `cogs_total`, `actual_shipping_cost`, `gateway_fee` | Order | Yes (Score Table) | Yes (`gross_margin - shipping - gateway_fee`) |
| `target_min_profit` | F01 | `net_selling_price`, `category_target_margin_pct` | Order | No | Yes (`sum(net_price * category_margin)`) |
| `f01_loss` | F01 | `target_min_profit`, `order_profit`, `is_discounted` | Order | Yes (Score Table) | Yes (`max(0, target_profit - order_profit)`) |
| `discounted_sales_share`| F02 | `selling_price` across discounted vs total orders | Store / Window | Yes (Store Score) | Yes (`discounted_gmv / total_gmv`) |
| `avg_discount_depth` | F02 | `discount_given`, `discounted_sales_gmv` | Store / Window | Yes (Store Score) | Yes (`total_discount / discounted_gmv`) |
| `f02_loss` | F02 | `total_sales`, `discounted_sales_share`, `avg_discount_depth` | Store / Window | Yes (Store Score) | Yes (`gmv * max(0, share - 0.20) * depth`) |
| `channel_unit_profit` | F09 | `net_selling_price`, `cogs_total`, `channel_fee_pct`, `quantity` | Channel | Yes (Store Score) | Yes (`sum(item_margin) / sum(quantity)`) |
| `channel_divergence_loss`| F09 | `web_unit_profit`, `channel_unit_profit`, `channel_units` | Channel | Yes (Store Score) | Yes (`max(0, web_profit - mkt_profit) * units`) |
| `sku_contribution` | F10 | `net_sales`, `cogs`, `reverse_loss`, `alloc_ship`, `alloc_gw` | SKU / Variant | Yes (SKU Score) | Yes (`net_sales - cogs - reverse - ship - gw`) |
| `total_revenue_leakage` | F12 | `discounts`, `returns_restock`, `shipping_deficits`, `gateway`, `disputes` | Store / Window | Yes (Store Score) | Yes (`sum(all_leak_buckets)`) |
| `revenue_quality_score` | F12 | `gross_sales`, `total_revenue_leakage` | Store / Window | Yes (Store Score) | Yes (`(net_retained / gross_sales) * 100`) |

---

# 10. Grain Requirements by Formula

| Formula Code | Required Calculation Grain | Why This Grain is Mandatory | Impact of Current DB Limitation |
|---|---|---|---|
| **F01** | Order (with Line-Item aggregation) | Evaluates order-level net profit against the sum of category-specific profit floors of active items. | Current DB has only order-level grain. Without line items, category mix and item discounts cannot be resolved. |
| **F02** | Store / Time Window (Rolling 30/90 days) | Compares total storewide discounted gross sales against overall gross sales. | Can be run on order-grain if `gross_sales` and order discount flags are present. |
| **F03** | Order (with Line-Item COGS aggregation) | Determines if an order resulted in cash loss after deducting true COGS, courier delivery, and gateway fee. | Requires line-item COGS sum to prevent false breaches. |
| **F04** | Order (with Variant Dimension lookup) | Determines if uncovered shipping exceeds product profit, using volumetric weight fallback per SKU. | Requires line-item dimensional lookups to calculate volumetric package mass. |
| **F05** | Order (Per-order delta) & Store (Net position) | Reconciles customer shipping billed vs actual courier invoice across orders. | Can be computed at order grain if `actual_shipping_cost` is persisted. |
| **F09** | Sales Channel / SKU Group | Evaluates unit margin erosion across sales channels (`web`, `amazon`, `tiktok`, `walmart`). | Requires channel identifier and line-item COGS + quantity. |
| **F10** | SKU / Variant (with Order Cost Allocation) | Calculates true contribution margin per SKU by allocating outbound shipping and gateway fees proportionally to revenue share. | **Completely blocked** without line-item table, SKU IDs, and partial return line item mapping. |
| **F11** | Order (with Line-Item aggregation) | Computes total order cash profit after COGS, actual freight, gateway fee, and return losses. | Requires line items to sum true COGS and isolate returned line items. |
| **F12** | Store / Time Window (Master Rollup) | Additive reconciliation of all 5 operational leak categories against gross GMV. | Requires order-level shipping deficits and line-level discount and return loss totals. |

---

# 11. Missing Production Data & Engineering Remediation

| Missing Production Data Asset | Consuming Formulas | Why the Formula Requires It | Can Shopify Provide It? | External Source Required | Database Structure Needed to Persist |
|---|---|---|---|---|---|
| **Order Line Items Table** | F01, F03, F04, F09, F10, F11, F12 | Required to access unit selling price, individual discounts, product taxonomy, and item COGS. | Yes (Native in `Order.lineItems`) | No | Create `order_line_items` table with FK to `orders`. |
| **Product Variants & SKUs Table** | F04, F10, F11 | Required to group financial performance by SKU and map physical dimensions. | Yes (Native in `ProductVariant`) | No | Create `product_variants` table with FK to `products`. |
| **COGS / Unit Cost Persistence** | F01, F03, F04, F09, F10, F11 | Margin calculations require deducting product inventory cost. | Conditional (~20% null in Shopify) | ERP / Accounting Sync (NetSuite, QuickBooks) | Add `cogs_unit_cost` to `product_variants` and `cogs_total` to `order_line_items`. |
| **Actual Courier Freight Cost** | F01, F03, F04, F05, F10, F11, F12 | Calculates real shipping leakage and net profit. Shipping charged is not courier cost. | **No (Structural Gap)** | Courier / 3PL Ingestion API (Shiprocket, EasyPost) | Add `actual_shipping_cost` to `orders` and create `shipments` table. |
| **External Gateway Fees** | F01, F03, F10, F11, F12 | Merchant processing fees erode margin by 1.5%–3.5%. | Conditional (Shopify Payments only) | Gateway APIs (Stripe, Razorpay, PayPal) | Create `payments_transactions` table linked by `order_id`. |
| **Marketplace Channel Commissions** | F09 | Marketplace platform fees (8%–15%) cause channel margin divergence. | **No (Structural Gap)** | Marketplace Seller APIs (Amazon SP-API, TikTok Shop) | Create `channel_fees` table linked by `order_id` / channel txn. |
| **Refund Line Items & Restocking Fees**| F10, F11, F12 | Partial returns require knowing exactly which SKU was returned and warehouse inspection costs. | Partially (Refund is native, restocking is not) | Returns App (Loop Returns / Return Prime) | Create `return_line_items` table with `refund_amount` and `restocking_cost`. |
| **Package Dimensions (L, W, H)** | F04 | Volumetric weight pricing on bulky lightweight goods. | Conditional (~10% in Metafields) | WMS / PIM / Metafield Ingestion | Add `length_cm`, `width_cm`, `height_cm` to `product_variants`. |
| **Historical Cost Snapshots** | All historical audits | Unit COGS changes over time; score recalculations must use order-time COGS. | No | Zeitster Cost Ingestion History | Create `cogs_history` table with effective date ranges. |

---

# 12. Shopify vs External Sources Matrix

| Required Data Asset | Shopify Admin API | Current Zeitster DB | External Source Needed? | Expected External Source System |
|---|---|---|---|---|
| **Orders Header** | Yes (`Order` object) | Yes (`orders` table) | No | Shopify Admin API |
| **Order Line Items** | Yes (`LineItem` nodes) | No | No (Ingest from Shopify) | Shopify Admin API |
| **Product Variants / SKUs** | Yes (`ProductVariant` nodes) | No | No (Ingest from Shopify) | Shopify Admin API |
| **Product Taxonomies / Types**| Yes (`Product.productType`) | No | No (Ingest from Shopify) | Shopify Admin API |
| **Dead Weight** | Yes (`ProductVariant.weight`)| No | No (Ingest from Shopify) | Shopify Admin API |
| **Product Dimensions (L,W,H)**| Conditional (Metafields only)| No | Yes (if Metafield missing)| PIM / WMS / Merchant Input |
| **Customer Shipping Charged** | Yes (`shippingLines`) | Yes (`orders.shipping_charged_to_customer`)| No | Shopify Admin API |
| **Actual Courier Freight Cost**| **No** | No | **Yes** | Courier API (Shiprocket / EasyPost / Delhivery) |
| **COGS (Cost of Goods Sold)** | Conditional (`InventoryItem.unitCost`)| No | Yes (for unmapped SKUs)| ERP / Inventory / Vendor Invoicing |
| **Shopify Payments Gateway Fee**| Yes (`Order.transactions`) | No | No (Ingest from Shopify) | Shopify Payments |
| **External Gateway Fees** | **No** | No | **Yes** | Stripe / Razorpay / PayPal API |
| **Marketplace Channel Fees** | **No** | No | **Yes** | Amazon SP-API / TikTok Shop / Walmart Seller |
| **Order Refund Total** | Yes (`Order.refunds`) | Yes (`orders.refund_amount`)| No | Shopify Admin API |
| **Refund Line Items** | Yes (`Refund.refundLineItems`)| No | No (Ingest from Shopify) | Shopify Admin API |
| **Warehouse Restocking Cost** | **No** | No | **Yes** | Returns App (Loop Returns / Return Prime) |
| **Return Freight Expense** | **No** | No | **Yes** | Reverse Logistics Carrier Rate Card |
| **Dispute / Chargeback Data** | Conditional (Shopify Payments)| No | Yes (for external gateways)| Processor Disputes API |

---

# 13. Current Database vs Required Database Comparison

| Data Domain / Entity | Current Database State | Required State for Scoring Engine | Remediation Action Required |
|---|---|---|---|
| **Orders** | Present (Order-grain metadata) | Present (Header with cost aggregations) | Add `actual_shipping_cost`, `gateway_fee`, `channel`, `chargeback_amount`. |
| **Products** | Present (Product-level table) | Present (Parent catalog reference) | Ensure taxonomy (`product_type`) is synchronized. |
| **Product Variants / SKUs** | Missing / Not separately persisted | **Mandatory** for SKU scoring (F10) & dimensions (F04) | Create `product_variants` table (`variant_id`, `sku`, `weight_kg`, `dimensions`, `unit_cost`). |
| **Order Line Items** | Missing / Not persisted | **Mandatory** for F01, F03, F04, F09, F10, F11 | Create `order_line_items` table (`line_item_id`, `order_id`, `variant_id`, prices, discounts, COGS). |
| **Refunds** | Order-level refund total only | Order-level + Line-item level refund details | Create `return_line_items` table linking refunds to specific line items. |
| **Payments & Fees** | Missing | **Mandatory** for gateway cost leakage | Create `payments_transactions` table to record gateway fees. |
| **Customer Shipping Charged**| Present (`shipping_amount`) | Present (`shipping_charged_to_customer`) | Retain and normalize column naming. |
| **Actual Courier Cost** | **Missing** | **Mandatory** for F01, F03, F04, F05, F10, F11, F12 | Add `actual_shipping_cost` to `orders` and build Courier API ingestion. |
| **COGS / Unit Cost** | **Missing** | **Mandatory** for F01, F03, F04, F09, F10, F11 | Populate `cogs_unit_cost` from Shopify with fallback ERP ingestion pipeline. |
| **Marketplace Channel Fees** | **Missing** | **Mandatory** for F09 Channel Divergence | Add `channel` to `orders` and create `channel_fees` commission table. |
| **Restocking / Return Labor** | **Missing** | **Mandatory** for F10 SKU net profit & F12 | Ingest return metadata from Returns App API. |
| **Historical Cost Snapshots** | **Missing** | Required for deterministic historical auditing | Create `cogs_history` table capturing effective date ranges. |

---

# 14. Concrete Database Changes Required for Scoring

To implement the required data model, the WebDev/Database team must execute the following concrete schema modifications:

### 14.1 New Tables to Create

```sql
-- 1. Product Variants / SKUs Table
CREATE TABLE product_variants (
    variant_id VARCHAR(64) PRIMARY KEY,
    product_id VARCHAR(64) NOT NULL,
    sku VARCHAR(64),
    title VARCHAR(255),
    product_weight_kg DECIMAL(10,3) DEFAULT 0.000,
    length_cm DECIMAL(10,2),
    width_cm DECIMAL(10,2),
    height_cm DECIMAL(10,2),
    cogs_unit_cost DECIMAL(10,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Order Line Items Table
CREATE TABLE order_line_items (
    line_item_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    variant_id VARCHAR(64) REFERENCES product_variants(variant_id),
    sku VARCHAR(64),
    category VARCHAR(64) NOT NULL DEFAULT 'other',
    quantity INTEGER NOT NULL DEFAULT 1,
    selling_price DECIMAL(10,2) NOT NULL,          -- original list total
    discount_given DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    net_selling_price DECIMAL(10,2) NOT NULL,       -- discounted invoice total
    cogs_total DECIMAL(10,2),                      -- unit_cost * quantity
    is_returned BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Return & Refund Line Items Table
CREATE TABLE return_line_items (
    return_item_id VARCHAR(64) PRIMARY KEY,
    line_item_id VARCHAR(64) NOT NULL REFERENCES order_line_items(line_item_id) ON DELETE CASCADE,
    refund_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id),
    refund_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    restocking_cost DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    return_shipping_cost DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    return_reason VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. Payment Gateway Transactions Table
CREATE TABLE payments_transactions (
    transaction_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    gateway_name VARCHAR(64) NOT NULL,
    transaction_amount DECIMAL(10,2) NOT NULL,
    gateway_fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. Shipments & Carrier Invoices Table
CREATE TABLE shipments (
    shipment_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    carrier_name VARCHAR(64) NOT NULL,
    tracking_number VARCHAR(128),
    billed_shipping_cost DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    chargeable_weight_kg DECIMAL(10,3),
    shipped_at TIMESTAMP WITH TIME ZONE
);

-- 6. Marketplace Channel Fees Table
CREATE TABLE channel_fees (
    channel_fee_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    channel_name VARCHAR(32) NOT NULL,
    referral_fee_pct DECIMAL(5,4) NOT NULL DEFAULT 0.0000,
    fixed_commission DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 7. COGS Historical Ledger Table
CREATE TABLE cogs_history (
    cogs_snapshot_id BIGSERIAL PRIMARY KEY,
    variant_id VARCHAR(64) NOT NULL REFERENCES product_variants(variant_id),
    unit_cost DECIMAL(10,2) NOT NULL,
    effective_from TIMESTAMP WITH TIME ZONE NOT NULL,
    effective_to TIMESTAMP WITH TIME ZONE,
    source_system VARCHAR(32) NOT NULL DEFAULT 'shopify'
);
```

### 14.2 Columns to Add to Existing `orders` Table

```sql
ALTER TABLE orders 
    ADD COLUMN IF NOT EXISTS channel VARCHAR(32) NOT NULL DEFAULT 'web',
    ADD COLUMN IF NOT EXISTS actual_shipping_cost DECIMAL(10,2) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS gateway_fee DECIMAL(10,2) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS chargeback_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    ADD COLUMN IF NOT EXISTS free_shipping_applied BOOLEAN GENERATED ALWAYS AS (shipping_charged_to_customer = 0.00) STORED;
```

---

# 15. Final Technical Architecture Flow

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       INGESTION & SOURCE SYSTEMS                                       │
│                                                                                                        │
│  [Shopify Admin GraphQL API]        [Courier / 3PL API]           [Payment Gateways]                   │
│   - Orders, LineItems, Variants      - Actual Billed Courier Cost  - Shopify Payments / Stripe Fees    │
│   - Refunds, Weight, Metafields      - Tracking & Chargeable Wt    - Dispute / Chargeback Amounts      │
│                │                                │                                │                     │
│                ▼                                ▼                                ▼                     │
│  [Marketplace Seller APIs]          [Returns Management App]      [ERP / Inventory Cost]               │
│   - Amazon SP-API, TikTok Shop       - Loop Returns Restocking Fee - Historical Unit COGS Ledger       │
│   - Marketplace Channel Fees         - Reverse Freight Label Cost  - SOURCE TO BE CONFIRMED            │
└────────────────────────────────────────────────┬───────────────────────────────────────────────────────┘
                                                 │
                                                 │ Webhooks / Scheduled Batch Sync
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   ZEITSTER RELATIONAL DATABASE MODEL                                   │
│                                                                                                        │
│  ┌────────────────────────┐      1:N      ┌────────────────────────┐      N:1     ┌─────────────────┐  │
│  │         orders         ├──────────────►│    order_line_items    ├─────────────►│product_variants │  │
│  │ PK: order_id           │               │ PK: line_item_id       │              │PK: variant_id   │  │
│  │ FK: store_id           │               │ FK: order_id           │              │FK: product_id   │  │
│  │ actual_shipping_cost   │               │ FK: variant_id         │              │sku, weight_kg   │  │
│  │ gateway_fee, channel   │               │ selling_price, net_rev │              │length/width/hgt │  │
│  │ chargeback_amount      │               │ cogs_total, category   │              │cogs_unit_cost   │  │
│  └───────────┬────────────┘               └───────────┬────────────┘              └─────────────────┘  │
│              │                                        │                                                │
│              ├───────────────────┐                    │ 1:1                                            │
│              │ 1:N               │ 1:N                ▼                                                │
│              ▼                   ▼        ┌────────────────────────┐                                   │
│  ┌────────────────────────┐ ┌──────────┐  │   return_line_items    │                                   │
│  │ payments_transactions  │ │shipments │  │ PK: return_item_id     │                                   │
│  │ PK: transaction_id     │ │PK: ship_id  │ FK: line_item_id       │                                   │
│  │ gateway_fee            │ │billed_cost  │ refund_amount, restock │                                   │
│  └────────────────────────┘ └──────────┘  └────────────────────────┘                                   │
└────────────────────────────────────────────────┬───────────────────────────────────────────────────────┘
                                                 │
                                                 │ Dynamic SQL / In-Memory Derived Measures
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 DERIVED METRICS & ALLOCATION LAYER                                     │
│  - Line Gross Margin: `net_selling_price - cogs_total`                                                 │
│  - Revenue Share Ratio: `line_net_sales / order_total_net_sales`                                       │
│  - Allocated Outbound Freight: `actual_shipping_cost * revenue_share_ratio`                            │
│  - Allocated Merchant Gateway Fee: `gateway_fee * revenue_share_ratio`                                 │
│  - Reverse Logistics Drain: `refund_amount + restocking_cost + return_shipping_cost`                   │
│  - Chargeable Weight: `max(product_weight_kg, (L * W * H) / 5000)`                                     │
└────────────────────────────────────────────────┬───────────────────────────────────────────────────────┘
                                                 │
                                                 │ Clean Metric Input Vectors
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                      ZEITSTER SCORING ENGINE (F01–F12)                                 │
│                                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ ORDER LEVEL:                                                                                     │  │
│  │   • F01 Promo Margin Leakage: max(0, Target Margin Floor - Order Net Profit)                     │  │
│  │   • F03 Margin Floor Breach: Order Profit < 0 (Flag) and Severity ($)                            │  │
│  │   • F04 Free Shipping Leakage: max(0, Uncovered Courier Cost - Product Profit)                   │  │
│  │   • F05 Shipping Cost Recovery: (Shipping Charged / Actual Courier Cost) * 100                   │  │
│  │   • F11 Order Net Profitability: Total Collected - COGS - Actual Freight - Gateway - Returns     │  │
│  └──────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ PRODUCT / SKU LEVEL:                                                                             │  │
│  │   • F10 SKU Product Contribution: Net Sales - COGS - Reverse Logistics - Alloc Ship - Alloc GW   │  │
│  └──────────────────────────────────────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ STORE / CHANNEL LEVEL:                                                                           │  │
│  │   • F02 Discount Dependency: Total GMV * max(0, Disc Share - 0.20) * Avg Discount Depth          │  │
│  │   • F09 Channel Margin Divergence: (Marketplace Unit Profit / Direct Web Unit Profit) * 100      │  │
│  │   • F12 Revenue Quality Score: (Net Retained Revenue / Gross Merchandise Sales) * 100            │  │
│  └──────────────────────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────┬───────────────────────────────────────────────────────┘
                                                 │
                                                 │ Scored Vectors & Diagnostics
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     MERCHANT APPLICATION & WRITE-BACK                                  │
│  - Executive Profitability & Leakage Dashboard                                                         │
│  - Shopify GraphQL Metafield Mutation Pipeline (`zeitster_scores.*`)                                   │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

# Technical Implementation Document: R10 — Fraud Loss Impact Score

**Business Context:** Zeitster  
**Functional Category:** Category 2 — Fraud, Returns & Disputes  
**Metric Identifier:** R10 — Fraud Loss Impact Score  
**Target Audience:** WebDev, Data Engineering (ETL), and Database Architecture Teams  

---

## 1. Data Mapping

### 1.1 Formula Component Data Mapping

| # | R10 Component | Formula / Logic | Required Input | Source Type | Source Field | Transformation |
|---|---|---|---|---|---|---|
| **1** | **Order Refund Amount** | $\text{Refund Amount} \times \text{FX}$ | `Order.refunds.totalRefundedSet` | **SHOPIFY DIRECT** | `Order.refunds.totalRefundedSet.shopMoney.amount` | Convert to base currency via `FX_Rate(createdAt)`. In partial disputes without direct refund record, set equal to `disputed_amount`. |
| **2** | **Bank Chargeback Penalty Fee** | Fixed fee per dispute event | `Order.disputes` / Config Fallback | **SHOPIFY CONDITIONAL** | `Dispute.fee` (Shopify Payments) or **ZEISTER CONFIGURATION** | If absent: Fallback USD=\$15, EUR=€15, GBP=£10, CAD=\$20. Multiplied by FX. Never prorated in partial disputes. |
| **3** | **Product Sourcing Cost (COGS)** | $\sum (\text{unitCost} \times \text{qty}) \times \text{FX}$ | `unitCost` / Category Avg | **SHOPIFY CONDITIONAL** | `ProductVariant.inventoryItem.unitCost.amount` | If null, substitute `category_avg_cogs`. Scale by `dispute_value_ratio` in partial disputes. |
| **4** | **Outbound Shipping Fee** | Actual courier cost or percentage fallback | 3PL Invoice / Net Item Value | **EXTERNAL** | External Carrier Invoices or 5% Domestic / 15% International Fallback | If external 3PL API cost missing, compute: $\text{Item Price} \times (0.05 \text{ or } 0.15) \times \text{FX}$. Scale by `dispute_value_ratio` in partial disputes. |
| **5** | **Packaging Material Cost** | Item Value $\times 2\%$ clamped $[\$0.50, \$5.00]$ | Net Item Selling Price | **ZEISTER CONFIGURATION** | `Shop.metafields.packaging_config` or Fallback rule | Clamp $(\text{Item Price} \times 0.02, \min=0.50, \max=5.00) \times \text{FX}$. Partial dispute allocation undefined (baseline: full order value). |
| **6** | **Warehouse Fulfillment Labor Cost** | Item Value $\times 3\%$ clamped $[\$1.00, \$10.00]$ | Net Item Selling Price | **ZEISTER CONFIGURATION** | `Shop.metafields.labor_config` or Fallback rule | Clamp $(\text{Item Price} \times 0.03, \min=1.00, \max=10.00) \times \text{FX}$. Partial dispute allocation undefined (baseline: full order value). |
| **7** | **Unrefunded Payment Gateway Fee** | Incurred fee or $2.5\%$ of disputed amount | `transactions.fees` / Disputed Value | **SHOPIFY CONDITIONAL** | `Order.transactions.fees.amount.amount` | If null, compute $\text{disputed\_amount} \times 0.025 \times \text{FX}$. Scale by `dispute_value_ratio` in partial disputes if native fee is order-level. |
| **8** | **Unrefunded Platform Fee** | Disputed Value $\times 2.5\%$ | Disputed Value / Merchant Config | **ZEISTER CONFIGURATION** | `Shop.metafields.platform_fee_rate` (Default: 2.5%) | Compute $\text{disputed\_amount} \times 0.025 \times \text{FX}$. Partial dispute allocation undefined (baseline: full order value). |
| **9** | **Customs Clearance / COD Fee** | Incurred cross-border fee | External Carrier / Customs Entry | **EXTERNAL** | Carrier Customs Entry Invoice | If null/missing: evaluate as $\$0.00$ and flag for clarification. Partial dispute allocation undefined. |
| **10** | **Customer Support Dispute Cost** | Support ticket logging | Support Helpdesk System (Zendesk/Gorgias) | **EXTERNAL** | Support Ticket Worklog | If manual support log exists: $\text{logged\_cost} \times \text{FX}$; otherwise $\$0.00$. Applied at full order level. |
| **11** | **Gross Order Revenue** | Item Net $+$ Cust. Ship $+$ Cust. Tax | Shopify Order Totals | **SHOPIFY DIRECT** | `Order.totalPriceSet.shopMoney.amount` | Convert to base currency via `FX_Rate(createdAt)`. |

---

### 1.2 Shopify Admin GraphQL Mapping (Verified Local GraphiQL)

| R10 Requirement | Shopify Object | Exact GraphQL Field | Verified? | Usage | Transformation |
|---|---|---|---|---|---|
| **Gross Order Revenue** | `Order` | `totalPriceSet.shopMoney.amount` | **VERIFIED — LOCAL GRAPHIQL** | Denominator of R10 | Parse to float, multiply by creation date FX. |
| **Line Item Selling Price** | `LineItem` | `discountedTotalSet.shopMoney.amount` | **VERIFIED — LOCAL GRAPHIQL** | Net sales basis for proration | Sum across all order line items. |
| **Customer-Paid Shipping** | `ShippingLine` | `discountedPriceSet.shopMoney.amount` | **VERIFIED — LOCAL GRAPHIQL** | Gross revenue component | Sum over `shippingLines.nodes`. Default $0.00$ if empty. |
| **Customer-Paid Tax** | `Order` | `totalTaxSet.shopMoney.amount` | **VERIFIED — LOCAL GRAPHIQL** | Gross revenue component | Parse to float. Default $0.00$ if null. |
| **Refunds** | `Refund` | `totalRefundedSet.shopMoney.amount` | **VERIFIED — LOCAL GRAPHIQL** | Loss Component 1 | Deduplicate across `refunds` array by refund `id`. |
| **Dispute Eligibility & Status** | `Dispute` | `status` (via `Order.disputes`) | **VERIFIED — LOCAL GRAPHIQL** | Eligibility Filter | Validate against `CHARGEBACK_OPENED`, `CHARGEBACK_LOST`, `NEEDS_RESPONSE`, `UNDER_REVIEW`. |
| **Disputed Amount** | `Dispute` | `amountSet.shopMoney.amount` | **VERIFIED — LOCAL GRAPHIQL** | Loss Component 2 & Proration Ratio | Extract disputed amount in order currency. |
| **Dispute Fee (Native)** | `Dispute` | `fee.amount` | **VERIFIED — LOCAL GRAPHIQL** | Loss Component 2 | Available for Shopify Payments. Fallback to config if null. |
| **Product COGS** | `InventoryItem` | `unitCost.amount` (via `LineItem.variant.inventoryItem`) | **VERIFIED — LOCAL GRAPHIQL** | Loss Component 3 | $\sum (\text{unitCost} \times \text{currentQuantity})$. Fallback to category average if null. |
| **Gateway Transaction Fees** | `OrderTransaction` | `fees.amount.amount` (via `Order.transactions`) | **VERIFIED — LOCAL GRAPHIQL** | Loss Component 7 | Sum fees across `SUCCESS` capture transactions. Fallback to 2.5% if empty. |
| **Fulfillment Status** | `Fulfillment` / `Order` | `displayFulfillmentStatus` | **VERIFIED — LOCAL GRAPHIQL** | Eligibility Filter | Validate $\in \{\text{FULFILLED}, \text{PARTIALLY\_FULFILLED}\}$ (maps to `SHIPPED`/`DELIVERED`). |
| **Order Creation Timestamp** | `Order` | `createdAt` | **VERIFIED — LOCAL GRAPHIQL** | FX Normalization | Use date string (`YYYY-MM-DD`) to fetch historical exchange rate. |
| **Order Currency** | `Order` | `currencyCode` | **VERIFIED — LOCAL GRAPHIQL** | FX Normalization | Determine base currency conversion factor. |
| **Destination Country** | `Order` | `shippingAddress.countryCodeV2` | **VERIFIED — LOCAL GRAPHIQL** | Shipping Fallback Selection | Determine `is_international = (shippingAddress.countryCodeV2 != shop.countryCode)`. |
| **Product Category** | `Product` | `productType` (or `tags`) | **VERIFIED — LOCAL GRAPHIQL** | Category COGS Fallback | Key to look up category average COGS table. |

---

### 1.3 Derived Fields

| Derived Field | Formula | Source Fields | Used For |
|---|---|---|---|
| **Disputed Value Ratio ($r$)** | $\min\left(1.0, \frac{\text{Disputed Amount}}{\sum \text{LineItem.discountedTotalSet}}\right)$ | `Dispute.amountSet`, `LineItem.discountedTotalSet` | Proration of variable loss components (Refund, COGS, Courier Shipping, Gateway Fee) in partial disputes. |
| **Category-Average COGS Fallback** | $\text{Category\_COGS\_Table}[\text{Product.productType}] \times \text{Quantity}$ | `Product.productType`, `Shop.metafields.category_cogs` | Sourcing cost loss calculation when `inventoryItem.unitCost` is null. |
| **Unrefunded Gateway Fee Calculation** | $\text{IF } \text{fees} \ne \text{null} \implies \sum \text{fees}; \text{ ELSE } \text{Disputed Amount} \times 0.025$ | `Order.transactions.fees`, `disputed_amount` | Loss Component 7 quantification. |
| **Unrefunded Platform Fee Calculation** | $\text{Disputed Amount} \times \text{platform\_fee\_rate}\ (0.025)$ | `disputed_amount`, `Shop.metafields.platform_fee_rate` | Loss Component 8 quantification. |
| **Partial-Dispute Sourcing Loss** | $\text{base\_cogs} \times r$ | `base_cogs`, `dispute_value_ratio` | Allocated COGS loss for partial dispute orders. |
| **Partial-Dispute Shipping Loss** | $\text{base\_shipping} \times r$ | `base_shipping`, `dispute_value_ratio` | Allocated Courier Shipping loss for partial dispute orders. |
| **Total Monetary Fraud Loss** | $\sum_{k=1}^{10} \text{Loss Component}_k$ | Loss Components 1 through 10 | Numerator of the R10 risk formula. |
| **Final R10 Score** | $\text{IF } \text{Rev} = 0 \implies (\text{IF } \text{Loss} > 0 \implies 100; \text{ELSE } 0); \text{ELSE } \min(100.0, \frac{\text{Loss}}{\text{Rev}} \times 100)$ | `total_monetary_fraud_loss`, `gross_order_revenue` | Primary R10 metric written back to order metafields and dashboard. |

---

### 1.4 External & Configuration Data Sources

| Requirement | Type | Required Value | Where It Comes From | DB / Config Target |
|---|---|---|---|---|
| **Actual Courier Shipping Cost** | External Data | Billed courier invoice amount | **EXTERNAL SOURCE NOT SPECIFIED** (3PL Courier APIs / Carrier Invoice CSV) | `order_logistics_costs` table |
| **Customs Clearance / COD Fee** | External Data | Cross-border customs assessment fee | **EXTERNAL SOURCE NOT SPECIFIED** (Customs Brokerage / Carrier Invoice Data) | `order_customs_fees` table |
| **Third-Party Gateway Processing Fees** | External Data | Exact fee deducted by external gateway | External Payment Gateway APIs (Stripe / PayPal Settlement Reports) | `gateway_settlement_transactions` table |
| **Customer Support Dispute Cost** | External Data | Support labor cost allocated to dispute | Helpdesk Worklogs (Zendesk / Gorgias API) | `support_dispute_logs` table |
| **Historical Exchange Rates (FX)** | External Data | Exchange rate on `Order.createdAt` | Financial FX Rate API (OpenExchangeRates / ECB) | `currency_exchange_rates` table |
| **Bank Chargeback Penalty Fallback** | Zeister Config | `USD: 15.00`, `CAD: 20.00`, `EUR: 15.00`, `GBP: 10.00` | Zeister Tenant Configuration Metafield | `tenant_fraud_config.chargeback_fallbacks` |
| **Packaging Material Cost Model** | Zeister Config | $\text{Rate} = 2\%$, $\text{Min} = \$0.50$, $\text{Max} = \$5.00$ | Zeister Tenant Configuration Metafield | `tenant_fraud_config.packaging_model` |
| **Warehouse Fulfillment Labor Model** | Zeister Config | $\text{Rate} = 3\%$, $\text{Min} = \$1.00$, $\text{Max} = \$10.00$ | Zeister Tenant Configuration Metafield | `tenant_fraud_config.labor_model` |
| **Fallback Courier Shipping Rates** | Zeister Config | $\text{Domestic} = 5\%$, $\text{International} = 15\%$ | Zeister Tenant Configuration Metafield | `tenant_fraud_config.shipping_fallbacks` |
| **Unrefunded Platform Fee Rate** | Zeister Config | $2.5\%$ ($0.025$) of disputed value | Zeister Tenant Configuration Metafield | `tenant_fraud_config.platform_fee_rate` |
| **Category Average COGS Matrix** | Zeister Config | e.g., `{"Apparel": 35.00, "Electronics": 120.00}` | Zeister Merchant Catalog Metafield | `catalog_category_cogs` table |

---

## 2. Missing Value & Null Handling

| Field | Missing/Null Scenario | Approved Fallback | Technical Handling |
|---|---|---|---|
| `ProductVariant.inventoryItem.unitCost` | Sourcing cost is null in catalog (~20% of catalog items) | Category-Average COGS | Look up `Shop.metafields.category_avg_cogs[productType]`. If category not found, default to `0.00` and append warning flag to audit trail. |
| `OrderTransaction.fees` | Empty transaction array / Non-Shopify Payments gateway | $2.5\%$ of Disputed Amount | Compute $\text{disputed\_amount} \times 0.025 \times \text{FX}$. Log fallback applied. |
| `Shop.metafields.platform_fee_rate` | Missing platform fee rate in config | $2.5\%$ of Disputed Amount | Compute $\text{disputed\_amount} \times 0.025 \times \text{FX}$. |
| `outbound_shipping_fee` (External) | 3PL courier invoice missing | 5% Domestic / 15% International | If `is_international == false`: $\text{Item Net} \times 0.05 \times \text{FX}$. If `is_international == true`: $\text{Item Net} \times 0.15 \times \text{FX}$. |
| `packaging_material_cost` | Missing packaging configuration | 2% of Item Net clamped to $[\$0.50, \$5.00]$ | Compute $\min(5.00, \max(0.50, \text{Item Net} \times 0.02)) \times \text{FX}$. |
| `warehouse_labor_cost` | Missing fulfillment labor configuration | 3% of Item Net clamped to $[\$1.00, \$10.00]$ | Compute $\min(10.00, \max(1.00, \text{Item Net} \times 0.03)) \times \text{FX}$. |
| `bank_chargeback_fee` | Missing dispute fee from gateway payload | Currency-specific fallback | Match order currency: `USD: $15`, `CAD: $20`, `EUR: €15`, `GBP: £10`. Fallback for any other currency: `$15.00 USD` equivalent. |
| `support_dispute_cost` | No manual support worklog entry found | $\$0.00$ | Set $\text{Loss}_{10} = 0.00$. Do not estimate or extrapolate. |
| `customs_cod_fee` | Missing cross-border customs / COD data | **UNDEFINED / BUSINESS RULE REQUIRED** | Set to $\$0.00$ baseline; record explicit `clarification_required` flag in database. |
| `Order.disputes` (Empty Array) | No dispute object present on order | Check `Order.refunds` for fraud tag | If refund reason contains `"fraud"` or `"fraudulent"`, classify as `FRAUD_REFUND`; otherwise mark order as ineligible ($\text{R10} = 0.00$). |
| `Order.refunds` (Empty Array) | No refund object present on order | Use `disputed_amount` from `Dispute` | If dispute exists, $\text{Refund Loss} = \text{disputed\_amount}$. |
| `exchange_rate` | Null or $\le 0$ FX rate | $1.00$ | Default FX multiplier to $1.00$ and emit pipeline data health alert. |

---

## 3. Edge Cases & Boundary Handling

| Edge Case | Expected Handling | Tested? | Test Result | Technical Action |
|---|---|:---:|:---:|---|
| **Zero Revenue with Positive Loss** | $\text{Gross Rev} = 0 \land \text{Loss} > 0 \implies \mathbf{Score = 100.0}$ | Yes (T03) | **PASS** | Guardrail check: bypass division by zero, return float `100.0`. |
| **Zero Revenue with Zero Loss** | $\text{Gross Rev} = 0 \land \text{Loss} = 0 \implies \mathbf{Score = 0.0}$ | Yes (T04) | **PASS** | Guardrail check: bypass division by zero, return float `0.0`. |
| **Loss Greater than Revenue** | Raw ratio $> 100.0 \implies \mathbf{Score = 100.0}$ | Yes (T07, T44) | **PASS** | Apply $\min(100.0, \text{raw\_score})$. |
| **Full Refund** | Full item price refunded | Yes (T01, T15) | **PASS** | $100\%$ of refund amount included in $\text{Loss}_1$. |
| **Partial Refund** | Partial refund on line items | Yes (T14, T36) | **PASS** | Include exact refunded monetary value in $\text{Loss}_1$. |
| **Full Dispute** | Disputed amount equals order net sales ($r = 1.0$) | Yes (T15) | **PASS** | Scale variable components by $1.0$; include 100% of order losses. |
| **Partial Dispute** | Disputed amount $<$ order net sales ($r < 1.0$) | Yes (T14, T45) | **PASS** | Prorate Refund, COGS, Courier Shipping, Gateway Fee by $r$. |
| **Multiple Disputes on Single Order** | Multiple chargebacks opened on same `order_id` | Yes (T13) | **PASS** | Aggregate all valid dispute loss amounts into a single composite score. |
| **Multiple Capture Transactions** | Multiple payment captures on single order | Yes (T35) | **PASS** | Sum gateway transaction fees across all successful capture transactions. |
| **Missing COGS** | `inventoryItem.unitCost == null` | Yes (T16) | **PASS** | Substitute `category_avg_cogs` without throwing null pointer exception. |
| **Missing Gateway / Platform Fees** | Empty fee arrays | Yes (T21, T22) | **PASS** | Trigger 2.5% fallback calculation on disputed amount. |
| **Null Values across all Optionals** | All optional loss fields set to `null` | Yes (T38) | **PASS** | Execute graceful 7-tier fallback cascade. |
| **Empty String Mandatory Fields** | `fulfillment_status = ""` or `dispute_status = null` | Yes (T39) | **PASS** | Mark `is_eligible = false`, return `final_r10_score = 0.0`. |
| **Zero Gateway Fee** | Gateway fee explicitly $\$0.00$ | Yes (T02) | **PASS** | Ingest $0.00$ without triggering missing fallback. |
| **Zero Shipping Cost** | Free shipping order ($0 charged) | Yes (T07) | **PASS** | Denominator includes $\$0.00$ shipping; courier loss computed normally. |
| **Negative Monetary Values** | Ingestion payload contains negative numbers | Yes (T37) | **PASS** | **BUSINESS RULE REQUIRED**: Baseline passes raw values; flag in audit log. |
| **Duplicate Dispute Webhooks** | Repeated webhook deliveries for same dispute ID | Yes (T32) | **PASS** | **TECHNICAL DEDUPLICATION**: Idempotency key on `dispute_id`. |
| **Duplicate Refund Transactions** | Duplicate refund events for same refund ID | Yes (T33) | **PASS** | **TECHNICAL DEDUPLICATION**: Idempotency key on `refund_id`. |
| **Multi-Item Order** | Order containing multiple distinct line items | Yes (T35) | **PASS** | Aggregate line item prices and line item COGS before applying formula. |
| **Foreign Currency Normalization** | Order in EUR, GBP, or CAD with FX rate | Yes (T25, T26) | **PASS** | Multiply all revenue and loss components by `FX_Rate(createdAt)`. |
| **Sub-Dollar Penny Precision** | Fractional cent amounts | Yes (T41) | **PASS** | Retain IEEE 754 double precision without truncation. |
| **Score Rounding** | Final score decimal representation | Yes (T42) | **PASS** | **BUSINESS RULE REQUIRED**: Retain raw float; UI layer formats to 2 decimals. |
| **Score Exactly = 100.0** | Total Fraud Loss exactly equals Gross Revenue | Yes (T06) | **PASS** | Evaluates cleanly to float `100.0`. |
| **Score Exactly = 0.0** | Fraud dispute with zero monetary losses | Yes (T02) | **PASS** | Evaluates cleanly to float `0.0`. |

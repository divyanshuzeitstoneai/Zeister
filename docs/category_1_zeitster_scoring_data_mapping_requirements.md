# Zeitster — Category 1: Financial & Margin Leakage
## Phase 4: Production Data Mapping & WebDev Alignment Specification

### Document Navigation (Outline)
- [1. Status Legend & Field Classification](#1-status-legend--field-classification)
- [2. Consolidated Executive Summary (Expected Outputs Matrix)](#2-consolidated-executive-summary-expected-outputs-matrix)
- [3. Formula-by-Formula Detailed Mapping & Logic](#3-formula-by-formula-detailed-mapping--logic)
  - [F01 — Promotion Margin Leakage](#f01--promotion-margin-leakage)
  - [F02 — Discount Dependency Score](#f02--discount-dependency-score)
  - [F03 — Margin Floor Breach](#f03--margin-floor-breach)
  - [F04 — Free Shipping Leakage](#f04--free-shipping-leakage)
  - [F05 — Shipping Cost Recovery](#f05--shipping-cost-recovery)
  - [F06 — Payment Fee Leakage Score](#f06--payment-fee-leakage-score)
  - [F09 — Channel Margin Divergence](#f09--channel-margin-divergence)
  - [F10 — Product Contribution](#f10--product-contribution)
  - [F11 — Order Profitability](#f11--order-profitability)
  - [F12 — Revenue Quality Score](#f12--revenue-quality-score)

---

## 1. Status Legend & Field Classification

| Status Tag | Classification | Description |
|---|---|---|
| ✅ **SHOPIFY — VERIFIED** | Verified Field | Natively present in Shopify Admin GraphQL, verified live against real test orders, and accessible directly via standard query paths. |
| ⚠️ **SHOPIFY — PARTIAL** | Conditional Field | Exists in Shopify GraphQL but requires live payment gateways (e.g., Shopify Payments / Stripe for transaction fees), specific API scopes (`read_inventory`), or returns null on manual test orders. |
| ⚙️ **SHOPIFY — METAFIELD / CONFIG** | Configuration Metafield | Business configuration parameters not generated during customer checkout. Must be provisioned as Shop-level or ProductVariant-level Metafields. |
| ❌ **NOT IN SHOPIFY / EXTERNAL** | External Data Source | Completely absent from Shopify Admin GraphQL. Ingested via external systems (3PL Courier APIs, carrier invoice CSV imports, Marketplace Seller Central APIs). |
| 🧮 **PIPELINE / DERIVED** | ETL Computed Metric | Statistical, predictive, or allocation-weighted metric computed within the backend ETL scoring engine by combining multiple raw fields. |

---

## 2. Consolidated Executive Summary (Expected Outputs Matrix)

| Metric | Business Indicator | Logic & Core Calculation | Raw Output | Normalized / Tier Output | Business Health State |
|---|---|---|---|---|---|
| **F01** | Promo Margin Leakage | $\text{Target Profit} - \text{Actual Profit}$ | `+$25.00` | `10.0% Margin Gap` | ⚠️ Margin Subsidized |
| **F02** | Discount Dependency | $\left(\frac{\text{Total Discounts}}{\text{Gross Sales}}\right) \times 100$ | `30.0%` | `Warning Tier` | ⚠️ Heavy Promotion |
| **F03** | Margin Floor Breach | $\text{Net Revenue} - \text{Active COGS} - \text{Shipping} - \text{Fees} < 0$ | `-$315.00` | `BREACH (True)` | 🔴 Critical Cash Loss |
| **F04** | Free Shipping Leakage | $\max(0, \text{Uncovered Shipping} - \text{Product Profit})$ | `+$20.00` | `71.4% Coverage` | ⚠️ Uncovered Logistics |
| **F05** | Shipping Recovery | $\left(\frac{\text{Shipping Charged}}{\text{Actual Courier Cost}}\right) \times 100$ | `-$5.00` | `50.0% Recovery` | ⚠️ 50% Self-Subsidized |
| **F06** | Payment Fee Leakage | $\max(0, \text{Actual Gateway Fee} - \text{Benchmark Fee})$ | `+$1.55` | `53.0% Efficiency` | ⚠️ Gateway Fee Leakage |
| **F09** | Channel Divergence | $\text{Web Unit Profit} - \text{Marketplace Unit Profit}$ | `+$37.50 / unit` | `62.5% Efficiency` | ℹ️ Marketplace Drag |
| **F10** | Product Contribution | $\text{Net Revenue} - \text{Active COGS} - \text{Allocated Overhead}$ | `+$78.99` | `31.60% Contribution` | 🟢 Healthy Retained Unit |
| **F11** | Order Profitability | $\text{Retained Cash} - \text{Active COGS} - \text{Costs} - 5\% \text{ Provision}$ | `+$90.40` | `24.43% Margin` | 🟢 Net Cash Positive |
| **F12** | Revenue Quality | $\left(\frac{\text{Net Retained Revenue}}{\text{Gross Revenue}}\right) \times 100$ | `+$325.00` | `37.36% Retained` | 🔴 High Return Attrition |


---

## 3. Formula-by-Formula Detailed Mapping & Logic

### F01 — Promotion Margin Leakage

#### Core Mathematical Formula:
$$\text{Target Profit} = \text{Net Selling Price} \times \text{Category Target Margin}$$
$$\text{Actual Profit} = \text{Net Selling Price} - \text{COGS}$$
$$\text{Line Leakage} = \max(0, \text{Target Profit} - \text{Actual Profit}) \times \text{currentQuantity}$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `net_selling_price` | ✅ VERIFIED | `LineItem.discountedUnitPriceSet.shopMoney.amount` | `"500.0"`, `"250.0"`, `"120.0"`, `"90.0"` |
| `cogs` | ✅ VERIFIED | `LineItem.variant.inventoryItem.unitCost.amount` | `"300.0"`, `"150.0"`, `"80.0"`, `"40.0"` |
| `active_units` | ✅ VERIFIED | `LineItem.currentQuantity` | `1` (Active), `0` (Refunded/Canceled) |
| `category` | ✅ VERIFIED | `LineItem.product.category.name` | Fallback: `LineItem.product.productType` |
| `target_margin` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "category_margin_targets")` | JSON: `{"apparel": 0.50, "electronics": 0.40}` |
| `is_cogs_estimated` | 🧮 PIPELINE | ETL flag set when `inventoryItem.unitCost == null` | `true` on Order #1013 (Item B) |
| `is_returned` | ✅ VERIFIED | `Order.refunds.refundLineItems.lineItem.id` | Returns `true` if line item ID matched |

#### Developer Fallback & Transformation Rules:
- **Category Ladder:** `LineItem.product.category.name` ⟶ `LineItem.product.productType` ⟶ `"Uncategorized"`.
- **Missing COGS Ladder:** If `unitCost == null`, set `is_cogs_estimated = true` and inject category average margin target. If `unitCost` exists, set `is_cogs_estimated = false`.
- **Refund Filter:** Only compute leakage on active items where `currentQuantity > 0`.

#### Calculation Trace (Order #1014 - Electronics Item C):
- Net Price = $\$250.00$, COGS = $\$150.00$, Target Margin = $50\%$
- $\text{Target Profit} = \$250.00 \times 0.50 = \$125.00$
- $\text{Actual Profit} = \$250.00 - \$150.00 = \$100.00$
- $\text{Shortfall Leakage} = \max(0, \$125.00 - \$100.00) \times 1 = +\$25.00\text{ (Margin Gap: 10.0\%)}$

---

### F02 — Discount Dependency Score

#### Core Mathematical Formula:
$$\text{Discount Dependency (\%)} = \left(\frac{\sum \text{totalDiscountsSet}}{\sum \text{subtotalPriceSet} + \sum \text{totalDiscountsSet}}\right) \times 100$$

**Tiers:** $\le 20\%$ (Healthy), $20.01\% - 30\%$ (Warning), $> 30\%$ (Excessive).

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `total_discounts` | ✅ VERIFIED | `Order.totalDiscountsSet.shopMoney.amount` | `"0.0"`, `"150.0"`, `"500.0"` |
| `current_subtotal` | ✅ VERIFIED | `Order.currentSubtotalPriceSet.shopMoney.amount` | `"370.0"`, `"350.0"`, `"0.0"` |
| `subtotal_price` | ✅ VERIFIED | `Order.subtotalPriceSet.shopMoney.amount` | `"870.0"`, `"350.0"`, `"0.0"` |
| `discount_pct` | ✅ VERIFIED | `Order.discountApplications.value.percentage` | `30` (#1010), `100` (#1011) |
| `threshold_config` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "discount_dependency_thresholds")` | JSON: `{"healthy": 20, "warning": 30}` |

#### Developer Fallback & Transformation Rules:
- **Zero Division Guard:** If gross subtotal is $\$0.00$ (100% discount promo order), set dependency to $100\%$ (Excessive).
- **Threshold Defaults:** If shop metafield is missing, default to `healthy: 20`, `warning: 30`.

#### Calculation Trace (Order #1010 - 30% Boundary Test):
- Total Discounts = $\$150.00$, Subtotal = $\$350.00 \implies \text{Original Total} = \$500.00$
- $\text{Discount Dependency} = \left(\frac{\$150.00}{\$500.00}\right) \times 100 = 30.0\% \implies \text{Warning/Borderline Excessive}$

---

### F03 — Margin Floor Breach

#### Core Mathematical Formula:
$$\text{Order Profit} = \text{currentSubtotalPriceSet} - \text{Active COGS} - \text{actual\_shipping\_cost} - \text{gateway\_fee}$$
$$\text{Breach Condition} = \text{Order Profit} < 0$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `net_revenue` | ✅ VERIFIED | `Order.currentSubtotalPriceSet.shopMoney.amount` | `"370.0"`, `"200.0"`, `"90.0"`, `"0.0"` |
| `active_cogs` | ✅ VERIFIED | $\sum (\text{inventoryItem.unitCost} \times \text{currentQuantity})$ | Excludes refunded units |
| `gateway_fee` | ⚠️ PARTIAL | `Order.transactions.fees.amount.amount` | `0.0` on manual; populated on online gateways |
| `shipping_cost` | ❌ NOT IN SHOPIFY | External 3PL Carrier Invoices / Shipping App API | Courier billed rate |

#### Developer Fallback & Transformation Rules:
- **Gateway Fee Resolution:** Sum `fees.amount.amount` for all `SUCCESS` transactions. If `fees` array is empty, default to `0.0`.
- **Active COGS Calculation:** Multiply `unitCost` strictly by `currentQuantity`. Never use unadjusted quantity.

#### Calculation Trace (Order #1011 - 100% Discount Floor Breach):
- Net Revenue = $\$0.00$, Active COGS = $\$300.00$, Shipping = $\$15.00$, Fee = $\$0.00$
- $\text{Order Profit} = \$0.00 - \$300.00 - \$15.00 - \$0.00 = -\$315.00 \implies \mathbf{BREACH\ DETECTED}$

---

### F04 — Free Shipping Leakage

#### Core Mathematical Formula:
$$\text{Uncovered Shipping} = \text{actual\_shipping\_cost} - \text{shipping\_charged}$$
$$\text{Product Profit} = \sum (\text{discountedUnitPriceSet} - \text{unitCost}) \times \text{currentQuantity}$$
$$\text{Free Shipping Leakage} = \max(0, \text{Uncovered Shipping} - \text{Product Profit})$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `is_free_shipping` | ✅ VERIFIED | `Order.shippingLines.discountedPriceSet.shopMoney.amount == "0.0"` | `true` on Order #1012 |
| `shipping_charged` | ✅ VERIFIED | `Order.shippingLines.discountedPriceSet.shopMoney.amount` | `"0.0"` |
| `selling_price` | ✅ VERIFIED | `LineItem.discountedUnitPriceSet.shopMoney.amount` | `"90.0"` |
| `cogs` | ✅ VERIFIED | `LineItem.variant.inventoryItem.unitCost.amount` | `"40.0"` |
| `weight` | ✅ VERIFIED | `inventoryItem.measurement.weight` | `value: 15, unit: "KILOGRAMS"` |
| `dimensions` | ⚙️ METAFIELD | `ProductVariant.metafield(namespace: "zeitster", key: "dimensions")` | JSON: `{"length": 50, "width": 40, "height": 30}` |
| `actual_shipping` | ❌ NOT IN SHOPIFY | External Carrier Rate / 3PL API | Courier invoice amount |

#### Developer Fallback & Transformation Rules:
- **Volumetric Weight Formula:** $\text{Volumetric (kg)} = \frac{\text{Length (cm)} \times \text{Width (cm)} \times \text{Height (cm)}}{5000}$.
- **Chargeable Weight:** $\max(\text{Physical Weight}, \text{Volumetric Weight})$. If dimensions are missing, use physical weight.

#### Calculation Trace (Order #1012 - Bulky Heavy Item D):
- Price = $\$90.00$, COGS = $\$40.00 \implies \text{Product Profit} = \$50.00$
- Shipping Charged = $\$0.00$, Weight = $15\text{ kg}$, Actual Courier Cost = $\$70.00$
- $\text{Uncovered Shipping} = \$70.00 - \$0.00 = \$70.00$
- $\text{Leakage} = \max(0, \$70.00 - \$50.00) = +\$20.00\text{ (Coverage: 71.4\%)}$

---

### F05 — Shipping Cost Recovery

#### Core Mathematical Formula:
$$\text{Shipping Recovery (Raw)} = \text{shipping\_charged} - \text{actual\_shipping\_cost}$$
$$\text{Shipping Recovery (Normalized 0–100)} = \left(\frac{\text{shipping\_charged}}{\text{actual\_shipping\_cost}}\right) \times 100$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `shipping_charged` | ✅ VERIFIED | `Order.shippingLines.discountedPriceSet.shopMoney.amount` | `"0.0"` on #1012 |
| `tracking_carrier` | ✅ VERIFIED | `Order.fulfillments.trackingInfo.company` | Tracking company name |
| `tracking_number` | ✅ VERIFIED | `Order.fulfillments.trackingInfo.number` | Key for carrier invoice join |
| `actual_shipping` | ❌ NOT IN SHOPIFY | External 3PL Invoices / Carrier API | Invoiced courier amount |

#### Developer Fallback & Transformation Rules:
- **Empty Shipping Lines:** If `shippingLines: []`, default `shipping_charged = 0.0`.
- **V1 Shipment Assumption:** $1\ \text{Order} = 1\ \text{Package}$.

#### Calculation Trace (Standard Subsidized Shipping Scenario):
- Shipping Charged = $\$5.00$, Actual Courier Cost = $\$10.00$
- $\text{Raw Recovery} = \$5.00 - \$10.00 = -\$5.00$
- $\text{Normalized Recovery Score} = \left(\frac{\$5.00}{\$10.00}\right) \times 100 = 50.0\%$

---

### F06 — Payment Fee Leakage Score

#### Core Mathematical Formula:
$$\text{Standard Benchmark Fee} = (\text{Order Amount} \times \text{standard\_fee\_pct}) + \text{standard\_fixed\_fee}$$
$$\text{Fee Variance (Loss per Order)} = \text{Actual Gateway Fee Paid} - \text{Standard Benchmark Fee}$$
$$\text{Leakage (Raw)} = \max(0, \text{Fee Variance})$$
$$\text{Normalized Fee Efficiency Score (0–100)} = \left(\frac{\text{Standard Benchmark Fee}}{\text{Actual Gateway Fee Paid}}\right) \times 100$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `order_amount` | ✅ VERIFIED | `Order.totalPriceSet.shopMoney.amount` | `"50.0"`, `"100.0"` |
| `actual_gateway_fee` | ⚠️ PARTIAL | `Order.transactions.fees.amount.amount` | `"1.75"` (Card), `"3.30"` (BNPL); null on manual orders |
| `payment_method_name` | ⚠️ PARTIAL | `Order.transactions.paymentDetails.paymentMethodName` | `"Visa"`, `"Shop Pay Installments"`, `"Klarna"` |
| `gateway_name` | ⚠️ PARTIAL | `Order.transactions.gateway` | `"shopify_payments"`, `"shop_pay_installments"` |
| `is_international_card`| ❌ EXTERNAL | External processor payload / BIN lookup | `true` / `false` |
| `standard_fee_pct` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "gateway_fee_benchmark").pct` | Default: `0.029` (2.9%) |
| `standard_fixed_fee` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "gateway_fee_benchmark").fixed` | Default: `0.30` ($0.30) |
| `high_cost_rates` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "high_cost_payment_rates")` | JSON: `{"bnpl": {"pct": 0.06, "fixed": 0.30}, "intl_card": {"pct": 0.045, "fixed": 0.30}}` |
| `is_benchmark_estimated`| 🧮 PIPELINE | Flag set to `true` when default 2.9% + $0.30 fallback is used | `true` / `false` |

#### Developer Fallback & Transformation Rules:
- **Strict Non-Silent Zero Rule on Gateway Fees:** If `actual_gateway_fee` is null (offline, COD, manual, or uncaptured orders), the score **must resolve to `Unresolved`**. NEVER default missing gateway fee to $0.00.
- **Missing Benchmark Metafield:** If merchant has no custom benchmark metafield, fall back to industry default `2.9% + $0.30` and set `is_benchmark_estimated = true`.
- **Payment Method Classification Ladder:** `paymentDetails.paymentMethodName` ⟶ infer from `gateway` (e.g. `shop_pay_installments` ⟶ `BNPL`) ⟶ `Unknown`. Longest patterns matched first to prevent substring collisions (e.g. "Shop Pay Installments" before "Shop Pay"). If unclassifiable, compute baseline leakage and flag `is_method_known = false`.
- **Asymmetric Reporting:** Order-level leakage is strictly $\max(0, \text{variance})$. Negative variance (savings on low-cost debit rails) is tracked separately in storewide rollups (`total_savings`, `net_fee_position`).

#### Calculation Trace (BNPL Worked Example):
- Order Amount = $\$50.00$, Payment Method = Shop Pay Installments (BNPL)
- Actual Gateway Fee Paid = $\$3.30$
- Standard Benchmark Fee = $(\$50.00 \times 0.029) + \$0.30 = \$1.75$
- $\text{Fee Variance} = \$3.30 - \$1.75 = +\$1.55 \text{ (Leakage)}$
- $\text{Normalized Fee Efficiency Score} = \left(\frac{\$1.75}{\$3.30}\right) \times 100 = 53.03\% \approx 53.0\% \quad (\text{Overpaying } \sim 47\% \text{ vs. Baseline})$

---

### F09 — Channel Margin Divergence


#### Core Mathematical Formula:
$$\text{Web Unit Profit} = \text{Selling Price} - \text{COGS}$$
$$\text{Marketplace Unit Profit} = \text{Selling Price} - \text{COGS} - \text{channel\_fee}$$
$$\text{Channel Divergence (Raw)} = (\text{Web Unit Profit} - \text{Marketplace Unit Profit}) \times \text{Units} = \text{channel\_fee} \times \text{Units}$$
$$\text{Normalized Score (0–100)} = \left(\frac{\text{Marketplace Unit Profit}}{\text{Web Unit Profit}}\right) \times 100$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `selling_price` | ✅ VERIFIED | `LineItem.discountedUnitPriceSet.shopMoney.amount` | `"250.0"` (#1014 Item C) |
| `cogs` | ✅ VERIFIED | `LineItem.variant.inventoryItem.unitCost.amount` | `"150.0"` |
| `units` | ✅ VERIFIED | `LineItem.currentQuantity` | `1` |
| `channel_name` | ⚠️ PARTIAL | `Order.channelInformation.channelDefinition.channelName` | Fallback: `Order.sourceName` |
| `channel_fee` | ❌ NOT IN SHOPIFY | Amazon SP-API / TikTok Seller API | Marketplace referral commission |

#### Developer Fallback & Transformation Rules:
- **Channel Name Hierarchy:** `channelInformation.channelDefinition.channelName` ⟶ `Order.sourceName` ⟶ `"Direct Web"`.
- If `channel_name == "web"`, set `channel_fee = 0.0`.

#### Calculation Trace (Order #1014 Item C on Amazon with 15% Fee):
- Price = $\$250.00$, COGS = $\$150.00 \implies \text{Web Unit Profit} = \$100.00$
- Amazon Fee (15%) = $\$37.50 \implies \text{Marketplace Unit Profit} = \$62.50$
- $\text{Raw Divergence} = (\$100.00 - \$62.50) \times 1 = +\$37.50/\text{unit}$
- $\text{Normalized Score} = \left(\frac{\$62.50}{\$100.00}\right) \times 100 = 62.5\%$

---

### F10 — Product Contribution

#### Core Mathematical Formula:
$$\text{Line Revenue Share} = \frac{\text{Line Net Revenue}}{\sum \text{Active Subtotal}}$$
$$\text{Allocated Shipping} = \text{actual\_shipping\_cost} \times \text{Line Revenue Share}$$
$$\text{Allocated Gateway Fee} = \text{gateway\_fee} \times \text{Line Revenue Share}$$
$$\text{SKU Contribution} = \text{Line Net Revenue} - \text{Line Active COGS} - \text{Allocated Shipping} - \text{Allocated Gateway Fee}$$
$$\text{Normalized Contribution Score (0–100)} = \max\left(0, \left(\frac{\text{SKU Contribution}}{\text{Line Net Revenue}}\right) \times 100\right)$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `product_id` | ✅ VERIFIED | `LineItem.product.id` | `gid://shopify/Product/9581863141615` |
| `sku` | ⚠️ PARTIAL | `LineItem.sku` | Returns `null`; fallback to `variant.id` / `product.id` |
| `line_net_revenue` | ✅ VERIFIED | `LineItem.discountedUnitPriceSet` $\times$ `currentQuantity` | Item C: `"$250.0"`, Item E: `"$120.0"` |
| `line_cogs` | ✅ VERIFIED | `inventoryItem.unitCost.amount` $\times$ `currentQuantity` | Item C: `"$150.0"`, Item E: `"$80.0"` |
| `line_refund` | ✅ VERIFIED | `Order.refunds.refundLineItems.subtotalSet.shopMoney.amount` | `"$500.0"` refunded on Item A |
| `allocated_shipping` | 🧮 PIPELINE | $\text{actual\_shipping\_cost} \times \text{Line Revenue Share}$ | Derived in scoring engine |
| `allocated_fee` | 🧮 PIPELINE | $\text{gateway\_fee} \times \text{Line Revenue Share}$ | Derived in scoring engine |

#### Developer Fallback & Transformation Rules:
- **SKU Fallback:** `LineItem.sku` ⟶ `LineItem.variant.id` ⟶ `LineItem.product.id`.
- **Allocation Denominator:** Allocate order costs only across active retained items (`currentQuantity > 0`).

#### Calculation Trace (Order #1014 Post-Return Allocation):
- Retained Subtotal = $\$370.00$ (Item C = $\$250$, Item E = $\$120$). Item A refunded.
- Item C Share = $\frac{\$250}{\$370} = 67.57\%$ | Item E Share = $\frac{\$120}{\$370} = 32.43\%$.
- Allocated Shipping ($\$20.00$ total) = Item C: $\$13.51$, Item E: $\$6.49$.
- Allocated Gateway Fee ($\$11.10$ total) = Item C: $\$7.50$, Item E: $\$3.60$.
- Item C Contribution: $\$250.00 - \$150.00 - \$13.51 - \$7.50 = +\$78.99\text{ (Score: 31.60\%)}$
- Item E Contribution: $\$120.00 - \$80.00 - \$6.49 - \$3.60 = +\$29.91\text{ (Score: 24.93\%)}$
- Item A (Refunded): $\$0.00\text{ (Score: 0.0\%)}$

---

### F11 — Order Profitability

#### Core Mathematical Formula:
$$\text{Expected Refund Cost} = \text{Total Received} \times 0.05\ (\text{Approved 5\% Fallback Provision})$$
$$\text{Order Profitability} = \text{Total Received} - \text{Total Refunded} - \text{Active COGS} - \text{Shipping} - \text{Gateway Fee} - \text{Expected Refund Cost}$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `total_received` | ✅ VERIFIED | `Order.totalReceivedSet.shopMoney.amount` | `"870.0"`, `"700.0"`, `"90.0"`, `"350.0"` |
| `total_refunded` | ✅ VERIFIED | `Order.totalRefundedSet.shopMoney.amount` | `"500.0"` (#1014), `"0.0"` |
| `active_cogs` | ✅ VERIFIED | $\sum (\text{inventoryItem.unitCost} \times \text{currentQuantity})$ | $\$150 + \$80 = \$230.0$ (#1014) |
| `shipping_cost` | ❌ NOT IN SHOPIFY | External 3PL Invoices / Carrier API | Invoiced courier amount |
| `gateway_fee` | ⚠️ PARTIAL | `Order.transactions.fees.amount.amount` | `0.0` on manual; live on online gateways |
| `expected_refund` | 🧮 PIPELINE | $\text{Retained Revenue} \times 0.05$ | Statistical provision in ETL |

#### Developer Fallback & Transformation Rules:
- Use `totalReceivedSet` to verify captured funds.
- Keep the 5% refund provision parameter configurable in pipeline settings.

#### Calculation Trace (Order #1014):
- Retained Cash = $\$870.00 - \$500.00 = \$370.00$
- Active COGS = $\$230.00$, Shipping = $\$20.00$, Gateway Fee = $\$11.10$
- $\text{Expected Refund Cost (5\%)} = \$370.00 \times 0.05 = \$18.50$
- $\text{Order Profitability} = \$370.00 - \$230.00 - \$20.00 - \$11.10 - \$18.50 = +\$90.40\text{ (Net Margin: 24.43\%)}$

---

### F12 — Revenue Quality Score

#### Core Mathematical Formula:
$$\text{Net Retained Revenue} = \text{Gross Revenue} - \text{Total Refunded} - \text{Chargebacks} - \text{F01/F04/F05 Leakages}$$
$$\text{Revenue Quality Score (\%)} = \left(\frac{\text{Net Retained Revenue}}{\text{Gross Revenue}}\right) \times 100$$

#### Data Mapping:
| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `gross_revenue` | ✅ VERIFIED | `Order.totalPriceSet.shopMoney.amount` | `"870.0"`, `"700.0"`, `"90.0"`, `"350.0"` |
| `refunds` | ✅ VERIFIED | `Order.totalRefundedSet.shopMoney.amount` | `"500.0"` (#1014), `"0.0"` |
| `chargebacks` | ✅ VERIFIED | `Order.disputes` | `[]` (Empty on test orders) |
| `leakage_sum` | 🧮 PIPELINE | Rollup sum of outputs from F01, F04, F05 | Derived in ETL |

#### Developer Fallback & Transformation Rules:
- Sum dispute amounts where `Order.disputes.status` is `NEEDS_RESPONSE`, `UNDER_REVIEW`, or `LOST`.
- If `gross_revenue == 0`, return Revenue Quality = `0.0%`.

#### Calculation Trace (Order #1014 with Real-World Deductions):
- Gross Revenue = $\$870.00$, Refunds = $\$500.00$
- Promo Leakage (F01) = $\$25.00$, Shipping Deficit (F05) = $\$20.00$
- $\text{Net Retained Revenue} = \$870.00 - \$500.00 - \$25.00 - \$20.00 = \$325.00$
- $\text{Revenue Quality Score} = \left(\frac{\$325.00}{\$870.00}\right) \times 100 = 37.36\%\text{ (Health: 🔴 High Return Attrition)}$

---



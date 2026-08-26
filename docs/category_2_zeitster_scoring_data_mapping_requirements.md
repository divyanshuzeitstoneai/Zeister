# Zeitster — Category 2: Fraud, Returns & Disputes
## Phase 4: Production Data Mapping & WebDev Alignment Specification

### Document Navigation (Outline)
- [1. Status Legend & Field Classification](#1-status-legend--field-classification)
- [2. Consolidated Executive Summary (Expected Outputs Matrix)](#2-consolidated-executive-summary-expected-outputs-matrix)
- [3. Formula Detailed Mapping & Logic](#3-formula-detailed-mapping--logic)
  - [R10 — Fraud Loss Impact Score](#r10--fraud-loss-impact-score)
- [4. Master GraphQL Ingestion Query](#4-master-graphql-ingestion-query)
- [5. Metafields & External Ingestion Stubs](#5-metafields--external-ingestion-stubs)

---

## 1. Status Legend & Field Classification

| Status Tag | Classification | Description |
|---|---|---|
| ✅ **SHOPIFY — VERIFIED** | Verified Field | Natively present in Shopify Admin GraphQL, verified live against real test orders, and accessible directly via standard query paths. |
| ⚠️ **SHOPIFY — PARTIAL** | Conditional Field | Exists in Shopify GraphQL but requires live payment gateways (e.g., Shopify Payments / Stripe for transaction fees), specific API scopes (`read_inventory`), or returns null on manual test orders. |
| ⚙️ **SHOPIFY — METAFIELD / CONFIG** | Configuration Metafield | Business configuration parameters not generated during customer checkout. Must be provisioned as Shop-level or ProductVariant-level Metafields. |
| ❌ **NOT IN SHOPIFY / EXTERNAL** | External Data Source | Completely absent from Shopify Admin GraphQL. Ingested via external systems (3PL Courier APIs, carrier invoice CSV imports, Helpdesk logs, FX rate feeds). |
| 🧮 **PIPELINE / DERIVED** | ETL Computed Metric | Statistical, predictive, or allocation-weighted metric computed within the backend ETL scoring engine by combining multiple raw fields. |

---

## 2. Consolidated Executive Summary (Expected Outputs Matrix)

| Metric | Business Indicator | Logic & Core Calculation | Raw Output | Normalized / Tier Output | Business Health State |
|---|---|---|---|---|---|
| **R10** | Fraud Loss Impact Score | $\min\left(100.0, \left(\frac{\text{Total Monetary Fraud Loss}}{\text{Gross Order Revenue}}\right) \times 100\right)$ | `+$178.00 Loss` on `$115.00 Rev` | `100.0% (Capped)` | 🔴 Critical Fraud Sunk Loss |

---

## 3. Formula Detailed Mapping & Logic

### R10 — Fraud Loss Impact Score

#### Core Mathematical Formula:

$$\text{Total Monetary Fraud Loss} = \sum_{k=1}^{10} \text{Loss Component}_k$$

$$\begin{aligned}
\text{Total Monetary Fraud Loss} = &\quad \text{Order Refund Amount} \\
&+ \text{Bank Chargeback Penalty Fee} \\
&+ \text{Product Sourcing Cost (COGS)} \\
&+ \text{Outbound Shipping Fee} \\
&+ \text{Packaging Material Cost} \\
&+ \text{Warehouse Fulfillment Labor Cost} \\
&+ \text{Unrefunded Payment Gateway Fee} \\
&+ \text{Unrefunded Platform Fee} \\
&+ \text{Customs Clearance / COD Fee} \\
&+ \text{Customer Support Dispute Handling Cost}
\end{aligned}$$

$$\text{Gross Order Revenue} = \text{Item Selling Price after discounts} + \text{Customer-Paid Shipping} + \text{Customer-Paid Taxes}$$

$$\text{R10 Score} = \begin{cases} 
100.00 & \text{if } \text{Gross Order Revenue} = 0 \text{ and } \text{Total Monetary Fraud Loss} > 0 \\
0.00 & \text{if } \text{Gross Order Revenue} = 0 \text{ and } \text{Total Monetary Fraud Loss} = 0 \\
\min\left(100.0, \left(\frac{\text{Total Monetary Fraud Loss}}{\text{Gross Order Revenue}}\right) \times 100\right) & \text{otherwise}
\end{cases}$$

---

#### Data Mapping:

| Variable Name | Status | Exact Source Path | Test Value / Schema Type |
|---|---|---|---|
| `fulfillment_status` | ✅ VERIFIED | `Order.displayFulfillmentStatus` | `"FULFILLED"`, `"PARTIALLY_FULFILLED"` |
| `dispute_status` | ⚠️ PARTIAL | `Order.disputes.status` | `"CHARGEBACK_OPENED"`, `"CHARGEBACK_LOST"`, `"NEEDS_RESPONSE"` |
| `disputed_amount` | ⚠️ PARTIAL | `Order.disputes.amountSet.shopMoney.amount` | `"100.0"`, `"50.0"` |
| `item_net_price` | ✅ VERIFIED | `LineItem.discountedTotalSet.shopMoney.amount` | `"100.0"`, `"200.0"` |
| `customer_shipping` | ✅ VERIFIED | `Order.shippingLines.discountedPriceSet.shopMoney.amount` | `"10.0"`, `"0.0"` |
| `customer_tax` | ✅ VERIFIED | `Order.totalTaxSet.shopMoney.amount` | `"5.0"`, `"0.0"` |
| `refund_amount` | ✅ VERIFIED | `Order.refunds.totalRefundedSet.shopMoney.amount` | `"100.0"`, `"0.0"` |
| `native_chargeback_fee` | ⚠️ PARTIAL | `Order.disputes.fee.amount` | `"15.0"` (Shopify Payments); `null` on manual |
| `cogs` | ✅ VERIFIED | `LineItem.variant.inventoryItem.unitCost.amount` | `"40.0"`, `"80.0"`; `null` if unpopulated |
| `category_avg_cogs` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "category_avg_cogs")` | JSON: `{"fashion": 35.0, "electronics": 120.0}` |
| `actual_shipping_cost` | ❌ NOT IN SHOPIFY | External 3PL Courier API (Shiprocket / EasyPost) | Invoiced courier amount |
| `shipping_country` | ✅ VERIFIED | `Order.shippingAddress.countryCodeV2` | `"US"`, `"CA"`, `"GB"` |
| `packaging_config` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "packaging_cost_model")` | JSON: `{"rate": 0.02, "min": 0.50, "max": 5.00}` |
| `labor_config` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "labor_cost_model")` | JSON: `{"rate": 0.03, "min": 1.00, "max": 10.00}` |
| `gateway_fee` | ⚠️ PARTIAL | `Order.transactions.fees.amount.amount` | `"2.50"` (Shopify Payments); `0.0` on manual |
| `platform_fee_rate` | ⚙️ METAFIELD | `Shop.metafield(namespace: "zeitster", key: "platform_fee_rate")` | Float: `0.025` (2.5%) |
| `customs_cod_fee` | ❌ NOT IN SHOPIFY | External Carrier Customs Entry Invoice | Invoiced cross-border fee |
| `support_dispute_cost` | ❌ NOT IN SHOPIFY | Helpdesk Worklog (Zendesk / Gorgias API) | Ticket labor cost |
| `fx_rate` | ❌ NOT IN SHOPIFY | Daily FX Rate Feed (OpenExchangeRates) | FX to USD on `Order.createdAt` |
| `dispute_value_ratio` | 🧮 PIPELINE | $\min\left(1.0, \frac{\text{disputed\_amount}}{\text{item\_net\_price}}\right)$ | Derived in scoring engine |
| `total_fraud_loss` | 🧮 PIPELINE | $\sum_{k=1}^{10} \text{Loss Component}_k$ | Derived in scoring engine |

---

#### Developer Fallback & Transformation Rules:

1. **Eligibility Filter:**
   - Only process orders where `fulfillment_status` is `FULFILLED` or `PARTIALLY_FULFILLED` (mapping to `SHIPPED` / `DELIVERED`).
   - Payment dispute status must strictly match `CHARGEBACK_OPENED`, `CHARGEBACK_LOST`, `NEEDS_RESPONSE`, `UNDER_REVIEW`, or `FRAUD_REFUND`. Unfulfilled or won dispute orders evaluate to $\text{Score} = 0.0, \text{Eligible} = \text{False}$.
2. **Missing COGS Ladder:**
   - If `inventoryItem.unitCost == null`, fall back to `Shop.metafield(namespace: "zeitster", key: "category_avg_cogs")[productType]`. If category is unlisted, default to `0.00`.
3. **Missing Chargeback Penalty Fee Fallback:**
   - If `Dispute.fee == null`, look up currency-specific fallback:
     - `USD`: $\$15.00$
     - `CAD`: $\$20.00$
     - `EUR`: $€15.00$
     - `GBP`: $£10.00$
     - All other currencies: $\$15.00\text{ USD}$ equivalent.
4. **Missing Outbound Courier Shipping Fallback:**
   - If external 3PL carrier invoice is unavailable:
     - `Domestic` (`shippingAddress.countryCodeV2 == shop.countryCode`): $5\%$ of item net price.
     - `International` (`shippingAddress.countryCodeV2 != shop.countryCode`): $15\%$ of item net price.
5. **Missing Packaging Material Cost:**
   - Calculate $2\%$ of item net price clamped to $[\min=\$0.50, \max=\$5.00]$.
6. **Missing Warehouse Fulfillment Labor Cost:**
   - Calculate $3\%$ of item net price clamped to $[\min=\$1.00, \max=\$10.00]$.
7. **Missing Payment Gateway & Platform Fees:**
   - Gateway Fee: If `transactions.fees` is empty, calculate $2.5\%$ of disputed amount.
   - Platform Fee: Calculate $2.5\%$ of disputed amount using `platform_fee_rate`.
8. **Missing Customer Support Dispute Cost:**
   - Default to $\$0.00$ unless an explicit worklog entry is present in `support_dispute_logs`.
9. **Missing Customs / COD Fee:**
   - Default to $\$0.00$ baseline and flag `clarification_required = true` in pipeline audit record.
10. **Partial Dispute Proration Rules:**
    - Variable Components (Refund, COGS, Courier Shipping, Gateway Fee) are scaled by `dispute_value_ratio` ($r = \text{Disputed Amount} / \text{Item Net Price}$).
    - Fixed Components (Bank Chargeback Penalty Fee, Customer Support Cost) are retained at 100% full-order value.
    - Packaging, Labor, Platform Fee, and Customs are retained at baseline full order level pending final business specification.
11. **Currency Normalization:**
    - Normalize all revenue and loss components to base currency (USD) using the exchange rate on `Order.createdAt`.
12. **Idempotency & Deduplication:**
    - Deduplicate multiple webhook deliveries for the same `dispute_id` and `refund_id` to ensure penalty fees and refunds are not double-counted.

---

#### Calculation Trace (Order #ORD-SYN-01 — Standard Fraud Order):

- **Gross Revenue Components:**
  - Net Selling Price = $\$100.00$, Customer Shipping = $\$10.00$, Customer Taxes = $\$5.00$
  - $\text{Gross Order Revenue} = \$100.00 + \$10.00 + \$5.00 = \$115.00$
- **Loss Vector Breakdown (10 Components):**
  1. Refund = $\$100.00$
  2. Bank Chargeback Fee = $\$15.00$
  3. Product COGS = $\$40.00$
  4. Outbound Shipping = $\$8.00$
  5. Packaging Material = $\$2.00$
  6. Warehouse Labor = $\$3.00$
  7. Gateway Fee = $\$2.50$
  8. Platform Fee = $\$2.50$
  9. Customs / COD = $\$0.00$
  10. Customer Support = $\$5.00$
- $\text{Total Monetary Fraud Loss} = \$100 + \$15 + \$40 + \$8 + \$2 + \$3 + \$2.50 + \$2.50 + \$0 + \$5 = \$178.00$
- $\text{Raw Risk Score} = \left(\frac{\$178.00}{\$115.00}\right) \times 100 = 154.78\%$
- $\text{Final R10 Score} = \min(100.0, 154.78) = \mathbf{100.00\%}\text{ (🔴 Critical Sunk Fraud Loss)}$

---

## 4. Master GraphQL Ingestion Query

This paginated Admin GraphQL query (`2024-10`) extracts all fields required for R10:

```graphql
query IngestOrdersForFraudScoring($cursor: String) {
  orders(first: 50, after: $cursor, reverse: true) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        createdAt
        currencyCode
        displayFulfillmentStatus
        shippingAddress {
          countryCodeV2
        }
        totalPriceSet {
          shopMoney { amount currencyCode }
        }
        totalTaxSet {
          shopMoney { amount currencyCode }
        }
        totalRefundedSet {
          shopMoney { amount currencyCode }
        }
        shippingLines(first: 5) {
          edges {
            node {
              discountedPriceSet {
                shopMoney { amount currencyCode }
              }
            }
          }
        }
        disputes(first: 5) {
          id
          status
          amountSet {
            shopMoney { amount currencyCode }
          }
          fee {
            amount
            currencyCode
          }
        }
        transactions(first: 10) {
          id
          status
          fees {
            amount {
              amount
              currencyCode
            }
          }
        }
        refunds {
          id
          note
          totalRefundedSet {
            shopMoney { amount currencyCode }
          }
        }
        lineItems(first: 50) {
          edges {
            node {
              id
              quantity
              currentQuantity
              discountedTotalSet {
                shopMoney { amount currencyCode }
              }
              product {
                productType
                category {
                  name
                }
              }
              variant {
                id
                sku
                inventoryItem {
                  unitCost {
                    amount
                    currencyCode
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

---

## 5. Metafields & External Ingestion Stubs

### 5.1 Shop-Level Configuration Metafields

```graphql
mutation ConfigureFraudScoringParameters($shopId: ID!) {
  metafieldsSet(metafields: [
    {
      ownerId: $shopId
      namespace: "zeitster"
      key: "chargeback_fallbacks"
      type: "json"
      value: "{\"USD\": 15.00, \"EUR\": 15.00, \"GBP\": 10.00, \"CAD\": 20.00}"
    },
    {
      ownerId: $shopId
      namespace: "zeitster"
      key: "packaging_cost_model"
      type: "json"
      value: "{\"rate\": 0.02, \"min\": 0.50, \"max\": 5.00}"
    },
    {
      ownerId: $shopId
      namespace: "zeitster"
      key: "labor_cost_model"
      type: "json"
      value: "{\"rate\": 0.03, \"min\": 1.00, \"max\": 10.00}"
    },
    {
      ownerId: $shopId
      namespace: "zeitster"
      key: "shipping_fallbacks"
      type: "json"
      value: "{\"domestic\": 0.05, \"international\": 0.15}"
    },
    {
      ownerId: $shopId
      namespace: "zeitster"
      key: "platform_fee_rate"
      type: "number_decimal"
      value: "0.025"
    },
    {
      ownerId: $shopId
      namespace: "zeitster"
      key: "category_avg_cogs"
      type: "json"
      value: "{\"fashion\": 35.00, \"apparel\": 35.00, \"electronics\": 120.00, \"accessories\": 15.00}"
    }
  ]) {
    userErrors {
      field
      message
    }
  }
}
```

### 5.2 External Ingestion Database Tables

```sql
-- 1. Actual Logistics Shipping Costs (3PL Courier Invoices)
CREATE TABLE order_logistics_costs (
    order_id VARCHAR(64) PRIMARY KEY,
    tracking_number VARCHAR(128),
    carrier_name VARCHAR(64),
    actual_shipping_cost_usd DECIMAL(12, 4) NOT NULL,
    invoiced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Customer Support Worklogs (Helpdesk Dispute Management Costs)
CREATE TABLE support_dispute_logs (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL,
    dispute_id VARCHAR(64),
    agent_handling_cost_usd DECIMAL(12, 4) NOT NULL,
    ticket_id VARCHAR(64),
    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Daily Currency Exchange Rates Feed
CREATE TABLE currency_exchange_rates (
    currency_code VARCHAR(3) NOT NULL,
    rate_date DATE NOT NULL,
    rate_to_usd DECIMAL(10, 6) NOT NULL,
    PRIMARY KEY (currency_code, rate_date)
);

-- 4. R10 Score Outputs & Audit Rollup
CREATE TABLE r10_scoring_outputs (
    order_id VARCHAR(64) PRIMARY KEY,
    is_eligible BOOLEAN NOT NULL,
    gross_order_revenue_usd DECIMAL(12, 4) NOT NULL,
    total_monetary_fraud_loss_usd DECIMAL(12, 4) NOT NULL,
    raw_risk_score DECIMAL(8, 4) NOT NULL,
    final_r10_score DECIMAL(6, 2) NOT NULL,
    loss_breakdown_json JSONB NOT NULL,
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 5.3 Metafield Write-Back Mutation (Write-Path)

```graphql
mutation WriteBackR10Score($orderId: ID!, $r10Score: Float!, $fraudLoss: Float!, $breakdownJson: String!) {
  metafieldsSet(metafields: [
    {
      ownerId: $orderId
      namespace: "zeitster_scoring"
      key: "r10_fraud_loss_score"
      type: "number_decimal"
      value: $r10Score
    },
    {
      ownerId: $orderId
      namespace: "zeitster_scoring"
      key: "total_monetary_fraud_loss"
      type: "number_decimal"
      value: $fraudLoss
    },
    {
      ownerId: $orderId
      namespace: "zeitster_scoring"
      key: "loss_breakdown"
      type: "json"
      value: $breakdownJson
    }
  ]) {
    userErrors {
      field
      message
    }
  }
}
```

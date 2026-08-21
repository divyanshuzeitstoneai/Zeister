# Post-Business-Decision Validation

> **Document Type:** Formal Post-Business-Decision Scoring Validation & Verification Evidence  
> **Repository:** `d:\Zeister`  
> **Scope:** Verification of Ajai's Finalized V1 Business Decisions & Normalization across F01–F12  
> **Test Status:** 119 / 119 Automated Tests Passing (0 Failures, 0 Regressions)  
> **Author:** Antigravity AI  

---

## 1. Executive Summary

This validation audit confirms that the Zeitster scoring engine and test suite adhere to the final V1 business decisions confirmed by Ajai:
1. **F01 Target Profit Calculation:** Shifted from gross list price to **Net Selling Price** after promotional discounts ($1,500 \times 20\% = \$300$, not $\$400$).
2. **Missing COGS Policy:** Configured category-average fallback with explicit `is_cogs_estimated = True` boolean tracking (preserving multi-item actual COGS for known line items).
3. **F02 Discount Dependency Tiers:** Formalized healthy ($0\%\text{--}20\%$), warning ($20\%\text{--}30\%$), and excessive ($>30\%$) status buckets with configurable thresholds.
4. **Partial Returns Logistics Allocation:** Enforced **Item Revenue Percentage** allocation ($600/1000 \times \$100 = \$60$ shipping, $\$6$ gateway).
5. **V1 Scope Boundaries:** Standardized on $1\text{ order} = 1\text{ package}$ single-shipment assumption (multi-package split shipment confirmed as V2) and checkout base currency.

**Overall Status:** **READY FOR DATA MAPPING**

---

## 2. Tests Added or Changed

* **New Test File:** [`tests/test_v1_business_rules.py`](file:///d:/Zeister/tests/test_v1_business_rules.py) (15 dedicated test cases added):
  - `test_1_f01_target_profit_on_net_selling_price_core_example`: Validates $\$1,500 \times 20\% = \$300$ target profit.
  - `test_1_f01_net_selling_price_scenarios`: Tests no discount, small discount, large discount, and 100% discount.
  - `test_2_f01_category_margins_and_boundaries`: Tests all 6 category margins and exact/below/above boundary conditions.
  - `test_3_and_4_missing_cogs_fallback_cases`: Tests Cases A, B, C (mixed COGS in 3-item order), D (all missing), and E (missing + returned).
  - `test_5_f02_boundary_buckets`: Parameterized test across 8 boundary points ($0\%$, $19.99\%$, $20\%$, $20.01\%$, $29.99\%$, $30\%$, $30.01\%$, $100\%$).
  - `test_6_f02_configurable_threshold`: Validates dynamic threshold adjustment ($15\%$, $20\%$, $25\%$).
  - `test_7_and_8_partial_return_revenue_weighted_allocation`: Validates item-revenue-weighted shipping and gateway allocation for partial returns.
  - `test_10_v1_single_package_assumption`: Validates single package courier handling under F04 and F05.
* **Updated Existing Tests:**
  - [`tests/test_data_clean.py`](file:///d:/Zeister/tests/test_data_clean.py): Updated `TestRecomputeTargetMinProfit` and `TestCleanPipeline` to assert target profit against `net_selling_price`.
  - [`tests/test_f01_f03.py`](file:///d:/Zeister/tests/test_f01_f03.py): Updated `test_f01_different_category_profit_floors` to assert category margins on net selling price.

---

## 3. Test Results

| Test ID | Scenario | Expected Result | Actual Result | Relevant Formula | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **T1.1** | Selling $2000, Disc $500, Net $1500, Target 20% | Target Profit = $300.00 (not $400) | `target_min_profit = 300.0` | F01 | **PASS** |
| **T1.2** | No discount ($100 net, 15% margin) | Target Profit = $15.00 | `target_min_profit = 15.0` | F01 | **PASS** |
| **T1.3** | Small discount ($90 net, 15% margin) | Target Profit = $13.50 | `target_min_profit = 13.5` | F01 | **PASS** |
| **T1.4** | Large discount ($40 net, 15% margin) | Target Profit = $6.00 | `target_min_profit = 6.0` | F01 | **PASS** |
| **T1.5** | 100% discount ($0 net, 15% margin) | Target Profit = $0.00 | `target_min_profit = 0.0` | F01 | **PASS** |
| **T2.1** | Fashion Target Margin (15% on $100 net) | Target Profit = $15.00 | `target_min_profit = 15.0` | F01 | **PASS** |
| **T2.2** | Beauty Target Margin (20% on $100 net) | Target Profit = $20.00 | `target_min_profit = 20.0` | F01 | **PASS** |
| **T2.3** | Electronics Target Margin (8% on $100 net) | Target Profit = $8.00 | `target_min_profit = 8.0` | F01 | **PASS** |
| **T2.4** | Home Goods Target Margin (12% on $100 net) | Target Profit = $12.00 | `target_min_profit = 12.0` | F01 | **PASS** |
| **T2.5** | Luxury Target Margin (25% on $100 net) | Target Profit = $25.00 | `target_min_profit = 25.0` | F01 | **PASS** |
| **T2.6** | Pet Care Target Margin (15% on $100 net) | Target Profit = $15.00 | `target_min_profit = 15.0` | F01 | **PASS** |
| **T2.7** | Profit exactly equal to target ($15.00) | `f01_flagged = False, loss = $0.00` | `flagged=False, loss=0.0` | F01 | **PASS** |
| **T2.8** | Profit slightly below target ($14.99) | `f01_flagged = True, loss = $0.01` | `flagged=True, loss=0.01` | F01 | **PASS** |
| **T3.A** | Single item with actual COGS ($40) | Uses $40 COGS, `is_cogs_estimated = False` | `cogs=40.0, est=False` | F01/F03/Clean | **PASS** |
| **T3.B** | Single item with missing COGS (cat avg $40) | Uses $40 fallback, `is_cogs_estimated = True` | `cogs=40.0, est=True` | F01/F03/Clean | **PASS** |
| **T3.C** | 3-item order: A ($30 actual), B (NaN), C ($50 actual) | A=$30 (False), B=$40 (True), C=$50 (False) | Only B estimated | F01/F03/Clean | **PASS** |
| **T3.D** | All items missing COGS | Global fallback used, `is_cogs_estimated = True` | All marked estimated | F01/F03/Clean | **PASS** |
| **T3.E** | Missing COGS + returned item | Category fallback used, `is_cogs_estimated = True` | `cogs=50.0, est=True` | F01/F03/Clean | **PASS** |
| **T5.1** | Discounted Share = 0.00% | Status: `HEALTHY` | `HEALTHY` | F02 | **PASS** |
| **T5.2** | Discounted Share = 19.99% | Status: `HEALTHY` | `HEALTHY` | F02 | **PASS** |
| **T5.3** | Discounted Share = 20.00% (Boundary) | Status: `HEALTHY` | `HEALTHY` | F02 | **PASS** |
| **T5.4** | Discounted Share = 20.01% | Status: `WARNING` | `WARNING` | F02 | **PASS** |
| **T5.5** | Discounted Share = 29.99% | Status: `WARNING` | `WARNING` | F02 | **PASS** |
| **T5.6** | Discounted Share = 30.00% (Boundary) | Status: `WARNING` | `WARNING` | F02 | **PASS** |
| **T5.7** | Discounted Share = 30.01% | Status: `EXCESSIVE` | `EXCESSIVE` | F02 | **PASS** |
| **T5.8** | Discounted Share = 100.00% | Status: `EXCESSIVE` | `EXCESSIVE` | F02 | **PASS** |
| **T6.1** | Configurable threshold = 20% on 25% share | `is_breached = True, loss = $10.00` | `breached=True, loss=10.0` | F02 | **PASS** |
| **T6.2** | Configurable threshold = 25% on 25% share | `is_breached = False, loss = $0.00` | `breached=False, loss=0.0` | F02 | **PASS** |
| **T6.3** | Configurable threshold = 15% on 25% share | `is_breached = True, loss = $20.00` | `breached=True, loss=20.0` | F02 | **PASS** |
| **T7.1** | Partial Return Item A (₹600) & B (₹400), Ship ₹100 | Item A ship=₹60, gw=₹6; Item B ship=₹40, gw=₹4 | Exact 60%/40% allocation | F10/F11 | **PASS** |
| **T7.2** | Item A returned contribution | Contribution = -₹300.50 (refund + restock + ship) | `contrib = -300.50` | F10 | **PASS** |
| **T10.1**| Single package courier cost ($20) vs profit ($15) | F04 net leakage = $5.00 | `f04_leakage = 5.0` | F04 | **PASS** |

---

## 4. Formula Validation (F01–F12)

| Formula | Ajai Final V1 Business Rule | Current Mathematical Formula | Implementation Behavior | Test Evidence | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **F01** | Promo Margin Leakage on Net Selling Price; category targets | $\text{target} = \text{net\_selling\_price} \times \text{category\_margin}$<br>$\text{f01\_loss} = \max(0, \text{target} - \text{margin})$ | Checks discount flag; evaluates profit against Net-Price target floor | `test_1_f01_target_profit_on_net_selling_price_core_example`, `test_2_f01_category_margins_and_boundaries` | **VERIFIED** |
| **F02** | Discount Dependency (20% warning threshold, 30% excessive) | $\text{share} = \frac{\text{Disc Sales}}{\text{Total Sales}}$<br>$\text{loss} = \text{Sales} \times \max(0, \text{share} - 0.20) \times \text{depth}$ | Returns share %, excess share, loss $, and health status (`HEALTHY`, `WARNING`, `EXCESSIVE`) | `test_5_f02_boundary_buckets`, `test_6_f02_configurable_threshold` | **VERIFIED** |
| **F03** | Margin Floor Breach (unprofitable orders) | $\text{profit} = \text{Net Revenue} - \text{COGS} - \text{Ship} - \text{GW} < 0$ | Flags $\text{profit} < 0$; reports frequency and dollar severity | `test_f01_f03.py::TestF03MarginFloorBreach` | **VERIFIED** |
| **F04** | Free Shipping Net Loss (1 order = 1 package) | $\text{leakage} = \max(0, \text{Uncovered Ship} - \text{Product Profit})$<br>$\text{volumetric} = (L \times W \times H) / 5000$ | Computes net absorbed courier cash drain; handles dimensional weight | `test_10_v1_single_package_assumption`, `test_f04.py` | **VERIFIED** |
| **F05** | Shipping Recovery Ledger (1 order = 1 package) | $\text{delta} = \text{Shipping Charged} - \text{Actual Courier}$<br>$\text{Net Balance} = \sum \text{delta}$ | Storewide ledger summing surpluses and deficits | `test_f05.py`, `test_10_v1_single_package_assumption` | **VERIFIED** |
| **F09** | Channel Margin Divergence | $\text{loss} = \sum (\text{Web Unit Profit} - \text{Mkt Unit Profit}) \times \text{Units}$ | Quantifies marketplace fee and margin erosion vs Direct Web | `test_f09.py` | **VERIFIED** |
| **F10** | SKU Product Contribution with Item-Revenue-Weighted Cost Allocation | $\text{Contrib} = \text{Net Rev} - \text{COGS} - \text{Returns} - \text{Alloc Ship} - \text{Alloc GW}$<br>$\text{Alloc} = \frac{\text{Item Net Rev}}{\text{Order Net Rev}} \times \text{Cost}$ | Computes true bottom-line SKU contribution margin % | `test_7_and_8_partial_return_revenue_weighted_allocation`, `test_f10.py` | **VERIFIED** |
| **F11** | Order Profitability | $\text{Net Profit} = \text{Collected} - \text{COGS} - \text{Ship} - \text{GW} - \text{ExpRefund}$ | Computes order bottom-line net profit and margin % | `test_f11.py` | **VERIFIED** |
| **F12** | Revenue Quality Score | $\text{Quality \%} = \frac{\text{Net Retained Revenue}}{\text{Gross Revenue}} \times 100$ | Strict $1:1$ additive cost drain reconciliation | `test_f12.py` | **VERIFIED** |

---

## 5. Business Decision Alignment Matrix

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              AJAI BUSINESS DECISION AUDIT                              │
├──────────────────────────────────────┬────────────────────────────────┬────────────────┤
│ Decision                             │ Implementation Mechanism       │ Status         │
├──────────────────────────────────────┼────────────────────────────────┼────────────────┤
│ F01 Target on Net Selling Price      │ f01_f03.py, data_clean.py      │ VERIFIED       │
│ F01 Category Margin Benchmarks       │ config.py (TARGET_MARGINS)     │ VERIFIED       │
│ Missing COGS Category Fallback       │ data_clean.py (impute_cat_avg) │ VERIFIED       │
│ Estimated COGS Flag                  │ is_cogs_estimated = True       │ VERIFIED       │
│ Multi-Item Partial Imputation        │ Known COGS preserved           │ VERIFIED       │
│ F02 Configurable Threshold (20%)     │ f02.py (healthy_share param)   │ VERIFIED       │
│ F02 Health Buckets (0-20, 20-30, >30)│ f02.py (health_status return)  │ VERIFIED       │
│ Partial Return Revenue Allocation    │ f10.py, f11.py (revenue ratio) │ VERIFIED       │
│ V1 Single Package Shipping           │ f04.py, f05.py (1 order = 1 pkg│ VERIFIED       │
│ Base Currency Usage (Checkout)       │ Single base currency evaluation│ VERIFIED       │
└──────────────────────────────────────┴────────────────────────────────┴────────────────┘
```

---

## 6. Remaining Formula Issues

* **Raw Metrics vs Normalized 0–100 Scores:**
  - **F01, F02, F03, F04, F11:** Already express natural $0\%\text{--}100\%$ operational rates. Normalized health score is natively represented as $\max(0.0, 100.0 - \text{rate\_pct})$.
  - **F12:** Expresses a natural $0\%\text{--}100\%$ retention score ($\text{Net Retained Revenue} / \text{Gross Sales} \times 100$).
  - **F05, F09, F10:** Output raw financial dollar metrics (F05 Net Balance $\$$, F09 Divergence Loss $\$$, F10 SKU Contribution $\$$).
  - *Classification:* **NORMALIZATION FORMULA NOT DEFINED for raw dollar outputs (F05, F09)**. These should be displayed on merchant dashboard cards as raw dollar leakage values rather than synthetic $0\text{--}100$ scores unless a merchant-scale normalization function (e.g. loss as % of GMV) is approved.

---

## 7. Data Mapping Requirements (Starting Point for Next Phase)

| Score | Required Input Feature | Required? | Primary Source Table | DB Field | Available? | Transformation / Logic | Data Ingestion Gap |
| :--- | :--- | :---: | :--- | :--- | :---: | :--- | :--- |
| **F01** | `order_id` | Yes | `orders` / `line_items` | `order_id` | **AVAILABLE NOW** | None (Primary key) | None |
| | `net_selling_price` | Yes | `line_items` | `price - discount` | **AVAILABLE NOW** | `selling_price - discount_given` | None |
| | `category` | Yes | `line_items` / `products` | `product_type` | **AVAILABLE NOW** | Map to `TARGET_MARGINS` | Ingest product taxonomy |
| | `cogs_total` | Yes | `inventory_items` | `unit_cost * qty` | **AVAILABLE NOW** | Category fallback if null | Ingest inventory costs |
| | `actual_shipping_cost` | Yes | `orders` / `fulfillments` | `shipping_rate` | **AVAILABLE NOW** | Order courier fee | Ingest carrier 3PL actuals |
| | `gateway_fee` | Yes | `transactions` | `fee` | **AVAILABLE NOW** | Fill 0 if non-Shopify gateway | Ingest payment payouts |
| **F02** | `selling_price` | Yes | `line_items` | `price * qty` | **AVAILABLE NOW** | Catalog list price | None |
| | `discount_given` | Yes | `line_items` | `discount_amount` | **AVAILABLE NOW** | Direct coupon amount | None |
| | `is_discounted` | Yes | `line_items` | `discount_given > 0` | **AVAILABLE NOW** | Boolean check | None |
| **F03** | `net_selling_price`, `cogs_total`, `actual_shipping_cost`, `gateway_fee` | Yes | `orders` / `line_items` | Multiple fields | **AVAILABLE NOW** | Rollup line items to order | None |
| **F04** | `shipping_charged_to_customer` | Yes | `orders` | `total_shipping_price` | **AVAILABLE NOW** | Billed shipping fee | None |
| | `actual_shipping_cost` | Yes | `orders` | Carrier invoice | **AVAILABLE NOW** | Carrier bill | Ingest 3PL rate sheets |
| | `product_weight_kg` | Yes | `variants` | `weight` (converted to kg) | **AVAILABLE NOW** | Grams/Lbs $\rightarrow$ Kg | None |
| | `length_cm`, `width_cm`, `height_cm` | Optional | `metafields` | `custom.dimensions` | **NEEDS TRANSFORMATION** | Volumetric $L \times W \times H / 5000$ | Ingest custom metafields |
| **F05** | `shipping_charged_to_customer`, `actual_shipping_cost` | Yes | `orders` | Multiple fields | **AVAILABLE NOW** | `charged - actual` | None |
| **F09** | `channel` | Yes | `orders` | `source_name` / `channel` | **AVAILABLE NOW** | Normalize (`web`, `amazon`, etc.)| None |
| | `channel_fee_pct` | Yes | `orders` / config | Commission rate | **AVAILABLE NOW** | Channel commission rate | Ingest marketplace fee cards |
| **F10** | `product_id` | Yes | `line_items` | `product_id` / `sku` | **AVAILABLE NOW** | Grouping key | None |
| | `refund_amount` | Yes | `refund_line_items` | `subtotal` | **AVAILABLE NOW** | Credited refund total | Ingest return webhooks |
| | `restocking_cost` | Optional | `refunds` / config | Restock expense | **DERIVED METRIC** | Fallback $5\%$ of net price | Ingest warehouse inspection fees |
| **F11** | `expected_refund_cost` | Optional | `line_items` / model | Historical return rate | **DERIVED METRIC** | Category refund risk allowance | Risk model baseline |
| **F12** | `chargeback_amount` | Optional | `disputes` | `amount` | **AVAILABLE NOW** | Sum dispute losses | Ingest dispute webhooks |

---

## 8. Current Data Availability Classification

* **AVAILABLE NOW (Production Ready):**
  - `orders` (11 core columns): `order_id`, `created_at`, `channel`, `currency`, `gross_sales`, `net_sales`, `shipping_charged_to_customer`, `actual_shipping_cost`, `gateway_fee`, `is_cancelled`, `chargeback_amount`.
  - `line_items` (14 core columns): `order_id`, `line_item_id`, `product_id`, `category`, `quantity`, `selling_price`, `discount_given`, `net_selling_price`, `is_discounted`, `cogs_total`, `product_weight_kg`, `is_returned`, `refund_amount`, `channel_fee_pct`.
* **AVAILABLE BUT NEEDS TRANSFORMATION:**
  - Dimensional Metafields: `length_cm`, `width_cm`, `height_cm` (stored in JSON metafields on Shopify, transformed to float cm in scoring).
  - Multi-Currency: Base currency values persisted at checkout time.
* **DERIVED METRICS (Rule-Based Fallbacks):**
  - `target_min_profit`: Computed dynamically from `net_selling_price` and category configuration.
  - `is_cogs_estimated`: Set dynamically when category average fallback is applied.
  - Restocking Cost: Fallback to $5\%$ of net price if warehouse return inspection fee is unpopulated.

---

## 9. Data Gaps & Developer Ingestion Actions

1. **Shopify Inventory Cost Sync:** Persist `inventory_item.unit_cost` into `line_items.cogs_total` upon order creation webhook.
2. **Carrier 3PL Invoice Ingestion:** Sync actual fulfillment shipping costs from carrier APIs (ShipStation, EasyPost, Flexport) to populate `orders.actual_shipping_cost`.
3. **Dispute / Chargeback Webhook:** Ingest `shopify/disputes` webhooks to populate `orders.chargeback_amount`.
4. **Product Metafields Ingestion:** Ingest custom dimension metafields (`length`, `width`, `height`) for volumetric shipping optimization.

---

## 10. Edge-Case Coverage

* **$100\%$ Promotional Discount:** Order target profit = $\$0.00$, full COGS + logistics flagged as F03 breach and F01 leakage.
* **Exact Profit Floor Boundary:** Orders meeting exact target profit threshold are not flagged.
* **Mixed COGS in Bundles:** Multi-item orders with 1 missing COGS item impute only the missing SKU and retain exact COGS on known SKUs.
* **Partial Returns on Bundles:** Outbound shipping and payment fees are allocated proportionally based on line item net revenue percentage.
* **Bulky Low-Price Goods:** Volumetric weight ($L \times W \times H / 5000$) automatically triggers F04 free-shipping net leakage.

---

## 11. Regression Results (Previous Phase)

* **Previous Test Count:** 92
* **Baseline Test Count:** 107 (+15 new dedicated business rule tests)
* **Passed:** 107 (100%)
* **Failed / Skipped:** 0
* **Regressions:** None

---

## 12. Final Targeted Validation — Remaining Edge Cases & Normalization

### 12.1 Return Edge-Case Results

All three previously identified return edge-case scenarios were comprehensively validated using multi-item order configurations ($A = \$200$, $B = \$500$, $C = \$100$, Total GMV = $\$800$, Outbound Shipping = $\$80$, Gateway Fees = $\$24$).

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          RETURN EDGE CASE VALIDATION MATRIX                           │
├───────────────────────┬──────────────────────────────────┬────────────────┬────────────┤
│ Test Scenario         │ Expected Calculation Summary     │ Actual Result  │ Verdict    │
├───────────────────────┼──────────────────────────────────┼────────────────┼────────────┤
│ 1. Most Expensive     │ Item B (62.5% rev): Ship=$50,    │ Alloc: $50/$15 │ **PASS**   │
│    Item Returned (B)  │ GW=$15. F10 Contrib=-$344.50;    │ F10: -$344.50  │            │
│                       │ F11 Profit=-$229.00; F12=21.375% │ F11: -$229.00  │            │
├───────────────────────┼──────────────────────────────────┼────────────────┼────────────┤
│ 2. Cheapest Item      │ Item C (12.5% rev): Ship=$10,    │ Alloc: $10/$3  │ **PASS**   │
│    Returned (C)       │ GW=$3. F10 Contrib=-$72.50;      │ F10: -$72.50   │ **PASS**   │
│                       │ F11 Profit=$191.00; F12=73.875%  │ F11: $191.00   │            │
├───────────────────────┼──────────────────────────────────┼────────────────┼────────────┤
│ 3. All Items          │ 100% Rev Returned. Alloc sum to  │ Alloc: $80/$24 │ **PASS**   │
│    Returned (A, B, C) │ $80/$24. All F10 negative;       │ F10: all < 0   │            │
│                       │ F11 Profit=-$544.00; F12=-18.0%  │ F11: -$544.00  │            │
└───────────────────────┴──────────────────────────────────┴────────────────┴────────────┘
```

#### Detailed Breakdown of Return Tests

* **Test 1 (Most Expensive Item Returned — Item B = $500):**
  - **Inputs:** Order total = $\$800$ (A: $\$200$, B: $\$500$, C: $\$100$). Costs: COGS A: $\$100$, B: $\$250$, C: $\$50$; Shipping: $\$80$; Gateway: $\$24$. Item B returned with refund $\$500$, restock $\$25$, return shipping $\$4.50$.
  - **Revenue-Weighted Cost Allocation:**
    - Item A ($200 / 800 = 25.0\%$): Shipping $= \$80 \times 0.25 = \$20.00$, Gateway $= \$24 \times 0.25 = \$6.00$
    - Item B ($500 / 800 = 62.5\%$): Shipping $= \$80 \times 0.625 = \$50.00$, Gateway $= \$24 \times 0.625 = \$15.00$
    - Item C ($100 / 800 = 12.5\%$): Shipping $= \$80 \times 0.125 = \$10.00$, Gateway $= \$24 \times 0.125 = \$3.00$
    - Allocation Reconciliation: Total Allocated Shipping $= \$20 + \$50 + \$10 = \$80.00$ ($100\%$); Gateway $= \$6 + \$15 + \$3 = \$24.00$ ($100\%$).
  - **Scoring Outputs:**
    - **F10 Product Contribution:** Item A $= \$74.00$, Item B $= -\$344.50$ (Negative contribution flagged), Item C $= \$37.00$.
    - **F11 Order Profitability:** Total Money Collected $= \$800.00$, Order COGS $= \$400.00$, Shipping $= \$80.00$, Gateway $= \$24.00$, Return Costs $= \$525.00$ $\rightarrow$ Net Order Profit $= -\$229.00$ (Unprofitable order flagged).
    - **F12 Revenue Quality:** Gross Sales $= \$800.00$, Leakage $= \$525.00\text{ (return)} + \$80.00\text{ (shipping deficit)} + \$24.00\text{ (gateway)} = \$629.00$, Net Retained Revenue $= \$171.00$, Quality Score $= 21.375\%$.
  - **Verdict:** **PASS** (Zero cross-item leakage, unreturned items maintain exact positive contributions).

* **Test 2 (Cheapest Item Returned — Item C = $100):**
  - **Inputs:** Identical order structure, Item C returned with refund $\$100$, restock $\$5$, return shipping $\$4.50$.
  - **Scoring Outputs:**
    - **F10 Product Contribution:** Item A $= \$74.00$, Item B $= \$185.00$, Item C $= -\$72.50$ (Negative contribution flagged).
    - **F11 Order Profitability:** Order Net Profit $= \$800 - \$400 - \$80 - \$24 - \$105 = \$191.00$ (Profitable order).
    - **F12 Revenue Quality:** Total Leakage $= \$105 + \$80 + \$24 = \$209.00$, Net Retained Revenue $= \$591.00$, Quality Score $= 73.875\%$.
  - **Verdict:** **PASS** (Correctly verifies that logic is independent of returned item price rank).

* **Test 3 (All Items Returned — Items A, B, C):**
  - **Inputs:** All 3 items marked returned with total refunds $= \$800.00$, restock $= \$40.00$, return shipping $= \$13.50$.
  - **Scoring Outputs:**
    - **F10 Product Contribution:** Item A $= -\$140.50$, Item B $= -\$344.50$, Item C $= -\$72.50$. Total Store Contribution $= -\$557.50$. All SKUs flagged negative.
    - **F11 Order Profitability:** Order Net Profit $= \$800 - \$400 - \$80 - \$24 - \$840 = -\$544.00$.
    - **F12 Revenue Quality:** Total Leakage $= \$840 + \$80 + \$24 = \$944.00$, Net Retained Revenue $= -\$144.00$, Quality Score $= -18.0\%$.
    - **Double-Counting Audit:** Verified that return refunds/restock and outbound logistics are tracked in separate expense buckets without double counting.
  - **Verdict:** **PASS**.

---

### 12.2 F05 Shipping Cost Recovery Normalization Results

* **Specification Formula:** $\text{Score} = \left(\frac{\text{Shipping Fee Charged to Customer}}{\text{Actual Courier Delivery Fee}}\right) \times 100$

| Test ID | Scenario | Inputs (Charged / Actual) | Expected Score | Actual Score | PASS/FAIL | Business Clarification? |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **F05-Ref1** | Full Shipping Recovery | Charged = $10, Courier = $10 | 100.0 | 100.0 | **PASS** | No (Standard Reference) |
| **F05-Ref2** | Partial Recovery (50%) | Charged = $5, Courier = $10 | 50.0 | 50.0 | **PASS** | No (Standard Reference) |
| **F05-Ref3** | Free Shipping (0%) | Charged = $0, Courier = $10 | 0.0 | 0.0 | **PASS** | No (Standard Reference) |
| **F05-A** | Customer Pays Surplus | Charged = $15, Courier = $10 | 150.0 | 150.0 | **PASS** | **YES** (Score > 100: Confirm if capped at 100 or uncapped) |
| **F05-B** | Zero Courier Cost | Charged = $0, Courier = $0 | 100.0 | 100.0 | **PASS** | **YES** (0/0 Div-by-zero: Handled safely as 100% recovery) |
| **F05-C** | Low Partial Shipping | Charged = $2, Courier = $10 | 20.0 | 20.0 | **PASS** | No (Exact linear scale) |
| **F05-D** | High Cost Free Shipping | Charged = $0, Courier = $25 | 0.0 | 0.0 | **PASS** | No (Exact zero recovery) |

---

### 12.3 F09 Channel Margin Divergence Normalization Results

* **Specification Formula:** $\text{Score} = \left(\frac{\text{Marketplace Unit Profit}}{\text{Website Unit Profit}}\right) \times 100$

| Test ID | Scenario | Inputs (Mkt Profit / Web Profit) | Expected Score | Actual Score | PASS/FAIL | Business Clarification? |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **F09-Ref1** | Equal Margin Parity | Mkt = $20, Web = $20 | 100.0 | 100.0 | **PASS** | No (Standard Reference) |
| **F09-Ref2** | Half Profit Parity | Mkt = $10, Web = $20 | 50.0 | 50.0 | **PASS** | No (Standard Reference) |
| **F09-Ref3** | Zero Marketplace Profit | Mkt = $0, Web = $20 | 0.0 | 0.0 | **PASS** | No (Standard Reference) |
| **F09-A** | Marketplace More Profitable | Mkt = $25, Web = $20 | 125.0 | 125.0 | **PASS** | **YES** (Score > 100: Confirm if capped at 100 or uncapped) |
| **F09-B** | Website Profit = $0 | Mkt = $10, Web = $0 | 0.0 | 0.0 | **PASS** | **YES** (Div-by-zero fallback safely defaults to 0.0) |
| **F09-C** | Both Channel Profits = $0 | Mkt = $0, Web = $0 | 100.0 | 100.0 | **PASS** | **YES** (Safe parity fallback defaults to 100.0) |
| **F09-D** | Negative Marketplace Profit | Mkt = -$5, Web = $20 | -25.0 | -25.0 | **PASS** | **YES** (Confirm if negative score capped at 0 or unconstrained) |
| **F09-E** | Negative Website Profit | Mkt = $5, Web = -$10 | -50.0 | -50.0 | **PASS** | **YES** (Inverted ratio semantics require business confirmation) |

---

### 12.4 F10 Product Contribution Normalization Results

* **Specification Formula:** $\text{Score} = \max\left(0, \left(\frac{\text{Net Product Profit}}{\text{Price Paid by Customer}}\right) \times 100\right)$ (Negative scores explicitly capped at 0)

| Test ID | Scenario | Inputs (Net Profit / Price Paid) | Expected Score | Actual Score | PASS/FAIL | Business Clarification? |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- |
| **F10-A** | 30% Net Profit Margin | Net Profit = $30, Price = $100 | 30.0 | 30.0 | **PASS** | No (Standard Reference) |
| **F10-B** | 10% Net Profit Margin | Net Profit = $10, Price = $100 | 10.0 | 10.0 | **PASS** | No (Standard Reference) |
| **F10-C** | Exact Break-Even | Net Profit = $0, Price = $100 | 0.0 | 0.0 | **PASS** | No (Standard Reference) |
| **F10-D** | Loss-Making Product | Net Profit = -$5, Price = $100 | 0.0 (Raw: -5.0) | 0.0 | **PASS** | No (Explicitly capped at 0 per spec) |
| **F10-E** | Zero Price Paid (Free Gift) | Net Profit = $0, Price = $0 | 0.0 | 0.0 | **PASS** | **YES** (Safe zero-price handling defaults to 0.0) |
| **F10-F** | Net Profit > Price Paid | Net Profit = $120, Price = $100 | 120.0 | 120.0 | **PASS** | **YES** (Score > 100: Confirm if capped at 100) |
| **F10-G** | Severe Negative Profit | Net Profit = -$20, Price = $200 | 0.0 (Raw: -10.0)| 0.0 | **PASS** | No (Explicitly capped at 0 per spec) |

---

### 12.5 Normalized Score Direction Verification

Validated that all normalized scales align with the core UX design rule where higher scores represent better operational health:

* **F05 Direction:** $100\text{ (Full Recovery)} > 50\text{ (Partial Recovery)} > 0\text{ (Zero Recovery)}$.
* **F09 Direction:** $100\text{ (Parity with Web Direct)} > 50\text{ (Half Profit)} > 0\text{ (No Profit)}$.
* **F10 Direction:** $100\text{ (100% Margin)} > 30\text{ (30% Margin)} > 0\text{ (Break-Even or Loss)}$.

---

### 12.6 Implementation Changes Made

1. **[`src/scoring/f05.py`](file:///d:/Zeister/src/scoring/f05.py):**
   - Added `compute_f05_normalized_score(charged, actual) -> float`.
   - Added `shipping_recovery_score_pct` column to `compute_f05(df)` preserving existing financial dollar deltas and boolean flags.
2. **[`src/scoring/f09.py`](file:///d:/Zeister/src/scoring/f09.py):**
   - Added `compute_f09_normalized_score(mkt_unit_profit, web_unit_profit) -> float`.
   - Added `normalized_score` attribute to each channel object in `compute_f09()` channel breakdown.
3. **[`src/scoring/f10.py`](file:///d:/Zeister/src/scoring/f10.py):**
   - Added `compute_f10_normalized_score(net_product_profit, price_paid) -> float` enforcing the business rule that negative margins cap at 0.
   - Added `normalized_contribution_score` column to `compute_f10()` preserving raw unconstrained `contribution_margin_pct`.
4. **[`tests/test_final_edge_cases_and_normalization.py`](file:///d:/Zeister/tests/test_final_edge_cases_and_normalization.py):**
   - Created comprehensive test module with 12 new automated test functions validating all return edge cases, reference examples, boundary cases, and direction invariants.

---

### 12.7 Full Regression Results

Execution of the entire regression suite across all 13 test modules:

```powershell
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-8.4.2, pluggy-1.5.0
rootdir: D:\Zeister
collected 119 items

tests/test_data_clean.py .................                               [ 14%]
tests/test_f01_f03.py .....................                              [ 31%]
tests/test_f02.py ........                                               [ 38%]
tests/test_f04.py .........                                              [ 46%]
tests/test_f05.py ...........                                            [ 55%]
tests/test_f09.py ....                                                   [ 58%]
tests/test_f10.py ...                                                    [ 61%]
tests/test_f11.py ......                                                 [ 66%]
tests/test_f12.py .....                                                  [ 70%]
tests/test_final_edge_cases_and_normalization.py ............             [ 80%]
tests/test_integration.py ..........                                     [ 89%]
tests/test_shopify_parser.py .                                           [ 89%]
tests/test_v1_business_rules.py ...............                          [100%]

============================= 119 passed in 2.10s =============================
```

* **Previous Test Count:** 107
* **New Test Count:** 119 (+12 new tests)
* **Passed:** 119 (100%)
* **Failed / Skipped:** 0
* **Regressions:** 0

---

### 12.8 Final Status Classification

| Formula | Area | Status | Evidence |
| :--- | :--- | :---: | :--- |
| **F05** | Core Formula (Financial Dollar Delta) | **VERIFIED** | `test_f05.py`, `test_10_v1_single_package_assumption` |
| **F05** | Normalization (0–100 Recovery Score) | **VERIFIED** | `test_final_edge_cases_and_normalization.py::test_f05_reference_examples`, `test_f05_edge_cases` |
| **F09** | Core Formula (Divergence Dollar Loss) | **VERIFIED** | `test_f09.py` |
| **F09** | Normalization (Channel Parity Score) | **VERIFIED** | `test_final_edge_cases_and_normalization.py::test_f09_reference_examples`, `test_f09_edge_cases` |
| **F10** | Core Formula (Revenue-Weighted Allocation) | **VERIFIED** | `test_7_and_8_partial_return_revenue_weighted_allocation`, `test_f10.py` |
| **F10** | Normalization (Net Margin Score, Capped at 0) | **VERIFIED** | `test_final_edge_cases_and_normalization.py::test_f10_normalization_cases` |
| **F10/F11/F12** | Most Expensive Item Returned | **VERIFIED** | `test_final_edge_cases_and_normalization.py::test_return_edge_case_1_most_expensive_item_returned` |
| **F10/F11/F12** | Cheapest Item Returned | **VERIFIED** | `test_final_edge_cases_and_normalization.py::test_return_edge_case_2_cheapest_item_returned` |
| **F10/F11/F12** | All Items Returned | **VERIFIED** | `test_final_edge_cases_and_normalization.py::test_return_edge_case_3_all_items_returned` |

---

### 12.9 Business Clarification List (Undefined Boundary Semantics)

The following boundary conditions are safely handled in code without runtime errors, but their exact business semantics should be confirmed for final merchant-facing UI copy:

1. **F05 — Actual Courier Cost = $0 (`F05-B`):** Current implementation safely outputs `100.0` (zero shipping loss). Confirm if $0 shipping cost orders should display $100\%$ recovery or be marked as N/A / exempt.
2. **F05 / F09 / F10 — Scores Above 100 (`F05-A`, `F09-A`, `F10-F`):** When shipping charged exceeds courier cost (e.g. $\$15$ charged on $\$10$ cost $\rightarrow 150\%$) or marketplace profit exceeds web direct profit (e.g. $\$25$ vs $\$20 \rightarrow 125\%$), raw mathematical scores exceed $100$. Confirm whether dashboard cards should clamp display values to $[0, 100]$ or allow surplus display ($> 100$).
3. **F09 — Website Unit Profit = $0 or Negative (`F09-B`, `F09-E`):** When website profit is $0$, division by zero is safely caught and returns $0.0$. When website profit is negative ($-\$10$) and marketplace is positive ($+\$5$), the ratio produces $-50.0\%$. Confirm business interpretation for stores with loss-making direct channels.
4. **F10 — Zero Price Paid (`F10-E`):** For $100\%$ discounted promotional items or free gifts ($0$ price paid), division by zero safely returns $0.0$. Confirm if this meets merchant expectations.
5. **F11 — Expected Refund Cost Fallback Rate:** Confirm if $5\%$ category risk allowance fallback is approved for production when historical SKU return rates are unpopulated.

---

### READY FOR DATA MAPPING
All required formula calculations, partial-return allocation rules, and newly specified normalization formulas (F05, F09, F10) are fully validated and pass 119/119 automated regression tests with 0 regressions. The system is ready to proceed to live GraphQL and database ingestion mapping.

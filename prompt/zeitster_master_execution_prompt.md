# MASTER EXECUTION BRIEF — Zeitster Formula Testing & Data Pipeline

Paste this whole document at the start of every session with Opus on this
work. It is designed to be self-contained: even if this is a brand-new
conversation with no prior memory, Opus should be able to read this brief +
the living log (Section 7) and know exactly where things stand and what to
do next.

---

## 1. CONTEXT — What this project is

Zeitster is a multi-tenant analytics platform that connects to merchants'
Shopify stores (+ external sources like 3PL couriers, payment gateways,
marketplaces) and calculates ~120 business-health formulas (F01, F02, ...,
C-series, R-series) per order/customer/merchant. I am the sole owner of the
data architecture and scoring engine for this product. A backend/data team
joins in a few months; until then, I am building and validating this alone.

Formulas depend on fields with different reliability:
- ✅ VERIFIED — native Shopify fields, always present on valid orders
- ⚠️ PARTIAL — Shopify fields that are sometimes null (e.g. manual orders)
- ⚙️ METAFIELD — merchant-configured values (target margins, thresholds,
  product dimensions) — NOT guaranteed to exist, and Shopify only ever
  returns the CURRENT value (no history — overwritten on every update)
- ❌ EXTERNAL — from 3PL/gateway/marketplace APIs, not in Shopify at all
- 🧮 DERIVED — computed inside our own pipeline from other fields

A known hard constraint: Shopify metafields have no built-in history. Once
overwritten, the old value is permanently gone. Our own system must capture
every metafield change as an append-only event from the day we start
tracking it (the "cutover date"). Data before cutover is a permanent,
expected gap — not an error — and must be handled differently from a
post-cutover gap (which is a real problem worth investigating).

---

## 2. YOUR ROLE AND OPERATING PRINCIPLES

You are acting as the data engineer + QA lead for this pipeline. You own:
generating/extending realistic synthetic test data, building the formula
test matrix, executing tests, logging defects, and maintaining the living
documentation described in Section 7. You do NOT own final business
decisions (margin %, thresholds, which formulas ship first) — you flag
those and wait for my input.

**Operating rules:**
1. Never silently guess at a business rule. If a formula's fallback
   behavior, a threshold, or a data-source priority isn't already defined
   in existing docs, flag it (see Section 5) instead of inventing it.
2. Never mark a formula "tested and passing" unless it has been run against
   all 6 required edge-case types (Section 4) with results logged.
3. Every session, append to the living log — never overwrite or summarize
   away prior entries. The log is the permanent memory of this project.
4. Treat existing uploaded data (category3_* files, synthetic_orders,
   synthetic_line_items, etc.) as authoritative and already-validated
   where it overlaps with new work — extend it, don't regenerate it.
5. If something looks wrong in already-approved data or a prior decision,
   flag it explicitly rather than quietly changing it.

---

## 3. CLASSIFICATION SYSTEM — use this tag on every decision or output

| Tag | Meaning |
|---|---|
| CONFIRMED | Already validated against real data or explicitly approved by me |
| PROPOSED | Your recommendation, not yet approved — safe default, but flagged |
| NEEDS TECHNICAL DECISION | Requires backend/data engineering input once team joins |
| NEEDS BUSINESS DECISION | Requires my approval (thresholds, margins, priorities) |
| NEEDS REAL-DATA VALIDATION | Cannot be confirmed until tested against a real merchant |

Every table, formula result, or fallback rule you produce must carry one of
these tags. Never present a PROPOSED value as if it were CONFIRMED.

---

## 4. TASK SEQUENCE (what to execute, in order)

### Step 1 — Data generation / extension
Generate synthetic data using the schema and requirements in
`zeitster_synthetic_dataset_generation_prompt.md` (16 tables: orders,
line_items, customers, transactions, refunds, shipping_fulfillments,
disputes, subscriptions, subscription_events, products_variants,
metafields, metafield_history, support_tickets, category_cogs_benchmarks,
category_margin_targets, merchants). Reuse merchant_id / category / column
naming conventions from the existing category3_* and synthetic_* files —
do not create parallel incompatible schemas.

**Required edge-case coverage per formula (all 6, no exceptions):**
1. Normal case — clean, all fields present
2. Boundary/zero case — thresholds hit exactly, 100% discount, $0 breach
3. Missing field WITH approved fallback
4. Missing field WITH NO approved fallback → must resolve "Unresolved," never 0
5. Partial refund / return case
6. Multi-line-item allocation case (where relevant, e.g. F10)

Plus dataset-wide requirements: pre-cutover vs post-cutover metafield
history split, multi-merchant/multi-category variety, realistic null rates
per field-status type (not uniformly complete data).

### Step 2 — Validate before merge
Before merging new data with existing files, confirm:
- Column names match exactly across old and new files per table
- No colliding order_id / customer_id / test_case_id across batches
- Every claimed edge case actually exists in the generated rows (spot-check,
  don't just trust the tag)

### Step 3 — Merge into single working dataset
One CSV per table, `test_case_id` preserved on every row.

### Step 4 — Build the test matrix
For every formula, produce a table: `formula_id | test_case_id | input
values | expected output (hand-calculated) | status`. Expected outputs must
be manually derived from the formula's core mathematical definition — not
just copied from what the pipeline produces (that would test nothing).

### Step 5 — Execute
Run each formula against its test rows. Compare actual vs. expected.
Anything that doesn't match is a defect — log it in the living doc
(Section 7) with formula id, test_case_id, expected vs actual, and a
hypothesis for the cause (formula logic bug vs. fallback logic bug vs. bad
test data).

### Step 6 — Fix and re-test
A formula is only "done" when it passes 100% of its 6 required case types.
Partial passes stay open, logged, and are not marked complete.

### Step 7 — Move to next formula
Priority order: low-risk formulas first (mostly VERIFIED fields), then
medium-risk (PARTIAL/external dependent), then metafield-dependent formulas
last (F01, F02, F04), since those need cutover-date logic already proven by
earlier formulas.

---

## 5. WHEN TO FLAG INSTEAD OF PROCEED

Stop and flag (don't guess) whenever:
- A formula's fallback value isn't documented anywhere (e.g. what exact
  category-average COGS number to use if metafield AND category benchmark
  are both missing)
- Two source documents disagree on a field's source path or classification
- A test case reveals an edge case not covered in Section 4 (e.g. negative
  refund amount, duplicate order IDs) — flag it as a new case type to add,
  don't just handle it silently
- Generated data volume/realism seems insufficient to trust a formula's
  boundary behavior

Flag format in the log: `⚠️ FLAG — [formula_id] — [description] — [tag from
Section 3] — [what decision/input is needed from me]`

---

## 6. DEFINITION OF DONE (per formula)

A formula is only marked complete when ALL of the following are true:
- [ ] All 6 required edge cases tested with hand-calculated expected values
- [ ] Actual output matches expected for every case, or documented+approved
      tolerance applies
- [ ] Every field's fallback behavior is CONFIRMED or explicitly flagged
      NEEDS BUSINESS/TECHNICAL DECISION
- [ ] No field defaults silently to zero on missing data
- [ ] Pre/post-cutover metafield behavior tested (for metafield-dependent
      formulas only)
- [ ] Logged in the living documentation with pass/fail summary

---

## 7. LIVING DOCUMENTATION — append-only log

Maintain this as a single running file (e.g.
`zeitster_testing_log.md`). NEVER delete or rewrite past entries — only
append new ones. Each session, add a new dated entry using this exact
template:

```
## [YYYY-MM-DD] Session Entry

### Formulas worked on
- F0X: [status — in progress / complete / blocked]

### What was done
- [bullet list of concrete actions: data generated, tests run, defects found]

### Test results summary
| Formula | Cases passed | Cases failed | Notes |
|---|---|---|---|

### Flags raised this session
- ⚠️ [flag details, using format from Section 5]

### Decisions made / approved this session
- [only decisions I explicitly approved go here, tagged CONFIRMED]

### Open items carried to next session
- [anything unresolved, with enough detail that a fresh session with no
  memory could pick it up cold]
```

At the start of every new session, read the ENTIRE existing log before
doing anything else, so no prior context, decision, or open flag is lost.

---

## 8. FIRST ACTION FOR THIS SESSION

Start at Step 1 (Section 4). Before generating anything, read all existing
uploaded data files and the `zeitster_synthetic_dataset_generation_prompt.md`
spec, confirm you understand the existing schema/conventions, and list any
ambiguities as flags before proceeding — do not generate data on assumptions
that could be wrong.

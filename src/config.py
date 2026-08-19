"""src/config.py — Central configuration for all scoring modules (F01–F12).

Every business-tunable parameter lives here. No score module should
hard-code thresholds, policies, or margin targets — import from this file.
"""

# ---------------------------------------------------------------------------
# 🔶 Decision 1 — Missing-COGS Policy (F01, F03, F10, F11)
# ---------------------------------------------------------------------------
# "exclude"            → drop rows where COGS is null (conservative, deterministic)
# "impute_category_avg"→ fill nulls with category-average COGS (higher totals, less data loss)
COGS_POLICY: str = "exclude"

# ---------------------------------------------------------------------------
# 🔶 Decision 2 — Target Minimum Profit (as % of selling_price) (F01, F11)
# ---------------------------------------------------------------------------
TARGET_MARGINS: dict[str, float] = {
    "fashion":      0.15,
    "beauty":       0.20,
    "electronics":  0.08,
    "home_goods":   0.12,
    "luxury":       0.25,
    "pet_care":     0.15,
}
DEFAULT_TARGET_MARGIN: float = 0.15  # fallback for unknown categories

# ---------------------------------------------------------------------------
# 🔶 Decision 3 & D11 — F04: Free-Shipping Leakage Parameters
# ---------------------------------------------------------------------------
# Formula choice:
# "formula_a" -> Courier Fee - Shipping Charged (unrecovered courier cost)
# "formula_b" -> Product Profit - Courier Cost (true net cash loss)
F04_FORMULA_CHOICE: str = "formula_b"

# Free-shipping threshold ($)
FREE_SHIPPING_THRESHOLD: float = 50.00

# Category-tiered free shipping thresholds
FREE_SHIPPING_TIERS: dict[str, float] = {
    "fashion":      50.00,
    "beauty":       40.00,
    "electronics": 75.00,
    "home_goods":  100.00,
    "luxury":      150.00,
    "pet_care":     45.00,
}

# Volumetric weight divisor
# International standard (DHL, FedEx, UPS intl): (L_cm × W_cm × H_cm) / 5000
VOLUMETRIC_DIVISOR: int = 5000
# US domestic (FedEx/UPS inches): (L_in × W_in × H_in) / 139
DOMESTIC_VOLUMETRIC_DIVISOR: int = 139

# ---------------------------------------------------------------------------
# 🔶 Decision 6 — F02: Discount Dependency Benchmark
# ---------------------------------------------------------------------------
# Spec states 20-30%; industry research benchmark is ~13-20%
HEALTHY_DISCOUNT_SHARE: float = 0.20

# ---------------------------------------------------------------------------
# 🔶 Decision 5 — F09: Channel Margin Divergence
# ---------------------------------------------------------------------------
# "dollar_per_unit" -> Primary Unit Profit - Channel Unit Profit
# "percentage"       -> Primary Margin % - Channel Margin %
F09_FORMULA_CHOICE: str = "dollar_per_unit"
PRIMARY_CHANNEL: str = "web"

# ---------------------------------------------------------------------------
# F10 / F11 — Return & Restocking Assumptions
# ---------------------------------------------------------------------------
# Default fallback restocking / inspection cost as % of item price if app data is missing
DEFAULT_RESTOCKING_RATE: float = 0.05
DEFAULT_RETURN_SHIPPING_FLAT: float = 4.50

# ---------------------------------------------------------------------------
# Required columns for basic sanity
# ---------------------------------------------------------------------------
REQUIRED_ORDER_COLUMNS: list[str] = [
    "order_id",
    "selling_price",
    "net_selling_price",
    "shipping_charged_to_customer",
    "actual_shipping_cost",
]

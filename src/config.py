"""src/config.py — Central configuration for all scoring modules (F01–F12).

Updated to include food_bev category and column alias mappings for
bridging the unified zeitster_* schema to existing scoring modules.
"""

# ---------------------------------------------------------------------------
# Decision 1 — Missing-COGS Policy (F01, F03, F10, F11)
# ---------------------------------------------------------------------------
# "impute_category_avg" -> fill nulls with category-average fallback and set estimated flag
# "exclude"             -> drop rows where COGS is null
COGS_POLICY: str = "impute_category_avg"

# ---------------------------------------------------------------------------
# Decision 2 — Target Minimum Profit Margins (F01)
# ---------------------------------------------------------------------------
TARGET_MARGINS: dict[str, float] = {
    "fashion":      0.15,
    "beauty":       0.20,
    "electronics":  0.08,
    "home_goods":   0.12,
    "luxury":       0.25,
    "pet_care":     0.15,
    "food_bev":     0.18,  # PROPOSED — added for new unified dataset
}
DEFAULT_TARGET_MARGIN: float = 0.15

# ---------------------------------------------------------------------------
# Decision 3 & D11 — F04: Free-Shipping Leakage Parameters
# ---------------------------------------------------------------------------
F04_FORMULA_CHOICE: str = "formula_b"
FREE_SHIPPING_THRESHOLD: float = 50.00
FREE_SHIPPING_TIERS: dict[str, float] = {
    "fashion":      50.00,
    "beauty":       40.00,
    "electronics":  75.00,
    "home_goods":  100.00,
    "luxury":      150.00,
    "pet_care":     45.00,
    "food_bev":     35.00,  # PROPOSED — lower threshold for consumables
}
VOLUMETRIC_DIVISOR: int = 5000
DOMESTIC_VOLUMETRIC_DIVISOR: int = 139

# ---------------------------------------------------------------------------
# Decision 6 — F02: Discount Dependency Thresholds
# ---------------------------------------------------------------------------
HEALTHY_DISCOUNT_SHARE: float = 0.20
WARNING_DISCOUNT_SHARE: float = 0.30

# ---------------------------------------------------------------------------
# Decision 5 — F09: Channel Margin Divergence
# ---------------------------------------------------------------------------
F09_FORMULA_CHOICE: str = "dollar_per_unit"
PRIMARY_CHANNEL: str = "web"

# ---------------------------------------------------------------------------
# F10 / F11 — Return & Restocking Assumptions
# ---------------------------------------------------------------------------
DEFAULT_RESTOCKING_RATE: float = 0.05
DEFAULT_RETURN_SHIPPING_FLAT: float = 4.50

# ---------------------------------------------------------------------------
# F06 — Payment Fee Leakage Parameters
# ---------------------------------------------------------------------------
F06_STANDARD_FEE_PCT: float = 0.029
F06_STANDARD_FIXED_FEE: float = 0.30
F06_HIGH_COST_RATES: dict[str, dict[str, float]] = {
    "bnpl": {"pct": 0.06, "fixed": 0.30},
    "intl_card": {"pct": 0.045, "fixed": 0.30},
}

# ---------------------------------------------------------------------------
# Category: Inventory & Capital Risk (I03, I04, I05, I08)
# ---------------------------------------------------------------------------
I03_DEFAULT_AGING_THRESHOLD_DAYS: int = 180
I04_DEFAULT_VELOCITY_WINDOW_DAYS: int = 30
I05_DEFAULT_SUPPORT_COST: float = 15.00
I08_RESTOCK_DELAY_THRESHOLD_HOURS: float = 48.0
I08_MAX_RESTOCK_WINDOW_DAYS: int = 30

# ---------------------------------------------------------------------------
# Category: Logistics & Fulfillment (L01, L07, L12)
# ---------------------------------------------------------------------------
L01_DEFAULT_PERIOD_AVG_SHIPPING_COST: float = 6.50
L07_DEFAULT_ZONE_SURCHARGE_COLLECTED: float = 0.00
L12_DEFAULT_DISPATCH_SLA_HOURS: float = 48.0
L12_DEFAULT_WISMO_TICKET_COST: float = 12.00
L12_DEFAULT_WASTED_LABOR_COST: float = 8.50


# ---------------------------------------------------------------------------
# Category COGS Benchmarks (fallback reference values)
# ---------------------------------------------------------------------------
CATEGORY_COGS_BENCHMARKS: dict[str, float] = {
    "fashion":      35.00,
    "beauty":       18.50,
    "electronics": 120.00,
    "home_goods":   45.00,
    "luxury":      350.00,
    "pet_care":     22.00,
    "food_bev":     12.00,  # PROPOSED
}

# ---------------------------------------------------------------------------
# Column Alias Mapping — Zeitster unified schema → F01-F12 scoring columns
# ---------------------------------------------------------------------------
# The unified zeitster_* tables use category3_* naming. Existing F01-F12
# scoring modules expect the generate_data.py naming. This mapping allows
# the data_clean layer to rename columns before passing to scoring.
COLUMN_ALIASES: dict[str, str] = {
    # zeitster_* column name → existing scoring module column name
    "gross_price":     "selling_price",
    "discount_amount": "discount_given",
    "net_price":       "net_selling_price",
    "cogs":            "cogs_total",
}

# Reverse mapping for going from scoring columns back to zeitster names
COLUMN_ALIASES_REVERSE: dict[str, str] = {v: k for k, v in COLUMN_ALIASES.items()}

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

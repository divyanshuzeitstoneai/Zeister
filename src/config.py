"""src/config.py — Central configuration for all scoring modules (F01–F12)."""

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
# Required columns for basic sanity
# ---------------------------------------------------------------------------
REQUIRED_ORDER_COLUMNS: list[str] = [
    "order_id",
    "selling_price",
    "net_selling_price",
    "shipping_charged_to_customer",
    "actual_shipping_cost",
]

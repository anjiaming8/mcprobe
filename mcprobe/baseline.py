"""Stable facts used by McProbe's contract checks.

The official documentation listed 33 tools at the time this project was
created. The live endpoint exposes two additional tools, so the observed
baseline is 35. Keep this list in one place: users can audit every expected
name without reading diagnostic code.
"""

from __future__ import annotations


EXPECTED_TOOL_COUNT = 35

EXPECTED_TOOLS: tuple[str, ...] = (
    "list-nutrition-foods",
    "delivery-query-addresses",
    "delivery-create-address",
    "delivery-query-stores",
    "query-meal-assistance",
    "query-nearby-stores",
    "query-store-coupons",
    "query-meals",
    "query-meal-detail",
    "calculate-price",
    "create-order",
    "cancel-order",
    "query-order",
    "order-list",
    "campaign-calendar",
    "available-coupons",
    "auto-bind-coupons",
    "query-my-coupons",
    "query-my-account",
    "mall-points-products",
    "mall-product-detail",
    "mall-create-order",
    "now-time-info",
    "query-lottery-info",
    "draw-lottery",
    "query-my-prizes",
    "mall-order-list",
    "mall-order-detail",
    "query-party-city",
    "query-party-store",
    "query-party-store-date",
    "query-party-store-session",
    "party-order-create",
    "query-promotions",
    "query-survey-coupon",
)

# McProbe calls only these read-only tools. It never calls write tools.
CORE_READ_TOOLS: tuple[str, ...] = (
    "now-time-info",
    "campaign-calendar",
)

ACCOUNT_READ_TOOLS: tuple[str, ...] = ("query-my-account",)

# These tools can change remote state or spend money/points. McProbe treats
# them as presence-only contract checks and never invokes them.
WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "delivery-create-address",
        "create-order",
        "cancel-order",
        "auto-bind-coupons",
        "mall-create-order",
        "draw-lottery",
        "party-order-create",
    }
)

PERSONAL_DATA_TOOLS: frozenset[str] = frozenset(
    {
        "delivery-query-addresses",
        "query-store-coupons",
        "query-my-coupons",
        "query-my-account",
        "query-order",
        "order-list",
        "query-my-prizes",
        "mall-order-list",
        "mall-order-detail",
    }
)


def tool_risk(name: str) -> str:
    """Return a conservative risk label for a tool name."""

    if name in WRITE_TOOLS:
        return "write"
    if name in PERSONAL_DATA_TOOLS:
        return "personal"
    return "read"

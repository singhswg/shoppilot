"""Coupon discovery, cashback portal matching, and stacked savings calculation tools."""

from __future__ import annotations

from typing import Any

from google.adk.tools.tool_context import ToolContext

from shoppilot.catalog_data import COUPONS_AND_CASHBACK
from shoppilot.schemas import ToolResponse


def find_coupons_and_cashback(
    retailer: str,
    cart_subtotal_usd: float = 0.0,
    include_membership_offers: bool = True,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Find active promo codes, cashback portals, and credit card rewards for a retailer.

    Automatically highlights offers matching memberships saved in `user:preferences`.

    Args:
        retailer: Target retailer name (e.g., "Best Buy", "Amazon", "Target", "Walmart", "Costco", "REI").
        cart_subtotal_usd: Optional cart subtotal in USD to filter by minimum spend thresholds.
        include_membership_offers: If False, excludes offers requiring paid memberships unless the user has them.

    Returns:
        Structured list of matching promo codes, cashback portals, and eligibility notes.
    """
    if not retailer or not retailer.strip():
        return ToolResponse(status="error", error="retailer must be a non-empty string.").model_dump()
    if cart_subtotal_usd < 0:
        return ToolResponse(status="error", error="cart_subtotal_usd cannot be negative.").model_dump()

    user_memberships: set[str] = set()
    if tool_context is not None:
        prefs = tool_context.state.get("user:preferences", {})
        if isinstance(prefs, dict):
            user_memberships = {m.lower() for m in prefs.get("memberships", [])}

    target = retailer.strip().lower()
    matched: list[dict[str, Any]] = []
    for offer in COUPONS_AND_CASHBACK:
        if offer.retailer.lower() != target:
            continue

        req = offer.membership_required
        user_has_membership = req is None or req.lower() in user_memberships
        if not include_membership_offers and not user_has_membership:
            continue

        meets_min_spend = cart_subtotal_usd == 0.0 or cart_subtotal_usd >= offer.min_spend_usd
        matched.append(
            {
                "code": offer.code,
                "source": offer.source,
                "retailer": offer.retailer,
                "discount_type": offer.discount_type,
                "discount_value": offer.discount_value,
                "min_spend_usd": offer.min_spend_usd,
                "meets_min_spend": meets_min_spend,
                "stackable": offer.stackable,
                "membership_required": req,
                "user_eligible_now": user_has_membership and meets_min_spend,
                "expires_on": offer.expires_on,
                "description": offer.description,
            }
        )

    if not matched:
        return ToolResponse(
            status="not_found",
            data={"retailer": retailer, "offers": []},
        ).model_dump()

    return ToolResponse(
        status="success",
        data={"retailer": retailer, "offers": matched, "count": len(matched)},
    ).model_dump()


def calculate_stacked_savings(
    retailer: str,
    item_price_usd: float,
    user_memberships: list[str] | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Calculate the maximum legal stack of promo codes + cashback portals + credit card rewards.

    Args:
        retailer: Retailer name.
        item_price_usd: Base item price before coupons and cashback.
        user_memberships: Optional list of user memberships (falls back to `user:preferences`).

    Returns:
        Breakdown of upfront coupon discount, cashback earned, total savings, and effective net price.
    """
    if item_price_usd <= 0:
        return ToolResponse(status="error", error="item_price_usd must be positive.").model_dump()

    memberships_set: set[str] = {m.lower() for m in (user_memberships or [])}
    if not memberships_set and tool_context is not None:
        prefs = tool_context.state.get("user:preferences", {})
        if isinstance(prefs, dict):
            memberships_set = {m.lower() for m in prefs.get("memberships", [])}

    target = retailer.strip().lower()
    eligible = [
        o
        for o in COUPONS_AND_CASHBACK
        if o.retailer.lower() == target
        and item_price_usd >= o.min_spend_usd
        and (o.membership_required is None or o.membership_required.lower() in memberships_set)
    ]

    # Pick best upfront promo (percent or fixed_usd)
    upfront_offers = [o for o in eligible if o.discount_type in ("percent", "fixed_usd")]
    best_upfront = None
    upfront_savings = 0.0
    for offer in upfront_offers:
        saving = (
            item_price_usd * (offer.discount_value / 100.0)
            if offer.discount_type == "percent"
            else offer.discount_value
        )
        if saving > upfront_savings:
            upfront_savings = saving
            best_upfront = offer

    price_after_promo = max(0.0, round(item_price_usd - upfront_savings, 2))

    # Stack eligible cashback offers if the chosen upfront promo is stackable (or no upfront promo)
    applied_offers: list[dict[str, Any]] = []
    if best_upfront is not None:
        applied_offers.append(
            {
                "source": best_upfront.source,
                "code": best_upfront.code,
                "savings_usd": round(upfront_savings, 2),
                "type": best_upfront.discount_type,
            }
        )

    cashback_total = 0.0
    if best_upfront is None or best_upfront.stackable:
        for offer in eligible:
            if offer.discount_type == "cashback_percent" and offer.stackable:
                cb = round(price_after_promo * (offer.discount_value / 100.0), 2)
                cashback_total += cb
                applied_offers.append(
                    {
                        "source": offer.source,
                        "code": None,
                        "savings_usd": cb,
                        "type": "cashback_percent",
                    }
                )

    total_savings = round(upfront_savings + cashback_total, 2)
    effective_net_price = max(0.0, round(item_price_usd - total_savings, 2))

    return ToolResponse(
        status="success",
        data={
            "retailer": retailer,
            "base_price_usd": round(item_price_usd, 2),
            "upfront_discount_usd": round(upfront_savings, 2),
            "checkout_price_usd": price_after_promo,
            "cashback_rewards_usd": round(cashback_total, 2),
            "total_savings_usd": total_savings,
            "effective_net_price_usd": effective_net_price,
            "applied_stack": applied_offers,
        },
    ).model_dump()

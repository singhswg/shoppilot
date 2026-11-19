"""Holiday deal discovery, cross-retailer price comparison, and buy-timing intelligence tools."""

from __future__ import annotations

from typing import Any

from google.adk.tools.tool_context import ToolContext

from shoppilot.catalog_data import CATALOG, HOLIDAY_CALENDAR
from shoppilot.config import get_settings
from shoppilot.schemas import CatalogProduct, RetailerOffer, ToolResponse

_ALLOWED_CATEGORIES = {
    "electronics",
    "audio",
    "gaming",
    "home_kitchen",
    "wearables",
    "toys_gifts",
    "outdoor",
}
_ALLOWED_SORTS = {
    "price_asc",
    "price_desc",
    "discount_desc",
    "rating_desc",
    "deal_score_desc",
}


def _best_offer(
    product: CatalogProduct,
    in_stock_only: bool = True,
    retailer_filter: set[str] | None = None,
) -> RetailerOffer | None:
    """Select the lowest landed-cost offer matching filters."""
    candidates = [
        offer
        for offer in product.offers
        if (not in_stock_only or offer.in_stock)
        and (not retailer_filter or offer.retailer.lower() in retailer_filter)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda o: o.current_price + o.shipping_cost)


def _compute_deal_score(product: CatalogProduct, offer: RetailerOffer) -> tuple[float, bool]:
    """Compute a 0-100 authenticity-adjusted deal score and fake-deal flag.

    Penalizes items whose current price is above their 90-day average despite
    a high advertised MSRP discount.
    """
    hist = product.price_history
    is_fake_deal = offer.current_price > hist.avg_90d_price
    if is_fake_deal:
        return 20.0, True

    pct_below_avg = max(0.0, (hist.avg_90d_price - offer.current_price) / hist.avg_90d_price)
    at_all_time_low = offer.current_price <= hist.all_time_low * 1.01
    rating_bonus = (product.rating / 5.0) * 15.0
    low_bonus = 25.0 if at_all_time_low else 10.0
    score = min(100.0, round(40.0 + (pct_below_avg * 120.0) + rating_bonus + low_bonus, 1))
    return score, False


def _resolve_product(product_id_or_name: str) -> CatalogProduct | None:
    """Resolve a product by exact ID or fuzzy substring match."""
    key = product_id_or_name.strip().lower()
    if not key:
        return None
    if key in CATALOG:
        return CATALOG[key]
    for prod in CATALOG.values():
        if key in prod.product_id.lower() or key in prod.name.lower():
            return prod
    return None


def search_holiday_deals(
    query: str = "",
    category: str = "",
    max_price_usd: float | None = None,
    min_discount_pct: float = 0.0,
    retailers: list[str] | None = None,
    in_stock_only: bool = True,
    sort_by: str = "deal_score_desc",
    limit: int = 5,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Search holiday deals across major retailers with authenticity scoring.

    Args:
        query: Keyword(s) to match against product name, brand, or tags (e.g., "headphones", "espresso", "gift").
        category: Optional category filter. One of: electronics, audio, gaming, home_kitchen, wearables, toys_gifts, outdoor.
        max_price_usd: Optional maximum price ceiling in USD.
        min_discount_pct: Minimum advertised discount percentage off list price (0-90).
        retailers: Optional list of retailer names to restrict results (e.g., ["Amazon", "Best Buy"]).
        in_stock_only: If True, only include currently in-stock offers.
        sort_by: Sort order. One of: deal_score_desc, price_asc, price_desc, discount_desc, rating_desc.
        limit: Maximum number of results to return (1-20).

    Returns:
        Structured dictionary with matching holiday deals, best retailer offer,
        authenticity deal score, and fake-deal warnings.
    """
    settings = get_settings()
    if len(query) > settings.max_query_length:
        return ToolResponse(
            status="error",
            error=f"Query exceeds maximum length of {settings.max_query_length} characters.",
        ).model_dump()

    normalized_category = category.strip().lower()
    if normalized_category and normalized_category not in _ALLOWED_CATEGORIES:
        return ToolResponse(
            status="error",
            error=f"Invalid category '{category}'. Allowed: {sorted(_ALLOWED_CATEGORIES)}",
        ).model_dump()

    if sort_by not in _ALLOWED_SORTS:
        return ToolResponse(
            status="error",
            error=f"Invalid sort_by '{sort_by}'. Allowed: {sorted(_ALLOWED_SORTS)}",
        ).model_dump()

    if max_price_usd is not None and (max_price_usd <= 0 or max_price_usd > settings.max_budget_usd):
        return ToolResponse(
            status="error",
            error=f"max_price_usd must be between 0 and {settings.max_budget_usd}.",
        ).model_dump()

    if not (0.0 <= min_discount_pct <= 90.0):
        return ToolResponse(
            status="error",
            error="min_discount_pct must be between 0 and 90.",
        ).model_dump()

    bounded_limit = max(1, min(limit, 20))
    retailer_set = {r.strip().lower() for r in retailers if r.strip()} if retailers else None
    tokens = [t for t in query.lower().split() if t]

    results: list[dict[str, Any]] = []
    for product in CATALOG.values():
        if normalized_category and product.category != normalized_category:
            continue

        searchable = " ".join(
            [product.product_id, product.name, product.brand, product.category, *product.tags]
        ).lower()
        if tokens and not all(tok in searchable for tok in tokens):
            # Fallback to any-token match for multi-word descriptive queries
            if not any(tok in searchable for tok in tokens):
                continue

        best = _best_offer(product, in_stock_only=in_stock_only, retailer_filter=retailer_set)
        if best is None:
            continue

        landed_price = round(best.current_price + best.shipping_cost, 2)
        if max_price_usd is not None and landed_price > max_price_usd:
            continue

        advertised_discount = (
            round(((best.list_price - best.current_price) / best.list_price) * 100.0, 1)
            if best.list_price > 0
            else 0.0
        )
        if advertised_discount < min_discount_pct:
            continue

        deal_score, is_fake_deal = _compute_deal_score(product, best)
        results.append(
            {
                "product_id": product.product_id,
                "name": product.name,
                "brand": product.brand,
                "category": product.category,
                "rating": product.rating,
                "review_count": product.review_count,
                "best_retailer": best.retailer,
                "current_price_usd": best.current_price,
                "list_price_usd": best.list_price,
                "shipping_usd": best.shipping_cost,
                "landed_price_usd": landed_price,
                "advertised_discount_pct": advertised_discount,
                "avg_90d_price_usd": product.price_history.avg_90d_price,
                "all_time_low_usd": product.price_history.all_time_low,
                "deal_score": deal_score,
                "is_fake_deal_warning": is_fake_deal,
                "membership_required": best.membership_required,
                "delivery_days": best.estimated_delivery_days,
            }
        )

    sort_key_map = {
        "deal_score_desc": lambda x: (-x["deal_score"], x["landed_price_usd"]),
        "price_asc": lambda x: x["landed_price_usd"],
        "price_desc": lambda x: -x["landed_price_usd"],
        "discount_desc": lambda x: -x["advertised_discount_pct"],
        "rating_desc": lambda x: (-x["rating"], -x["review_count"]),
    }
    results.sort(key=sort_key_map[sort_by])
    top_results = results[:bounded_limit]

    # Store compact summary in session state for follow-up turns
    if tool_context is not None:
        tool_context.state["session:last_search_results"] = [
            {
                "product_id": r["product_id"],
                "name": r["name"],
                "best_retailer": r["best_retailer"],
                "landed_price_usd": r["landed_price_usd"],
            }
            for r in top_results
        ]

    if not top_results:
        return ToolResponse(
            status="not_found",
            data={"deals": [], "count": 0},
            metadata={"query": query, "category": normalized_category},
        ).model_dump()

    return ToolResponse(
        status="success",
        data={"deals": top_results, "count": len(top_results)},
        metadata={"holiday_season": HOLIDAY_CALENDAR["season"], "sort_by": sort_by},
    ).model_dump()


def compare_product_prices(
    product_id_or_name: str,
    estimated_tax_rate_pct: float = 8.25,
) -> dict[str, Any]:
    """Compare offers across all retailers for a specific product including landed cost and return windows.

    Args:
        product_id_or_name: Product ID (e.g., "sony-wh1000xm5") or product name substring.
        estimated_tax_rate_pct: Estimated sales tax rate percentage (0-15) to compute total landed cost.

    Returns:
        Cross-retailer comparison table sorted by total landed cost, plus savings vs highest offer.
    """
    if not (0.0 <= estimated_tax_rate_pct <= 15.0):
        return ToolResponse(
            status="error",
            error="estimated_tax_rate_pct must be between 0 and 15.",
        ).model_dump()

    product = _resolve_product(product_id_or_name)
    if product is None:
        return ToolResponse(
            status="not_found",
            error=f"No catalog product found matching '{product_id_or_name}'.",
        ).model_dump()

    comparisons: list[dict[str, Any]] = []
    for offer in product.offers:
        subtotal = offer.current_price + offer.shipping_cost
        est_tax = round(offer.current_price * (estimated_tax_rate_pct / 100.0), 2)
        total_landed = round(subtotal + est_tax, 2)
        comparisons.append(
            {
                "retailer": offer.retailer,
                "current_price_usd": offer.current_price,
                "list_price_usd": offer.list_price,
                "shipping_usd": offer.shipping_cost,
                "estimated_tax_usd": est_tax,
                "total_landed_usd": total_landed,
                "in_stock": offer.in_stock,
                "estimated_delivery_days": offer.estimated_delivery_days,
                "return_window_days": offer.return_window_days,
                "membership_required": offer.membership_required,
                "product_url": offer.product_url,
            }
        )

    comparisons.sort(key=lambda c: (not c["in_stock"], c["total_landed_usd"]))
    in_stock_prices = [c["total_landed_usd"] for c in comparisons if c["in_stock"]]
    spread = round(max(in_stock_prices) - min(in_stock_prices), 2) if len(in_stock_prices) > 1 else 0.0

    return ToolResponse(
        status="success",
        data={
            "product_id": product.product_id,
            "product_name": product.name,
            "offers": comparisons,
            "recommended_retailer": comparisons[0]["retailer"] if comparisons else None,
            "savings_vs_highest_retailer_usd": spread,
        },
        metadata={"estimated_tax_rate_pct": estimated_tax_rate_pct},
    ).model_dump()


def check_price_history_and_buy_timing(product_id_or_name: str) -> dict[str, Any]:
    """Analyze 90-day price history and holiday trends to recommend BUY_NOW, WAIT, SET_ALERT, or AVOID_FAKE_DEAL.

    Args:
        product_id_or_name: Product ID or name substring.

    Returns:
        Detailed price authenticity verdict, historical benchmarks, and buy-timing recommendation.
    """
    product = _resolve_product(product_id_or_name)
    if product is None:
        return ToolResponse(
            status="not_found",
            error=f"No catalog product found matching '{product_id_or_name}'.",
        ).model_dump()

    best = _best_offer(product, in_stock_only=True)
    if best is None:
        return ToolResponse(
            status="success",
            data={
                "product_id": product.product_id,
                "product_name": product.name,
                "recommendation": "SET_ALERT",
                "confidence": 0.85,
                "rationale": "Currently out of stock across tracked retailers; set a restock & price alert.",
            },
        ).model_dump()

    hist = product.price_history
    current = best.current_price
    deal_score, is_fake_deal = _compute_deal_score(product, best)

    if is_fake_deal:
        recommendation = "AVOID_FAKE_DEAL"
        confidence = 0.94
        rationale = (
            f"Fake holiday discount detected! Advertised at ${current:.2f} (list ${best.list_price:.2f}), "
            f"but the 90-day average is ${hist.avg_90d_price:.2f} and all-time low is ${hist.all_time_low:.2f}. "
            "Wait for a genuine drop below $85 or choose an alternative."
        )
    elif current <= hist.all_time_low * 1.02:
        recommendation = "BUY_NOW"
        confidence = 0.95
        rationale = (
            f"Matches or beats the all-time low (${hist.all_time_low:.2f}) at {best.retailer} "
            f"and is {round((1 - current / hist.avg_90d_price) * 100, 1)}% below its 90-day average."
        )
    elif current <= hist.avg_90d_price * 0.90:
        recommendation = "BUY_NOW"
        confidence = 0.82
        rationale = (
            f"Strong holiday discount at ${current:.2f} vs 90-day average of ${hist.avg_90d_price:.2f}. "
            f"Could dip slightly toward all-time low (${hist.all_time_low:.2f}) on Black Friday, "
            "but extended holiday return windows protect against further drops."
        )
    else:
        recommendation = "WAIT"
        confidence = 0.78
        rationale = (
            f"Current price (${current:.2f}) is close to the 90-day average (${hist.avg_90d_price:.2f}). "
            f"Historically drops ~{hist.typical_holiday_drop_pct:.0f}% during Black Friday/Cyber Monday."
        )

    return ToolResponse(
        status="success",
        data={
            "product_id": product.product_id,
            "product_name": product.name,
            "best_retailer": best.retailer,
            "current_price_usd": current,
            "avg_90d_price_usd": hist.avg_90d_price,
            "min_90d_price_usd": hist.min_90d_price,
            "all_time_low_usd": hist.all_time_low,
            "last_black_friday_price_usd": hist.last_black_friday_price,
            "deal_score": deal_score,
            "is_fake_deal": is_fake_deal,
            "recommendation": recommendation,
            "confidence": confidence,
            "rationale": rationale,
            "holiday_calendar_note": HOLIDAY_CALENDAR["extended_holiday_return_policy"],
        },
    ).model_dump()

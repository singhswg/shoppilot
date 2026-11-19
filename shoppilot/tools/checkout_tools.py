"""High-stakes holiday checkout & order placement tool with explicit ADK HITL confirmation.

Uses ADK's native `tool_context.request_confirmation(...)` and `tool_context.tool_confirmation`
protocol (paired with `FunctionTool(..., require_confirmation=True)`) so no purchase is ever
executed without explicit human approval.
"""

from __future__ import annotations

import uuid
from typing import Any

from google.adk.tools.tool_context import ToolContext

from shoppilot.observability.logging_utils import get_logger
from shoppilot.observability.telemetry import get_metrics, get_tracer
from shoppilot.schemas import ToolResponse
from shoppilot.tools.coupon_tools import calculate_stacked_savings
from shoppilot.tools.deal_tools import _best_offer, _resolve_product

logger = get_logger(__name__)
tracer = get_tracer("shoppilot.hitl")


def place_holiday_order(
    product_id_or_name: str,
    retailer: str = "",
    quantity: int = 1,
    recipient: str = "Self",
    apply_stacked_coupons: bool = True,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Place a holiday purchase order after explicit Human-in-the-Loop (HITL) confirmation.

    ALWAYS pauses for human confirmation via ADK `request_confirmation` before finalizing
    any order, surfacing total landed cost, fake-deal status, and holiday budget impact.

    Args:
        product_id_or_name: Catalog product ID or name substring.
        retailer: Optional retailer name; defaults to the lowest in-stock offer.
        quantity: Number of units to order (1-10).
        recipient: Gift recipient name (used to update budget and watchlist).
        apply_stacked_coupons: Whether to apply eligible promo codes and cashback.

    Returns:
        Structured ToolResponse with `pending_confirmation`, `cancelled`, or `success` receipt.
    """
    if tool_context is None:
        return ToolResponse(
            status="error", error="ToolContext is required for HITL order placement."
        ).model_dump()

    if not (1 <= quantity <= 10):
        return ToolResponse(
            status="error", error="quantity must be between 1 and 10."
        ).model_dump()

    product = _resolve_product(product_id_or_name)
    if product is None:
        return ToolResponse(
            status="not_found",
            error=f"No catalog product found matching '{product_id_or_name}'.",
        ).model_dump()

    retailer_filter = {retailer.strip().lower()} if retailer.strip() else None
    offer = _best_offer(product, in_stock_only=True, retailer_filter=retailer_filter)
    if offer is None:
        return ToolResponse(
            status="not_found",
            error=f"No in-stock offer found for '{product.name}'"
            + (f" at '{retailer}'." if retailer else "."),
        ).model_dump()

    base_total = round((offer.current_price + offer.shipping_cost) * quantity, 2)
    effective_total = base_total
    applied_coupons: list[dict[str, Any]] = []
    if apply_stacked_coupons:
        savings = calculate_stacked_savings(
            retailer=offer.retailer,
            item_price_usd=base_total,
            tool_context=tool_context,
        )
        if savings["status"] == "success":
            effective_total = float(savings["data"]["checkout_price_usd"])
            applied_coupons = list(savings["data"]["applied_stack"])

    # Compute budget impact for the confirmation prompt
    budget: dict[str, Any] = dict(
        tool_context.state.get(
            "user:holiday_budget",
            {"total_budget_usd": 0.0, "spent_usd": 0.0, "recipients": {}, "purchases": []},
        )
    )
    total_cap = float(budget.get("total_budget_usd", 0.0))
    spent_so_far = float(budget.get("spent_usd", 0.0))
    projected_spent = round(spent_so_far + effective_total, 2)
    would_exceed_budget = bool(total_cap > 0 and projected_spent > total_cap)
    is_fake_deal = offer.current_price > product.price_history.avg_90d_price

    confirmation_payload = {
        "action": "place_holiday_order",
        "product_id": product.product_id,
        "product_name": product.name,
        "retailer": offer.retailer,
        "quantity": quantity,
        "recipient": recipient.strip() or "Self",
        "checkout_total_usd": effective_total,
        "applied_coupons": applied_coupons,
        "would_exceed_budget": would_exceed_budget,
        "is_fake_deal_warning": is_fake_deal,
    }

    metrics = get_metrics()
    confirmation = getattr(tool_context, "tool_confirmation", None)

    # Step 1: Request explicit human confirmation if not yet provided
    if confirmation is None:
        metrics.inc("hitl_confirmations_requested")
        warning_parts: list[str] = []
        if would_exceed_budget:
            warning_parts.append(
                f"WARNING: exceeds holiday budget (${projected_spent:.2f} / ${total_cap:.2f})"
            )
        if is_fake_deal:
            warning_parts.append("WARNING: flagged as an inflated fake holiday deal")
        warning_suffix = f" [{' | '.join(warning_parts)}]" if warning_parts else ""

        hint = (
            f"Approve purchasing {quantity}x {product.name} from {offer.retailer} "
            f"for ${effective_total:.2f} (recipient: {confirmation_payload['recipient']})?"
            f"{warning_suffix}"
        )
        tool_context.request_confirmation(hint=hint, payload=confirmation_payload)

        with tracer.start_as_current_span("shoppilot.hitl.request") as span:
            span.set_attribute("shoppilot.hitl.action", "place_holiday_order")
            span.set_attribute("shoppilot.hitl.amount_usd", effective_total)
            span.set_attribute("shoppilot.hitl.would_exceed_budget", would_exceed_budget)

        logger.info(
            "HITL confirmation requested for order placement",
            extra={
                "structured": {
                    "event": "hitl_requested",
                    "product_id": product.product_id,
                    "retailer": offer.retailer,
                    "checkout_total_usd": effective_total,
                    "would_exceed_budget": would_exceed_budget,
                }
            },
        )
        return ToolResponse(
            status="pending_confirmation",
            data={
                "message": "Human confirmation required before placing this order.",
                "hint": hint,
                "order_preview": confirmation_payload,
            },
            metadata={"hitl_required": True},
        ).model_dump()

    # Step 2: Handle explicit rejection by human
    if not confirmation.confirmed:
        metrics.inc("hitl_confirmations_rejected")
        logger.info(
            "HITL order placement rejected by user",
            extra={
                "structured": {
                    "event": "hitl_rejected",
                    "product_id": product.product_id,
                    "checkout_total_usd": effective_total,
                }
            },
        )
        return ToolResponse(
            status="cancelled",
            data={
                "message": "Order cancelled by user during confirmation.",
                "product_id": product.product_id,
                "retailer": offer.retailer,
            },
            metadata={"hitl_confirmed": False},
        ).model_dump()

    # Step 3: Approved -> finalize order & update persistent budget/watchlist state
    metrics.inc("hitl_confirmations_approved")
    order_id = f"SP-{uuid.uuid4().hex[:8].upper()}"

    rec_key = recipient.strip() or "Self"
    budget["spent_usd"] = projected_spent
    recipients = dict(budget.get("recipients", {}))
    rec_entry = dict(recipients.get(rec_key, {"allocated_usd": 0.0, "spent_usd": 0.0}))
    rec_entry["spent_usd"] = round(float(rec_entry["spent_usd"]) + effective_total, 2)
    recipients[rec_key] = rec_entry
    budget["recipients"] = recipients
    purchases = list(budget.get("purchases", []))
    purchases.append(
        {
            "order_id": order_id,
            "recipient": rec_key,
            "amount_usd": effective_total,
            "note": f"{quantity}x {product.name} ({offer.retailer})",
        }
    )
    budget["purchases"] = purchases
    tool_context.state["user:holiday_budget"] = budget

    # Mark item as purchased in user:watchlist if present
    watchlist = list(tool_context.state.get("user:watchlist", []))
    for item in watchlist:
        if item.get("product_id") == product.product_id:
            item["status"] = "purchased"
    tool_context.state["user:watchlist"] = watchlist

    with tracer.start_as_current_span("shoppilot.hitl.approved") as span:
        span.set_attribute("shoppilot.hitl.action", "place_holiday_order")
        span.set_attribute("shoppilot.hitl.order_id", order_id)
        span.set_attribute("shoppilot.hitl.amount_usd", effective_total)

    return ToolResponse(
        status="success",
        data={
            "order_id": order_id,
            "product_id": product.product_id,
            "product_name": product.name,
            "retailer": offer.retailer,
            "quantity": quantity,
            "recipient": rec_key,
            "charged_usd": effective_total,
            "applied_coupons": applied_coupons,
            "estimated_delivery_days": offer.estimated_delivery_days,
            "return_window_days": offer.return_window_days,
        },
        metadata={"hitl_confirmed": True},
    ).model_dump()

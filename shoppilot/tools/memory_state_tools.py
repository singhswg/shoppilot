"""Stateful ADK tools for user preferences, holiday watchlist, gift budget, alerts, and loop control.

Uses ADK scoped state prefixes:
- `user:*` -> Persists across sessions for the same user (preferences, budget, watchlist, alerts).
- `session:*` -> Persists within the active conversation session.
"""

from __future__ import annotations

import uuid
from typing import Any

from google.adk.tools.tool_context import ToolContext

from shoppilot.config import get_settings
from shoppilot.schemas import PriceAlertRule, ToolResponse, WatchlistItem
from shoppilot.tools.deal_tools import _best_offer, _resolve_product


def manage_user_preferences(
    action: str,
    preferred_retailers: list[str] | None = None,
    memberships: list[str] | None = None,
    credit_cards: list[str] | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Read or update persistent user shopping preferences (`user:preferences`).

    Args:
        action: Either "get" or "update".
        preferred_retailers: Optional list of favorite retailers (e.g., ["Amazon", "Best Buy", "Target"]).
        memberships: Optional list of active memberships (e.g., ["Prime", "Costco", "Target Circle", "REI Co-op"]).
        credit_cards: Optional list of cashback cards (e.g., ["Prime Visa", "Target Circle Card"]).

    Returns:
        Current persisted user preferences.
    """
    if tool_context is None:
        return ToolResponse(status="error", error="ToolContext is required for preference storage.").model_dump()

    normalized_action = action.strip().lower()
    if normalized_action not in {"get", "update"}:
        return ToolResponse(status="error", error="action must be 'get' or 'update'.").model_dump()

    prefs: dict[str, Any] = dict(
        tool_context.state.get(
            "user:preferences",
            {"preferred_retailers": [], "memberships": [], "credit_cards": []},
        )
    )

    if normalized_action == "update":
        if preferred_retailers is not None:
            prefs["preferred_retailers"] = sorted({r.strip() for r in preferred_retailers if r.strip()})
        if memberships is not None:
            prefs["memberships"] = sorted({m.strip() for m in memberships if m.strip()})
        if credit_cards is not None:
            prefs["credit_cards"] = sorted({c.strip() for c in credit_cards if c.strip()})
        tool_context.state["user:preferences"] = prefs

    return ToolResponse(status="success", data={"preferences": prefs}).model_dump()


def manage_shopping_watchlist(
    action: str,
    product_id_or_name: str = "",
    target_price_usd: float | None = None,
    recipient: str = "Self",
    priority: str = "medium",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Add, remove, or list tracked holiday gifts in persistent `user:watchlist`.

    Args:
        action: One of "list", "add", "remove", "mark_purchased".
        product_id_or_name: Product ID or name substring (required for add/remove/mark_purchased).
        target_price_usd: Desired target price in USD (required for add).
        recipient: Gift recipient name (e.g., "Mom", "Partner", "Self").
        priority: One of "high", "medium", "low".

    Returns:
        Updated watchlist with live best-price comparison and target-met flags.
    """
    if tool_context is None:
        return ToolResponse(status="error", error="ToolContext is required for watchlist storage.").model_dump()

    settings = get_settings()
    act = action.strip().lower()
    if act not in {"list", "add", "remove", "mark_purchased"}:
        return ToolResponse(
            status="error",
            error="action must be one of: list, add, remove, mark_purchased.",
        ).model_dump()

    watchlist: list[dict[str, Any]] = list(tool_context.state.get("user:watchlist", []))

    if act == "list":
        return ToolResponse(
            status="success",
            data={"watchlist": watchlist, "count": len(watchlist)},
        ).model_dump()

    if not product_id_or_name.strip():
        return ToolResponse(status="error", error="product_id_or_name is required.").model_dump()

    product = _resolve_product(product_id_or_name)
    resolved_id = product.product_id if product else product_id_or_name.strip().lower().replace(" ", "-")
    resolved_name = product.name if product else product_id_or_name.strip()

    if act == "add":
        if target_price_usd is None or target_price_usd <= 0:
            return ToolResponse(
                status="error", error="target_price_usd must be a positive number."
            ).model_dump()
        if priority not in {"high", "medium", "low"}:
            return ToolResponse(
                status="error", error="priority must be high, medium, or low."
            ).model_dump()
        if len(watchlist) >= settings.max_watchlist_items:
            return ToolResponse(
                status="error",
                error=f"Watchlist limit ({settings.max_watchlist_items}) reached.",
            ).model_dump()

        best = _best_offer(product) if product else None
        best_price = best.current_price if best else None
        status_val = "target_met" if (best_price is not None and best_price <= target_price_usd) else "watching"

        item = WatchlistItem(
            product_id=resolved_id,
            product_name=resolved_name,
            recipient=recipient.strip() or "Self",
            target_price_usd=round(target_price_usd, 2),
            current_best_price_usd=best_price,
            priority=priority,  # type: ignore[arg-type]
            status=status_val,  # type: ignore[arg-type]
        ).model_dump()

        # Upsert by (product_id, recipient)
        watchlist = [
            w
            for w in watchlist
            if not (w["product_id"] == resolved_id and w["recipient"].lower() == item["recipient"].lower())
        ]
        watchlist.append(item)
        tool_context.state["user:watchlist"] = watchlist
        return ToolResponse(
            status="success",
            data={"added_or_updated": item, "watchlist": watchlist, "count": len(watchlist)},
        ).model_dump()

    if act == "remove":
        before_len = len(watchlist)
        watchlist = [
            w
            for w in watchlist
            if w["product_id"] != resolved_id and resolved_id not in w["product_name"].lower()
        ]
        tool_context.state["user:watchlist"] = watchlist
        return ToolResponse(
            status="success",
            data={"removed_count": before_len - len(watchlist), "watchlist": watchlist},
        ).model_dump()

    # mark_purchased
    updated = False
    for w in watchlist:
        if w["product_id"] == resolved_id or resolved_id in w["product_name"].lower():
            w["status"] = "purchased"
            updated = True
    tool_context.state["user:watchlist"] = watchlist
    return ToolResponse(
        status="success" if updated else "not_found",
        data={"updated": updated, "watchlist": watchlist},
    ).model_dump()


def manage_budget_and_gift_plan(
    action: str,
    total_budget_usd: float | None = None,
    recipient: str = "",
    recipient_budget_usd: float | None = None,
    record_spend_usd: float | None = None,
    item_note: str = "",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Track overall holiday budget, per-recipient allocations, and actual spending (`user:holiday_budget`).

    Args:
        action: One of "summary", "set_total_budget", "set_recipient_budget", "record_purchase".
        total_budget_usd: Overall holiday budget cap in USD.
        recipient: Recipient name for allocation or purchase logging.
        recipient_budget_usd: Per-recipient budget cap in USD.
        record_spend_usd: Amount spent on a purchase in USD.
        item_note: Short description of the purchased gift.

    Returns:
        Updated budget summary with remaining headroom and over-budget warnings.
    """
    if tool_context is None:
        return ToolResponse(status="error", error="ToolContext is required for budget storage.").model_dump()

    settings = get_settings()
    act = action.strip().lower()
    if act not in {"summary", "set_total_budget", "set_recipient_budget", "record_purchase"}:
        return ToolResponse(
            status="error",
            error="action must be one of: summary, set_total_budget, set_recipient_budget, record_purchase.",
        ).model_dump()

    budget: dict[str, Any] = dict(
        tool_context.state.get(
            "user:holiday_budget",
            {
                "total_budget_usd": 0.0,
                "spent_usd": 0.0,
                "recipients": {},
                "purchases": [],
            },
        )
    )
    budget["recipients"] = dict(budget.get("recipients", {}))
    budget["purchases"] = list(budget.get("purchases", []))

    if act == "set_total_budget":
        if total_budget_usd is None or total_budget_usd <= 0 or total_budget_usd > settings.max_budget_usd:
            return ToolResponse(
                status="error",
                error=f"total_budget_usd must be between 0 and {settings.max_budget_usd}.",
            ).model_dump()
        budget["total_budget_usd"] = round(total_budget_usd, 2)

    elif act == "set_recipient_budget":
        if not recipient.strip() or recipient_budget_usd is None or recipient_budget_usd <= 0:
            return ToolResponse(
                status="error", error="recipient and positive recipient_budget_usd are required."
            ).model_dump()
        rec_key = recipient.strip()
        existing = budget["recipients"].get(rec_key, {"allocated_usd": 0.0, "spent_usd": 0.0})
        existing["allocated_usd"] = round(recipient_budget_usd, 2)
        budget["recipients"][rec_key] = existing

    elif act == "record_purchase":
        if record_spend_usd is None or record_spend_usd <= 0:
            return ToolResponse(
                status="error", error="record_spend_usd must be positive."
            ).model_dump()
        rec_key = recipient.strip() or "Self"
        budget["spent_usd"] = round(float(budget["spent_usd"]) + record_spend_usd, 2)
        existing = budget["recipients"].get(rec_key, {"allocated_usd": 0.0, "spent_usd": 0.0})
        existing["spent_usd"] = round(float(existing["spent_usd"]) + record_spend_usd, 2)
        budget["recipients"][rec_key] = existing
        budget["purchases"].append(
            {
                "recipient": rec_key,
                "amount_usd": round(record_spend_usd, 2),
                "note": item_note.strip()[:120],
            }
        )

    tool_context.state["user:holiday_budget"] = budget

    total = float(budget["total_budget_usd"])
    spent = float(budget["spent_usd"])
    remaining = round(total - spent, 2) if total > 0 else None
    over_budget = bool(total > 0 and spent > total)

    return ToolResponse(
        status="success",
        data={
            "budget": budget,
            "remaining_usd": remaining,
            "over_budget_warning": over_budget,
        },
    ).model_dump()


def create_price_drop_alert(
    product_id_or_name: str,
    target_price_usd: float,
    notify_channel: str = "chat",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Register a persistent price-drop alert rule in `user:price_alerts`.

    Args:
        product_id_or_name: Product ID or name substring.
        target_price_usd: Alert trigger threshold in USD.
        notify_channel: Notification channel: "chat", "email_digest", or "push".

    Returns:
        Created alert rule and total active alerts count.
    """
    if tool_context is None:
        return ToolResponse(status="error", error="ToolContext is required for alerts.").model_dump()
    if target_price_usd <= 0:
        return ToolResponse(status="error", error="target_price_usd must be positive.").model_dump()
    if notify_channel not in {"chat", "email_digest", "push"}:
        return ToolResponse(
            status="error", error="notify_channel must be chat, email_digest, or push."
        ).model_dump()

    product = _resolve_product(product_id_or_name)
    resolved_id = product.product_id if product else product_id_or_name.strip().lower().replace(" ", "-")
    resolved_name = product.name if product else product_id_or_name.strip()

    rule = PriceAlertRule(
        alert_id=f"alert-{uuid.uuid4().hex[:8]}",
        product_id=resolved_id,
        product_name=resolved_name,
        target_price_usd=round(target_price_usd, 2),
        notify_channel=notify_channel,  # type: ignore[arg-type]
        active=True,
    ).model_dump()

    alerts: list[dict[str, Any]] = list(tool_context.state.get("user:price_alerts", []))
    alerts.append(rule)
    tool_context.state["user:price_alerts"] = alerts

    return ToolResponse(
        status="success",
        data={"alert": rule, "active_alerts_count": len(alerts)},
    ).model_dump()


def exit_bundle_loop(
    summary: str,
    total_bundle_cost_usd: float,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Terminate the iterative gift-bundle optimization LoopAgent once budget constraints are met.

    Args:
        summary: Final summary of the budget-compliant holiday gift bundle.
        total_bundle_cost_usd: Total net cost of the finalized bundle in USD.

    Returns:
        Confirmation dictionary and sets ADK escalate signal to exit the loop.
    """
    tool_context.state["session:final_bundle_summary"] = {
        "summary": summary,
        "total_bundle_cost_usd": round(total_bundle_cost_usd, 2),
    }
    tool_context.actions.escalate = True
    return ToolResponse(
        status="success",
        data={"loop_exited": True, "total_bundle_cost_usd": round(total_bundle_cost_usd, 2)},
    ).model_dump()

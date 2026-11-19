"""Tests for Human-in-the-Loop (HITL) confirmation hooks on high-stakes actions."""

from __future__ import annotations

from google.adk.tools import FunctionTool

from shoppilot import root_agent
from shoppilot.observability.telemetry import get_metrics
from shoppilot.tools import (
    manage_budget_and_gift_plan,
    manage_shopping_watchlist,
    place_holiday_order,
    requires_budget_confirmation,
)
from tests.conftest import DummyToolConfirmation


def test_agent_registers_adk_require_confirmation_hooks():
    planner = next(a for a in root_agent.sub_agents if a.name == "gift_budget_planner")
    function_tools = [t for t in planner.tools if isinstance(t, FunctionTool)]
    by_name = {t.name: t for t in function_tools}

    assert "place_holiday_order" in by_name
    assert by_name["place_holiday_order"]._require_confirmation is True

    assert "manage_budget_and_gift_plan" in by_name
    assert by_name["manage_budget_and_gift_plan"]._require_confirmation is requires_budget_confirmation


def test_requires_budget_confirmation_predicate():
    assert requires_budget_confirmation(action="summary") is False
    assert requires_budget_confirmation(action="record_purchase", record_spend_usd=50.0) is False
    assert requires_budget_confirmation(action="record_purchase", record_spend_usd=250.0) is True
    assert requires_budget_confirmation(action="set_total_budget", total_budget_usd=500.0) is False
    assert requires_budget_confirmation(action="set_total_budget", total_budget_usd=1500.0) is True


def test_place_holiday_order_full_hitl_lifecycle(tool_context):
    # Pre-seed budget ($200 cap so Sony headphones trigger over-budget warning) & watchlist
    manage_budget_and_gift_plan(
        action="set_total_budget", total_budget_usd=200.0, tool_context=tool_context
    )
    manage_shopping_watchlist(
        action="add",
        product_id_or_name="sony-wh1000xm5",
        target_price_usd=280.0,
        recipient="Sister",
        tool_context=tool_context,
    )

    # 1. Initial call pauses for explicit human confirmation
    pending = place_holiday_order(
        product_id_or_name="sony-wh1000xm5",
        recipient="Sister",
        tool_context=tool_context,
    )
    assert pending["status"] == "pending_confirmation"
    assert pending["metadata"]["hitl_required"] is True
    assert len(tool_context.confirmation_requests) == 1
    assert "exceeds holiday budget" in tool_context.confirmation_requests[0]["hint"]
    assert tool_context.state["user:holiday_budget"]["spent_usd"] == 0.0

    # 2. User rejects -> cancelled, no state mutation
    tool_context.tool_confirmation = DummyToolConfirmation(confirmed=False)
    rejected = place_holiday_order(
        product_id_or_name="sony-wh1000xm5",
        recipient="Sister",
        tool_context=tool_context,
    )
    assert rejected["status"] == "cancelled"
    assert tool_context.state["user:holiday_budget"]["spent_usd"] == 0.0

    # 3. User approves -> order placed, budget and watchlist updated
    tool_context.tool_confirmation = DummyToolConfirmation(confirmed=True)
    approved = place_holiday_order(
        product_id_or_name="sony-wh1000xm5",
        recipient="Sister",
        tool_context=tool_context,
    )
    assert approved["status"] == "success"
    assert approved["data"]["order_id"].startswith("SP-")
    assert tool_context.state["user:holiday_budget"]["spent_usd"] > 0.0
    assert tool_context.state["user:watchlist"][0]["status"] == "purchased"

    counters = get_metrics().snapshot()["counters"]
    assert counters["hitl_confirmations_requested"] == 1
    assert counters["hitl_confirmations_rejected"] == 1
    assert counters["hitl_confirmations_approved"] == 1


def test_place_holiday_order_flags_fake_deal_in_confirmation_hint(tool_context):
    res = place_holiday_order(
        product_id_or_name="generic-smart-air-fryer-pro",
        tool_context=tool_context,
    )
    assert res["status"] == "pending_confirmation"
    assert "fake holiday deal" in tool_context.confirmation_requests[0]["hint"].lower()


def test_manage_budget_conditional_hitl_for_high_value_or_over_budget(tool_context):
    manage_budget_and_gift_plan(
        action="set_total_budget", total_budget_usd=300.0, tool_context=tool_context
    )

    # Below threshold ($250) and within budget -> executes immediately
    small = manage_budget_and_gift_plan(
        action="record_purchase",
        recipient="Friend",
        record_spend_usd=40.0,
        item_note="YETI Tumbler",
        tool_context=tool_context,
    )
    assert small["status"] == "success"
    assert len(tool_context.confirmation_requests) == 0

    # High-value / over-budget ($280 pushes spent to $320 > $300) -> pauses for HITL
    pending = manage_budget_and_gift_plan(
        action="record_purchase",
        recipient="Partner",
        record_spend_usd=280.0,
        item_note="Headphones",
        tool_context=tool_context,
    )
    assert pending["status"] == "pending_confirmation"
    assert len(tool_context.confirmation_requests) == 1

    # Approve -> commits spend
    tool_context.tool_confirmation = DummyToolConfirmation(confirmed=True)
    approved = manage_budget_and_gift_plan(
        action="record_purchase",
        recipient="Partner",
        record_spend_usd=280.0,
        item_note="Headphones",
        tool_context=tool_context,
    )
    assert approved["status"] == "success"
    assert approved["data"]["over_budget_warning"] is True
    assert approved["data"]["budget"]["spent_usd"] == 320.0

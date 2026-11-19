"""Unit tests for ShopPilot tools: deal search, fake-deal detection, coupon stacking, and state."""

from __future__ import annotations

from shoppilot.tools import (
    calculate_stacked_savings,
    check_price_history_and_buy_timing,
    compare_product_prices,
    create_price_drop_alert,
    exit_bundle_loop,
    find_coupons_and_cashback,
    manage_budget_and_gift_plan,
    manage_shopping_watchlist,
    manage_user_preferences,
    search_holiday_deals,
)


def test_search_holiday_deals_returns_sorted_results_and_updates_session_state(tool_context):
    res = search_holiday_deals(
        query="headphones",
        max_price_usd=350.0,
        sort_by="deal_score_desc",
        tool_context=tool_context,
    )
    assert res["status"] == "success"
    assert res["data"]["count"] >= 1
    top = res["data"]["deals"][0]
    assert top["product_id"] == "sony-wh1000xm5"
    assert top["best_retailer"] == "Best Buy"
    assert top["is_fake_deal_warning"] is False
    assert "session:last_search_results" in tool_context.state


def test_search_holiday_deals_input_validation():
    assert search_holiday_deals(category="invalid_cat")["status"] == "error"
    assert search_holiday_deals(sort_by="bogus")["status"] == "error"
    assert search_holiday_deals(max_price_usd=-50.0)["status"] == "error"
    assert search_holiday_deals(min_discount_pct=99.0)["status"] == "error"
    assert search_holiday_deals(query="a" * 500)["status"] == "error"


def test_compare_product_prices_calculates_landed_cost_and_spread():
    res = compare_product_prices("sony-wh1000xm5", estimated_tax_rate_pct=10.0)
    assert res["status"] == "success"
    assert res["data"]["recommended_retailer"] == "Best Buy"
    assert res["data"]["savings_vs_highest_retailer_usd"] > 0
    best_offer = res["data"]["offers"][0]
    assert best_offer["estimated_tax_usd"] == 28.0
    assert best_offer["total_landed_usd"] == 307.99


def test_check_price_history_detects_genuine_all_time_low_and_fake_holiday_deal():
    genuine = check_price_history_and_buy_timing("sony-wh1000xm5")
    assert genuine["status"] == "success"
    assert genuine["data"]["recommendation"] == "BUY_NOW"
    assert genuine["data"]["is_fake_deal"] is False

    fake = check_price_history_and_buy_timing("generic-smart-air-fryer-pro")
    assert fake["status"] == "success"
    assert fake["data"]["recommendation"] == "AVOID_FAKE_DEAL"
    assert fake["data"]["is_fake_deal"] is True


def test_coupon_discovery_and_stacked_savings_with_user_preferences(tool_context):
    manage_user_preferences(
        action="update",
        memberships=["Target Circle", "Target Circle Card"],
        preferred_retailers=["Target", "Best Buy"],
        tool_context=tool_context,
    )

    coupons = find_coupons_and_cashback("Target", cart_subtotal_usd=100.0, tool_context=tool_context)
    assert coupons["status"] == "success"
    assert all(o["user_eligible_now"] for o in coupons["data"]["offers"])

    stacked = calculate_stacked_savings("Target", item_price_usd=100.0, tool_context=tool_context)
    assert stacked["status"] == "success"
    # $15 off ($85 checkout) + 5% cashback ($4.25) = $19.25 total savings -> $80.75 net
    assert stacked["data"]["upfront_discount_usd"] == 15.0
    assert stacked["data"]["cashback_rewards_usd"] == 4.25
    assert stacked["data"]["effective_net_price_usd"] == 80.75


def test_watchlist_budget_alerts_and_loop_exit_state(tool_context):
    # Set budget and record purchase
    b1 = manage_budget_and_gift_plan(
        action="set_total_budget", total_budget_usd=500.0, tool_context=tool_context
    )
    assert b1["status"] == "success"
    assert b1["data"]["remaining_usd"] == 500.0

    b2 = manage_budget_and_gift_plan(
        action="record_purchase",
        recipient="Nephew",
        record_spend_usd=67.99,
        item_note="LEGO Millennium Falcon",
        tool_context=tool_context,
    )
    assert b2["data"]["remaining_usd"] == 432.01
    assert b2["data"]["over_budget_warning"] is False

    # Watchlist add (target already met at $67.99 vs $70 target)
    w1 = manage_shopping_watchlist(
        action="add",
        product_id_or_name="lego-star-wars-millennium-falcon",
        target_price_usd=70.0,
        recipient="Nephew",
        priority="high",
        tool_context=tool_context,
    )
    assert w1["status"] == "success"
    assert w1["data"]["added_or_updated"]["status"] == "target_met"

    # Price alert
    a1 = create_price_drop_alert(
        product_id_or_name="sony-wh1000xm5",
        target_price_usd=250.0,
        notify_channel="chat",
        tool_context=tool_context,
    )
    assert a1["status"] == "success"
    assert a1["data"]["active_alerts_count"] == 1

    # LoopAgent exit signal
    exit_res = exit_bundle_loop(
        summary="3 gifts under $300", total_bundle_cost_usd=265.50, tool_context=tool_context
    )
    assert exit_res["status"] == "success"
    assert tool_context.actions.escalate is True
    assert tool_context.state["session:final_bundle_summary"]["total_bundle_cost_usd"] == 265.5

"""ShopPilot ADK tools for deal discovery, pricing intelligence, coupons, and stateful planning."""

from shoppilot.tools.coupon_tools import calculate_stacked_savings, find_coupons_and_cashback
from shoppilot.tools.deal_tools import (
    check_price_history_and_buy_timing,
    compare_product_prices,
    search_holiday_deals,
)
from shoppilot.tools.memory_state_tools import (
    create_price_drop_alert,
    exit_bundle_loop,
    manage_budget_and_gift_plan,
    manage_shopping_watchlist,
    manage_user_preferences,
)

__all__ = [
    "calculate_stacked_savings",
    "check_price_history_and_buy_timing",
    "compare_product_prices",
    "create_price_drop_alert",
    "exit_bundle_loop",
    "find_coupons_and_cashback",
    "manage_budget_and_gift_plan",
    "manage_shopping_watchlist",
    "manage_user_preferences",
    "search_holiday_deals",
]

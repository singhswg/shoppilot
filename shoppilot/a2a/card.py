"""Explicit A2A AgentCard definition for Google Cloud Agent Registry & Gemini Enterprise."""

from __future__ import annotations

from typing import Any

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)
from google.protobuf.json_format import MessageToDict

from shoppilot.config import Settings, get_settings


def build_agent_card(settings: Settings | None = None) -> AgentCard:
    """Build the canonical A2A AgentCard published at `/.well-known/agent-card.json`."""
    cfg = settings or get_settings()
    base_url = cfg.public_base_url.rstrip("/")

    return AgentCard(
        name="ShopPilot Holiday Shopping Assistant",
        description=(
            "Automated holiday shopping assistant built with Google ADK. Discovers verified "
            "multi-retailer deals, detects inflated fake holiday discounts using 90-day price "
            "history, stacks coupons and cashback rewards, and manages holiday gift budgets."
        ),
        version=cfg.service_version,
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/a2a",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        provider=AgentProvider(
            organization="ShopPilot",
            url=base_url,
        ),
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=False,
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="holiday_deal_discovery",
                name="Holiday Deal Discovery & Price Comparison",
                description=(
                    "Searches across major retailers (Amazon, Best Buy, Target, Walmart, Costco, "
                    "REI), computes total landed costs, and ranks offers by deal score."
                ),
                tags=["shopping", "holiday-deals", "price-comparison", "retail"],
                examples=[
                    "Find the best holiday deals on noise-canceling headphones under $300.",
                    "Compare prices for the LG 65-inch C4 OLED TV across Costco and Best Buy.",
                ],
            ),
            AgentSkill(
                id="fake_deal_detection_and_buy_timing",
                name="Fake Deal Detection & Buy-Timing Advisor",
                description=(
                    "Audits 90-day price history and past Black Friday lows to detect artificially "
                    "inflated MSRP sales and issue BUY_NOW, WAIT, SET_ALERT, or AVOID_FAKE_DEAL."
                ),
                tags=["price-history", "black-friday", "cyber-monday", "fraud-detection"],
                examples=[
                    "Is the UltraChef Smart Air Fryer Pro a real holiday deal or a fake markup?",
                    "Should I buy the Sony WH-1000XM5 now or wait for Black Friday?",
                ],
            ),
            AgentSkill(
                id="coupon_and_cashback_stacking",
                name="Coupon & Cashback Stacking Calculator",
                description=(
                    "Finds active holiday promo codes, cashback portals (Rakuten, TopCashback), "
                    "and credit card multipliers to calculate effective net price."
                ),
                tags=["coupons", "cashback", "promo-codes", "savings"],
                examples=[
                    "What coupons and cashback can I stack on a $280 Best Buy order?",
                    "Calculate my effective net price at Target with Target Circle.",
                ],
            ),
            AgentSkill(
                id="gift_budget_and_watchlist_planner",
                name="Gift Budget, Watchlist & Multi-Gift Bundle Optimizer",
                description=(
                    "Persists user memberships, holiday budgets, per-recipient allocations, "
                    "watchlists, price-drop alerts, and optimizes multi-recipient gift bundles."
                ),
                tags=["budget", "gift-list", "watchlist", "price-alerts", "planning"],
                examples=[
                    "Set my holiday budget to $600 and add Sony WH-1000XM5 with a $280 target.",
                    "Plan a holiday gift bundle for Mom, Dad, and my nephew under $300 total.",
                ],
            ),
        ],
    )


def agent_card_to_dict(card: AgentCard) -> dict[str, Any]:
    """Serialize an A2A protobuf AgentCard to standard camelCase JSON dict."""
    return dict(MessageToDict(card, preserving_proto_field_name=False))

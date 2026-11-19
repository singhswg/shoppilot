"""ShopPilot multi-agent orchestration using Google ADK.

Architecture:
    root_agent (shoppilot - Holiday Shopping Concierge)
    ├── deal_discovery_pipeline (SequentialAgent)
    │   ├── parallel_market_scanner (ParallelAgent)
    │   │   ├── catalog_deal_hunter      -> output_key: catalog_findings
    │   │   ├── coupon_and_cashback_scout -> output_key: coupon_findings
    │   │   └── price_timing_analyst     -> output_key: timing_findings
    │   └── deal_verifier_and_ranker     -> output_key: verified_deal_report
    ├── gift_budget_planner (LlmAgent)
    └── gift_bundle_optimizer (LoopAgent, max_iterations=2)
        ├── bundle_proposer              -> output_key: bundle_proposal
        └── bundle_budget_auditor        -> calls exit_bundle_loop on pass
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.tools import load_memory

from shoppilot.config import get_settings
from shoppilot.observability.callbacks import (
    after_agent_callback,
    after_model_callback,
    after_tool_callback,
    before_model_callback,
    before_tool_callback,
)
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


def build_root_agent() -> LlmAgent:
    """Construct the full ShopPilot multi-agent hierarchy."""
    settings = get_settings()
    fast_model = settings.shoppilot_model
    complex_model = settings.shoppilot_complex_model

    # -------------------------------------------------------------------------
    # Branch 1: Parallel Market Scanner + Sequential Verification Pipeline
    # -------------------------------------------------------------------------
    catalog_deal_hunter = LlmAgent(
        name="catalog_deal_hunter",
        model=fast_model,
        description="Searches holiday deals across retailers and compares total landed prices.",
        instruction=(
            "You are the Catalog Deal Hunter for ShopPilot. "
            "Use `search_holiday_deals` to find the best matching products for the user's request, "
            "and call `compare_product_prices` on the top 1-2 candidates to get full cross-retailer "
            "landed costs (including shipping, tax, delivery speed, and return windows). "
            "Return a concise, factual summary of product IDs, retailers, prices, and stock status."
        ),
        tools=[search_holiday_deals, compare_product_prices],
        output_key="catalog_findings",
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    coupon_and_cashback_scout = LlmAgent(
        name="coupon_and_cashback_scout",
        model=fast_model,
        description="Discovers stackable promo codes, cashback portals, and credit card rewards.",
        instruction=(
            "You are the Coupon & Cashback Scout for ShopPilot. "
            "Based on the user's request and preferred retailers/memberships in context, "
            "call `find_coupons_and_cashback` for relevant retailers (e.g., Best Buy, Amazon, Target, Walmart, Costco, REI) "
            "and `calculate_stacked_savings` when a price point is known. "
            "Always clearly separate upfront promo codes from cashback rewards and note membership requirements."
        ),
        tools=[find_coupons_and_cashback, calculate_stacked_savings],
        output_key="coupon_findings",
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    price_timing_analyst = LlmAgent(
        name="price_timing_analyst",
        model=fast_model,
        description="Audits 90-day price history to flag fake holiday sales and advise BUY_NOW vs WAIT.",
        instruction=(
            "You are the Price History & Buy-Timing Analyst for ShopPilot. "
            "First identify relevant product(s) using `search_holiday_deals` if needed, then call "
            "`check_price_history_and_buy_timing` on the top candidate(s). "
            "Explicitly flag any fake holiday discounts where current price exceeds the 90-day average, "
            "and report the BUY_NOW / WAIT / SET_ALERT / AVOID_FAKE_DEAL verdict with confidence."
        ),
        tools=[search_holiday_deals, check_price_history_and_buy_timing],
        output_key="timing_findings",
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    parallel_market_scanner = ParallelAgent(
        name="parallel_market_scanner",
        description="Concurrently scans retailer prices, stackable coupons/cashback, and 90-day price history.",
        sub_agents=[
            catalog_deal_hunter,
            coupon_and_cashback_scout,
            price_timing_analyst,
        ],
    )

    deal_verifier_and_ranker = LlmAgent(
        name="deal_verifier_and_ranker",
        model=complex_model,
        description="Synthesizes parallel market intelligence into a verified, ranked holiday deal report.",
        instruction=(
            "You are the Deal Verifier & Ranker for ShopPilot.\n"
            "Synthesize the findings gathered in parallel:\n"
            "- Catalog & Price Comparison: {catalog_findings?}\n"
            "- Coupons & Cashback: {coupon_findings?}\n"
            "- Price History & Timing: {timing_findings?}\n\n"
            "Produce a clear, structured holiday deal recommendation:\n"
            "1. Rank top genuine deals by effective net price (after stackable coupons + cashback) and deal authenticity.\n"
            "2. Prominently warn the user if any candidate is a FAKE HOLIDAY DEAL.\n"
            "3. State the exact BUY_NOW / WAIT / SET_ALERT recommendation, best retailer, delivery speed, and holiday return window.\n"
            "4. Check if the purchase fits the user's remaining holiday budget (if set) and offer to add it to their watchlist or set a price alert."
        ),
        output_key="verified_deal_report",
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    deal_discovery_pipeline = SequentialAgent(
        name="deal_discovery_pipeline",
        description=(
            "End-to-end holiday deal research pipeline: runs parallel price, coupon, and "
            "price-history analysis, then synthesizes a verified recommendation."
        ),
        sub_agents=[parallel_market_scanner, deal_verifier_and_ranker],
    )

    # -------------------------------------------------------------------------
    # Branch 2: Stateful Gift List, Watchlist, Preferences & Budget Planner
    # -------------------------------------------------------------------------
    gift_budget_planner = LlmAgent(
        name="gift_budget_planner",
        model=fast_model,
        description=(
            "Manages persistent user preferences, holiday budgets, per-recipient allocations, "
            "shopping watchlists, and price-drop alerts."
        ),
        instruction=(
            "You are the Gift & Budget Planner for ShopPilot. "
            "Help users save their memberships/preferred retailers (`manage_user_preferences`), "
            "set or review their total and per-recipient holiday budgets (`manage_budget_and_gift_plan`), "
            "manage their tracked gift watchlist (`manage_shopping_watchlist`), and create price-drop alerts "
            "(`create_price_drop_alert`). Use `load_memory` when the user references past conversations or "
            "previously discussed gift recipients. Always confirm saved changes clearly."
        ),
        tools=[
            manage_user_preferences,
            manage_shopping_watchlist,
            manage_budget_and_gift_plan,
            create_price_drop_alert,
            load_memory,
        ],
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    # -------------------------------------------------------------------------
    # Branch 3: Iterative Budget-Constrained Gift Bundle Optimizer (LoopAgent)
    # -------------------------------------------------------------------------
    bundle_proposer = LlmAgent(
        name="bundle_proposer",
        model=fast_model,
        description="Proposes or refines a multi-recipient holiday gift bundle using real deals and stacked coupons.",
        instruction=(
            "You are the Holiday Gift Bundle Proposer. "
            "Build a multi-gift holiday shopping bundle that matches all requested recipients and stays "
            "under the user's budget cap. Use `search_holiday_deals` and `calculate_stacked_savings`. "
            "If previous auditor feedback exists ({bundle_audit?}), swap out expensive or fake-deal items "
            "to satisfy the budget and quality constraints."
        ),
        tools=[search_holiday_deals, calculate_stacked_savings],
        output_key="bundle_proposal",
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    bundle_budget_auditor = LlmAgent(
        name="bundle_budget_auditor",
        model=fast_model,
        description="Audits a proposed gift bundle against budget constraints and exits the loop once valid.",
        instruction=(
            "You are the Bundle Budget Auditor. "
            "Review the proposed bundle: {bundle_proposal?}\n"
            "Check the user's budget using `manage_budget_and_gift_plan(action='summary')` (or the budget stated in the prompt). "
            "Verify that:\n"
            "1. Total net cost is within the budget cap.\n"
            "2. No item is flagged as a fake holiday deal.\n"
            "If ALL constraints are met, you MUST call `exit_bundle_loop` with a concise final summary and total cost. "
            "Otherwise, DO NOT call `exit_bundle_loop`; instead output specific, actionable instructions on which item(s) to swap."
        ),
        tools=[manage_budget_and_gift_plan, exit_bundle_loop],
        output_key="bundle_audit",
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
    )

    gift_bundle_optimizer = LoopAgent(
        name="gift_bundle_optimizer",
        description=(
            "Iteratively builds and audits a multi-gift holiday bundle until it fits within "
            "the user's budget and avoids fake holiday deals."
        ),
        sub_agents=[bundle_proposer, bundle_budget_auditor],
        max_iterations=2,
    )

    # -------------------------------------------------------------------------
    # Root Concierge & Router Agent
    # -------------------------------------------------------------------------
    return LlmAgent(
        name="shoppilot",
        model=complex_model,
        description=(
            "ShopPilot: Automated Holiday Shopping Assistant that discovers verified deals, "
            "compares cross-retailer prices, stacks coupons & cashback, detects fake discounts, "
            "and manages holiday gift budgets & watchlists."
        ),
        instruction=(
            "You are **ShopPilot**, an automated Holiday Shopping Assistant.\n"
            "Your mission is to help users get the best genuine holiday deals while staying on budget.\n\n"
            "Routing guidelines:\n"
            "- For finding deals, comparing prices, checking coupons/cashback, or asking if a deal is worth buying now "
            "-> delegate to `deal_discovery_pipeline`.\n"
            "- For saving memberships/retailers, managing holiday budgets, tracking watchlists, or setting price alerts "
            "-> delegate to `gift_budget_planner`.\n"
            "- For planning a multi-gift holiday shopping list under a strict total budget (e.g., 'plan gifts for 3 people under $400') "
            "-> delegate to `gift_bundle_optimizer`.\n"
            "- Use `load_memory` if the user refers to preferences or gifts discussed in an earlier session.\n\n"
            "Always be transparent about pricing, highlight fake holiday markups, note membership requirements, "
            "and remind users about holiday shipping cutoffs when relevant."
        ),
        tools=[load_memory, manage_user_preferences],
        sub_agents=[
            deal_discovery_pipeline,
            gift_budget_planner,
            gift_bundle_optimizer,
        ],
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        before_tool_callback=before_tool_callback,
        after_tool_callback=after_tool_callback,
        after_agent_callback=after_agent_callback,
    )


root_agent = build_root_agent()

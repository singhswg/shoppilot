"""Tests for ShopPilot multi-agent orchestration topology and A2A Agent Card."""

from __future__ import annotations

from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent

from shoppilot import root_agent
from shoppilot.a2a import build_agent_card
from shoppilot.config import Settings


def test_root_agent_hierarchy_and_workflow_primitives():
    assert isinstance(root_agent, LlmAgent)
    assert root_agent.name == "shoppilot"

    sub_by_name = {agent.name: agent for agent in root_agent.sub_agents}
    assert set(sub_by_name.keys()) == {
        "deal_discovery_pipeline",
        "gift_budget_planner",
        "gift_bundle_optimizer",
    }

    # Sequential -> [Parallel(3 scouts), Verifier]
    pipeline = sub_by_name["deal_discovery_pipeline"]
    assert isinstance(pipeline, SequentialAgent)
    assert len(pipeline.sub_agents) == 2
    scanner, verifier = pipeline.sub_agents
    assert isinstance(scanner, ParallelAgent)
    assert {a.name for a in scanner.sub_agents} == {
        "catalog_deal_hunter",
        "coupon_and_cashback_scout",
        "price_timing_analyst",
    }
    assert isinstance(verifier, LlmAgent)
    assert verifier.output_key == "verified_deal_report"

    # LoopAgent for iterative budget-constrained bundle optimization
    optimizer = sub_by_name["gift_bundle_optimizer"]
    assert isinstance(optimizer, LoopAgent)
    assert optimizer.max_iterations == 2
    assert [a.name for a in optimizer.sub_agents] == [
        "bundle_proposer",
        "bundle_budget_auditor",
    ]


def test_a2a_agent_card_metadata_and_skills():
    cfg = Settings(public_base_url="https://shoppilot-demo.a.run.app")
    card = build_agent_card(cfg)
    assert card.name == "ShopPilot Holiday Shopping Assistant"
    assert card.supported_interfaces[0].url == "https://shoppilot-demo.a.run.app/a2a"
    assert card.capabilities.streaming is True
    skill_ids = {s.id for s in card.skills}
    assert skill_ids == {
        "holiday_deal_discovery",
        "fake_deal_detection_and_buy_timing",
        "coupon_and_cashback_stacking",
        "gift_budget_and_watchlist_planner",
    }

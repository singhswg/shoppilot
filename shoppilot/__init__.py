"""ShopPilot ADK package root. Exports `root_agent` for ADK CLI & Cloud Run."""

from shoppilot.agent import build_root_agent, root_agent

__all__ = ["build_root_agent", "root_agent"]

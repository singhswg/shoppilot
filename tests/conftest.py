"""Shared pytest fixtures for ShopPilot tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shoppilot.observability.telemetry import get_metrics


@dataclass
class DummyActions:
    """Minimal stand-in for ADK EventActions."""

    escalate: bool = False


@dataclass
class DummyToolConfirmation:
    """Minimal stand-in for ADK ToolConfirmation."""

    confirmed: bool
    payload: Any = None


@dataclass
class DummyToolContext:
    """Minimal stand-in for ADK ToolContext supporting scoped state, actions, and HITL."""

    state: dict[str, Any] = field(default_factory=dict)
    actions: DummyActions = field(default_factory=DummyActions)
    tool_confirmation: DummyToolConfirmation | None = None
    confirmation_requests: list[dict[str, Any]] = field(default_factory=list)

    def request_confirmation(self, *, hint: str | None = None, payload: Any | None = None) -> None:
        self.confirmation_requests.append({"hint": hint, "payload": payload})


@dataclass
class DummyCallbackContext:
    """Minimal stand-in for ADK CallbackContext."""

    agent_name: str = "shoppilot"
    state: dict[str, Any] = field(default_factory=dict)
    _invocation_context: Any = None


@pytest.fixture
def tool_context() -> DummyToolContext:
    return DummyToolContext()


@pytest.fixture
def callback_context() -> DummyCallbackContext:
    return DummyCallbackContext()


@pytest.fixture(autouse=True)
def reset_metrics() -> None:
    get_metrics().reset()

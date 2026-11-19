"""ADK lifecycle callbacks for guardrails, dynamic context injection, tracing, and memory."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from shoppilot.catalog_data import HOLIDAY_CALENDAR
from shoppilot.observability.logging_utils import get_logger, redact_pii
from shoppilot.observability.telemetry import get_metrics, get_tracer

logger = get_logger(__name__)
tracer = get_tracer("shoppilot.callbacks")

# Heuristic prompt-injection / exfiltration patterns blocked before reaching the LLM
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions"),
    re.compile(r"(?i)reveal\s+(your\s+)?(system\s+prompt|hidden\s+instructions|api\s+keys?)"),
    re.compile(r"(?i)bypass\s+(security|guardrails?|authentication)"),
]


def _extract_latest_user_text(llm_request: LlmRequest) -> str:
    """Extract latest user message text from an ADK LlmRequest."""
    if not llm_request.contents:
        return ""
    for content in reversed(llm_request.contents):
        if content.role == "user" and content.parts:
            texts = [p.text for p in content.parts if isinstance(getattr(p, "text", None), str) and p.text]
            if texts:
                return "\n".join(texts)
    return ""


def _build_compact_user_context(state: Mapping[str, Any]) -> str:
    """Build a token-efficient context summary from scoped ADK state.

    Reads `user:preferences`, `user:holiday_budget`, and `user:watchlist` so every
    model turn is personalized without dumping raw historical tool payloads.
    """
    lines: list[str] = [
        f"[Holiday Context] {HOLIDAY_CALENDAR['season']} | "
        f"Black Friday: {HOLIDAY_CALENDAR['black_friday']} | "
        f"Cyber Monday: {HOLIDAY_CALENDAR['cyber_monday']} | "
        f"Standard Shipping Cutoff: {HOLIDAY_CALENDAR['standard_shipping_cutoff']}"
    ]

    prefs = state.get("user:preferences")
    if isinstance(prefs, dict) and prefs:
        memberships = ", ".join(prefs.get("memberships", [])) or "none"
        retailers = ", ".join(prefs.get("preferred_retailers", [])) or "any"
        cards = ", ".join(prefs.get("credit_cards", [])) or "none"
        lines.append(
            f"[User Profile] Preferred retailers: {retailers} | "
            f"Memberships: {memberships} | Cashback cards: {cards}"
        )

    budget = state.get("user:holiday_budget")
    if isinstance(budget, dict) and budget.get("total_budget_usd"):
        total = float(budget.get("total_budget_usd", 0.0))
        spent = float(budget.get("spent_usd", 0.0))
        remaining = max(0.0, total - spent)
        lines.append(
            f"[Holiday Budget] Total: ${total:.2f} | Spent: ${spent:.2f} | "
            f"Remaining: ${remaining:.2f}"
        )

    watchlist = state.get("user:watchlist")
    if isinstance(watchlist, list) and watchlist:
        preview = ", ".join(
            f"{item.get('product_name', item.get('product_id'))} "
            f"(target ${item.get('target_price_usd')})"
            for item in watchlist[:5]
        )
        lines.append(f"[Watchlist ({len(watchlist)} items)] {preview}")

    return "\n".join(lines)


def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    """Guardrail + dynamic context injection + start latency timer."""
    metrics = get_metrics()
    metrics.inc("model_calls_started")
    agent_name = callback_context.agent_name

    # Record start timestamp in temporary state for latency measurement
    callback_context.state["temp:model_start_ts"] = time.perf_counter()

    latest_text = _extract_latest_user_text(llm_request)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(latest_text):
            metrics.inc("guardrail_prompt_injection_blocked")
            logger.warning(
                "Blocked suspected prompt injection attempt",
                extra={
                    "structured": {
                        "event": "guardrail_blocked",
                        "agent_name": agent_name,
                        "snippet": redact_pii(latest_text[:120]),
                    }
                },
            )
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "I can only assist with holiday shopping, deal discovery, "
                                "price comparisons, coupon stacking, and gift budget planning. "
                                "Please share what product or gift you're looking for!"
                            )
                        )
                    ],
                )
            )

    # Inject compact personalized context into system instruction
    raw_state: Any = callback_context.state
    state_view: Mapping[str, Any] = (
        raw_state.to_dict() if hasattr(raw_state, "to_dict") else raw_state
    )
    compact_ctx = _build_compact_user_context(state_view)
    if llm_request.config is None:
        llm_request.config = types.GenerateContentConfig()

    existing_sys = llm_request.config.system_instruction
    if isinstance(existing_sys, str) and existing_sys:
        llm_request.config.system_instruction = f"{existing_sys}\n\n{compact_ctx}"
    elif existing_sys is None:
        llm_request.config.system_instruction = compact_ctx

    return None


def after_model_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse | None:
    """Record model latency, token usage metrics, and OpenTelemetry span attributes."""
    metrics = get_metrics()
    metrics.inc("model_calls_completed")

    start_ts = callback_context.state.get("temp:model_start_ts")
    duration_ms = (time.perf_counter() - float(start_ts)) * 1000.0 if start_ts else 0.0
    if duration_ms > 0:
        metrics.observe_latency(f"model.{callback_context.agent_name}", duration_ms)

    usage = getattr(llm_response, "usage_metadata", None)
    prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
    candidate_tokens = getattr(usage, "candidates_token_count", 0) or 0
    if prompt_tokens:
        metrics.inc("tokens_input_total", int(prompt_tokens))
    if candidate_tokens:
        metrics.inc("tokens_output_total", int(candidate_tokens))

    with tracer.start_as_current_span("shoppilot.model_turn") as span:
        span.set_attribute("gen_ai.agent.name", callback_context.agent_name)
        span.set_attribute("shoppilot.latency_ms", round(duration_ms, 2))
        span.set_attribute("gen_ai.usage.input_tokens", int(prompt_tokens))
        span.set_attribute("gen_ai.usage.output_tokens", int(candidate_tokens))

    logger.info(
        "Model turn completed",
        extra={
            "structured": {
                "event": "model_turn_completed",
                "agent_name": callback_context.agent_name,
                "latency_ms": round(duration_ms, 2),
                "input_tokens": int(prompt_tokens),
                "output_tokens": int(candidate_tokens),
            }
        },
    )
    return None


def before_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> dict[str, Any] | None:
    """Start tool telemetry timer and log sanitized tool invocation."""
    metrics = get_metrics()
    metrics.inc(f"tool_calls.{tool.name}")
    tool_context.state[f"temp:tool_start_{tool.name}"] = time.perf_counter()

    logger.info(
        "Invoking tool",
        extra={
            "structured": {
                "event": "tool_start",
                "tool_name": tool.name,
                "args": args,
            }
        },
    )
    return None


def after_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict[str, Any],
) -> dict[str, Any] | None:
    """Record tool duration, error rate, and emit OTel span."""
    metrics = get_metrics()
    start_ts = tool_context.state.get(f"temp:tool_start_{tool.name}")
    duration_ms = (time.perf_counter() - float(start_ts)) * 1000.0 if start_ts else 0.0
    if duration_ms > 0:
        metrics.observe_latency(f"tool.{tool.name}", duration_ms)

    status = tool_response.get("status", "unknown") if isinstance(tool_response, dict) else "ok"
    if status == "error":
        metrics.inc(f"tool_errors.{tool.name}")

    with tracer.start_as_current_span(f"shoppilot.tool.{tool.name}") as span:
        span.set_attribute("gen_ai.tool.name", tool.name)
        span.set_attribute("shoppilot.tool.status", str(status))
        span.set_attribute("shoppilot.latency_ms", round(duration_ms, 2))

    logger.info(
        "Tool execution finished",
        extra={
            "structured": {
                "event": "tool_end",
                "tool_name": tool.name,
                "status": status,
                "latency_ms": round(duration_ms, 2),
            }
        },
    )
    return None


async def after_agent_callback(callback_context: CallbackContext) -> types.Content | None:
    """Persist completed session turns into long-term MemoryService when available."""
    inv_ctx = getattr(callback_context, "_invocation_context", None)
    memory_service = getattr(inv_ctx, "memory_service", None)
    session = getattr(inv_ctx, "session", None)
    if memory_service is not None and session is not None:
        try:
            await memory_service.add_session_to_memory(session)
            get_metrics().inc("memory_snapshots_saved")
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Failed to persist session to memory service",
                extra={"structured": {"error": str(exc)}},
            )
    return None

"""Observability package for ShopPilot: structured logging, OpenTelemetry tracing, and ADK callbacks."""

from shoppilot.observability.callbacks import (
    after_agent_callback,
    after_model_callback,
    after_tool_callback,
    before_model_callback,
    before_tool_callback,
)
from shoppilot.observability.logging_utils import configure_logging, get_logger, redact_pii
from shoppilot.observability.telemetry import (
    MetricsCollector,
    configure_telemetry,
    get_metrics,
    get_tracer,
)

__all__ = [
    "MetricsCollector",
    "after_agent_callback",
    "after_model_callback",
    "after_tool_callback",
    "before_model_callback",
    "before_tool_callback",
    "configure_logging",
    "configure_telemetry",
    "get_logger",
    "get_metrics",
    "get_tracer",
    "redact_pii",
]

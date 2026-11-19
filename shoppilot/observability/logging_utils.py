"""Structured JSON logging for Google Cloud Logging with PII redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

# Compiled patterns for common PII and secrets
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "[REDACTED_CARD]",
    ),
    (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[REDACTED_SSN]",
    ),
    (
        re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"),
        r"\1[REDACTED_TOKEN]",
    ),
    (
        re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[^\s,'\"]+['\"]?"),
        r"\1=[REDACTED]",
    ),
]


def redact_pii(text: str) -> str:
    """Mask PII and credential-like patterns before writing to logs or traces."""
    if not text:
        return text
    sanitized = text
    for pattern, replacement in _PII_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    """Recursively redact PII from structured log payloads."""
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    return value


class CloudLoggingJsonFormatter(logging.Formatter):
    """Emits single-line JSON structured logs correlated with Cloud Trace spans."""

    def __init__(self, project_id: str = "") -> None:
        super().__init__()
        self._project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": redact_pii(record.getMessage()),
        }

        # Attach OpenTelemetry trace correlation fields for Google Cloud Logging
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.is_valid:
            trace_id_hex = f"{ctx.trace_id:032x}"
            span_id_hex = f"{ctx.span_id:016x}"
            if self._project_id:
                payload["logging.googleapis.com/trace"] = (
                    f"projects/{self._project_id}/traces/{trace_id_hex}"
                )
            else:
                payload["trace_id"] = trace_id_hex
            payload["logging.googleapis.com/spanId"] = span_id_hex

        # Include custom structured fields passed via `extra={"structured": {...}}`
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            payload.update(_sanitize_value(structured))

        if record.exc_info:
            payload["exception"] = redact_pii(self.formatException(record.exc_info))

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", project_id: str = "") -> None:
    """Configure root logger with structured Cloud Logging JSON formatter."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CloudLoggingJsonFormatter(project_id=project_id))

    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger."""
    return logging.getLogger(name)

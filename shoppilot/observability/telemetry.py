"""OpenTelemetry tracing & in-process metrics for ShopPilot."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

from opentelemetry import trace
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from shoppilot.config import Settings, get_settings
from shoppilot.observability.logging_utils import get_logger

logger = get_logger(__name__)

_TELEMETRY_INITIALIZED = False
_INIT_LOCK = threading.Lock()


class MetricsCollector:
    """Thread-safe lightweight metrics collector exposed via /metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies_ms: dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe_latency(self, name: str, duration_ms: float) -> None:
        with self._lock:
            bucket = self._latencies_ms[name]
            bucket.append(round(duration_ms, 2))
            # Keep bounded rolling window of last 500 samples
            if len(bucket) > 500:
                del bucket[: len(bucket) - 500]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latency_summary: dict[str, dict[str, float]] = {}
            for name, samples in self._latencies_ms.items():
                if not samples:
                    continue
                ordered = sorted(samples)
                p95_idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
                latency_summary[name] = {
                    "count": float(len(ordered)),
                    "avg_ms": round(sum(ordered) / len(ordered), 2),
                    "p95_ms": ordered[p95_idx],
                    "max_ms": ordered[-1],
                }
            return {
                "counters": dict(self._counters),
                "latencies": latency_summary,
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._latencies_ms.clear()


_METRICS = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Return global metrics collector."""
    return _METRICS


def configure_telemetry(settings: Settings | None = None) -> TracerProvider:
    """Initialize OpenTelemetry TracerProvider with W3C context propagation.

    - In production on Cloud Run (`ENABLE_CLOUD_TRACE=true`), exports spans directly
      to Google Cloud Trace via `CloudTraceSpanExporter`.
    - In local dev (`ENABLE_CONSOLE_TRACE=true`), prints spans to stdout.
    """
    global _TELEMETRY_INITIALIZED
    cfg = settings or get_settings()

    with _INIT_LOCK:
        if _TELEMETRY_INITIALIZED:
            provider = trace.get_tracer_provider()
            if isinstance(provider, TracerProvider):
                return provider

        resource = Resource.create(
            {
                "service.name": cfg.service_name,
                "service.version": cfg.service_version,
                "deployment.environment": cfg.app_env,
            }
        )
        provider = TracerProvider(resource=resource)

        if cfg.enable_cloud_trace:
            try:
                from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

                exporter = CloudTraceSpanExporter(
                    project_id=cfg.google_cloud_project or None
                )
                provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info(
                    "Configured Google Cloud Trace exporter",
                    extra={"structured": {"project_id": cfg.google_cloud_project}},
                )
            except Exception as exc:  # pragma: no cover - optional GCP runtime dep
                logger.warning(
                    "Failed to initialize CloudTraceSpanExporter; continuing without it",
                    extra={"structured": {"error": str(exc)}},
                )

        if cfg.enable_console_trace:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        trace.set_tracer_provider(provider)
        # Enable W3C traceparent header propagation for A2A multi-agent traces
        set_global_textmap(TraceContextTextMapPropagator())
        _TELEMETRY_INITIALIZED = True
        return provider


def get_tracer(name: str = "shoppilot") -> trace.Tracer:
    """Return an OpenTelemetry tracer."""
    return trace.get_tracer(name)

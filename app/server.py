"""Production Cloud Run FastAPI + A2A ASGI server for ShopPilot.

Exposes:
- `GET /healthz` and `GET /readyz` (Cloud Run liveness & readiness probes)
- `GET /metrics` (structured observability counters & latency percentiles)
- `GET /.well-known/agent-card.json` (A2A discovery card for Agent Registry & Gemini Enterprise)
- `/a2a` (ADK A2A JSON-RPC endpoint generated via `google.adk.a2a.utils.agent_to_a2a.to_a2a`)

Security controls:
- Strict HTTP security headers (CSP, X-Content-Type-Options, X-Frame-Options, Permissions-Policy)
- Strict CORS allow-list (never wildcard `*`)
- Per-client sliding-window rate limiting
- Optional Bearer/API-key auth middleware (Cloud Run IAM enforces auth in production)
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from shoppilot.a2a.card import agent_card_to_dict, build_agent_card
from shoppilot.agent import root_agent
from shoppilot.config import Settings, get_settings
from shoppilot.observability.logging_utils import configure_logging, get_logger
from shoppilot.observability.telemetry import configure_telemetry, get_metrics

logger = get_logger(__name__)

_PUBLIC_PATHS = {"/healthz", "/readyz", "/.well-known/agent-card.json"}


class SlidingWindowRateLimiter:
    """In-memory per-IP sliding-window rate limiter (60-second window)."""

    def __init__(self, max_requests_per_minute: int) -> None:
        self._limit = max_requests_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        return True


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the production FastAPI application mounting the ADK A2A server."""
    cfg = settings or get_settings()
    configure_logging(level=cfg.log_level, project_id=cfg.google_cloud_project)
    configure_telemetry(cfg)

    agent_card = build_agent_card(cfg)
    rate_limiter = SlidingWindowRateLimiter(cfg.rate_limit_requests_per_minute)

    # Create ADK A2A ASGI sub-app first so its lifespan can be run by the parent FastAPI app.
    # FastAPI does not automatically run lifespans of mounted sub-apps, and `to_a2a` registers
    # its JSON-RPC routes inside its Starlette lifespan startup hook.
    a2a_asgi_app = to_a2a(
        root_agent,
        host=cfg.host,
        port=cfg.port,
        agent_card=agent_card,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with a2a_asgi_app.router.lifespan_context(a2a_asgi_app):
            yield

    application = FastAPI(
        title="ShopPilot Holiday Shopping Assistant",
        version=cfg.service_version,
        docs_url=None if cfg.app_env == "production" else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # Strict CORS allow-list (no wildcard '*')
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "traceparent", "tracestate"],
    )

    @application.middleware("http")
    async def security_and_observability_middleware(request: Request, call_next: Any) -> Response:
        start = time.perf_counter()
        metrics = get_metrics()
        metrics.inc("http_requests_total")

        # Rate limiting (exempt lightweight health probes)
        if request.url.path not in {"/healthz", "/readyz"}:
            client_ip = request.client.host if request.client else "unknown"
            if not rate_limiter.allow(client_ip):
                metrics.inc("http_rate_limited_total")
                return JSONResponse(
                    status_code=429,
                    content={"error": "Rate limit exceeded. Please retry shortly."},
                )

        # Authentication check for non-public endpoints when REQUIRE_AUTH=true.
        # TODO(security): In Cloud Run production, enforce IAM (--no-allow-unauthenticated)
        # AND/OR Google OIDC JWT validation for Gemini Enterprise / Agent Registry callers.
        if cfg.require_auth and request.url.path not in _PUBLIC_PATHS:
            auth_header = request.headers.get("Authorization", "")
            api_key_header = request.headers.get("X-API-Key", "")
            has_bearer = auth_header.startswith("Bearer ") and len(auth_header) > 10
            has_valid_key = bool(
                cfg.shoppilot_api_key
                and api_key_header
                and hmac.compare_digest(api_key_header, cfg.shoppilot_api_key)
            )
            if not (has_bearer or has_valid_key):
                metrics.inc("http_auth_rejected_total")
                return JSONResponse(
                    status_code=401,
                    content={"error": "Authentication required."},
                )

        response: Response = await call_next(request)

        # Mandatory security headers
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metrics.observe_latency("http_request_duration", elapsed_ms)
        return response

    @application.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        """Liveness probe for Cloud Run."""
        return {"status": "ok", "service": cfg.service_name, "version": cfg.service_version}

    @application.get("/readyz", tags=["ops"])
    async def readyz() -> dict[str, Any]:
        """Readiness probe verifying root agent and sub-agent graph are initialized."""
        return {
            "status": "ready",
            "agent": root_agent.name,
            "sub_agents": [a.name for a in root_agent.sub_agents],
            "a2a_url": agent_card.supported_interfaces[0].url
            if agent_card.supported_interfaces
            else "",
        }

    @application.get("/metrics", tags=["ops"])
    async def metrics_endpoint() -> dict[str, Any]:
        """Expose in-process observability counters and latency percentiles."""
        return get_metrics().snapshot()

    @application.get("/.well-known/agent-card.json", tags=["a2a"])
    async def well_known_agent_card() -> dict[str, Any]:
        """Serve the canonical A2A Agent Card for Agent Registry & Gemini Enterprise discovery."""
        return agent_card_to_dict(agent_card)

    # Mount ADK's A2A ASGI application at /a2a (lifespan is managed by parent FastAPI app)
    application.mount("/a2a", a2a_asgi_app)

    # Instrument FastAPI with OpenTelemetry for automatic HTTP + W3C traceparent spans
    FastAPIInstrumentor.instrument_app(application)
    return application


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)

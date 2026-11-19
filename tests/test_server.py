"""Integration tests for the Cloud Run FastAPI + A2A server and security controls."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.server import create_app
from shoppilot.config import Settings


def test_health_ready_metrics_and_agent_card_endpoints():
    cfg = Settings(
        app_env="test",
        require_auth=False,
        public_base_url="http://127.0.0.1:8080",
    )
    client = TestClient(create_app(cfg))

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in health.headers["Content-Security-Policy"]

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["agent"] == "shoppilot"
    assert "deal_discovery_pipeline" in ready.json()["sub_agents"]

    card = client.get("/.well-known/agent-card.json")
    assert card.status_code == 200
    body = card.json()
    assert body["name"] == "ShopPilot Holiday Shopping Assistant"
    assert body["supportedInterfaces"][0]["url"] == "http://127.0.0.1:8080/a2a"
    assert len(body["skills"]) == 4

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["counters"]["http_requests_total"] >= 3


def test_auth_enforcement_when_require_auth_enabled():
    cfg = Settings(
        app_env="test",
        require_auth=True,
        shoppilot_api_key="test-ephemeral-key-only",
    )
    client = TestClient(create_app(cfg))

    # Public probes remain accessible
    assert client.get("/healthz").status_code == 200
    assert client.get("/.well-known/agent-card.json").status_code == 200

    # Protected endpoint rejected without credentials
    assert client.get("/metrics").status_code == 401

    # Accepted with valid API key or Bearer token
    assert client.get("/metrics", headers={"X-API-Key": "test-ephemeral-key-only"}).status_code == 200
    assert client.get("/metrics", headers={"Authorization": "Bearer valid-oidc-token"}).status_code == 200


def test_rate_limiter_enforces_429():
    cfg = Settings(
        app_env="test",
        require_auth=False,
        rate_limit_requests_per_minute=2,
    )
    client = TestClient(create_app(cfg))
    assert client.get("/.well-known/agent-card.json").status_code == 200
    assert client.get("/.well-known/agent-card.json").status_code == 200
    assert client.get("/.well-known/agent-card.json").status_code == 429

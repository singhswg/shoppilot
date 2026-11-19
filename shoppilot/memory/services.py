"""Pluggable ADK SessionService and MemoryService factories.

Supports:
- InMemorySessionService (local dev, unit tests, ephemeral Cloud Run)
- DatabaseSessionService (Cloud SQL PostgreSQL or local SQLite via SQLAlchemy URI)
- VertexAiSessionService / VertexAiMemoryBankService (Vertex AI managed persistence)
"""

from __future__ import annotations

from typing import Any

from google.adk.memory import InMemoryMemoryService
from google.adk.sessions import InMemorySessionService

from shoppilot.config import Settings, get_settings
from shoppilot.observability.logging_utils import get_logger

logger = get_logger(__name__)


def build_session_service(settings: Settings | None = None) -> Any:
    """Instantiate the configured ADK SessionService."""
    cfg = settings or get_settings()
    uri = cfg.session_service_uri.strip()

    if uri == "memory" or not uri:
        logger.info("Using InMemorySessionService")
        return InMemorySessionService()

    if uri == "vertex":
        from google.adk.sessions import VertexAiSessionService

        logger.info(
            "Using VertexAiSessionService",
            extra={
                "structured": {
                    "project": cfg.google_cloud_project,
                    "location": cfg.google_cloud_location,
                }
            },
        )
        return VertexAiSessionService(
            project=cfg.google_cloud_project,
            location=cfg.google_cloud_location,
        )

    # SQLite / PostgreSQL via ADK DatabaseSessionService (parameterized SQLAlchemy ORM)
    from google.adk.sessions import DatabaseSessionService

    logger.info("Using DatabaseSessionService")
    return DatabaseSessionService(db_url=uri)


def build_memory_service(settings: Settings | None = None) -> Any:
    """Instantiate the configured ADK long-term MemoryService."""
    cfg = settings or get_settings()

    if cfg.memory_service_type == "vertex" and cfg.vertex_agent_engine_id:
        from google.adk.memory import VertexAiMemoryBankService

        logger.info(
            "Using VertexAiMemoryBankService",
            extra={"structured": {"agent_engine_id": cfg.vertex_agent_engine_id}},
        )
        return VertexAiMemoryBankService(
            project=cfg.google_cloud_project,
            location=cfg.google_cloud_location,
            agent_engine_id=cfg.vertex_agent_engine_id,
        )

    logger.info("Using InMemoryMemoryService")
    return InMemoryMemoryService()

"""Application configuration for ShopPilot using Pydantic Settings.

All sensitive values (API keys, database URLs) must be supplied via environment
variables or Google Cloud Secret Manager—never hardcoded.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service identity
    service_name: str = Field(default="shoppilot", description="Logical service name")
    service_version: str = Field(default="1.0.0", description="Semantic version")
    app_env: Literal["development", "staging", "production", "test"] = Field(
        default="development"
    )

    # Google Cloud / Vertex AI
    google_genai_use_vertexai: bool = Field(default=True)
    google_cloud_project: str = Field(default="")
    google_cloud_location: str = Field(default="global")

    # Model selection (fast model for parallel scouts, complex model for synthesis/routing)
    shoppilot_model: str = Field(default="gemini-3-flash-preview")
    shoppilot_complex_model: str = Field(default="gemini-3-flash-preview")

    # HTTP / A2A server configuration
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8080, ge=1, le=65535)
    public_base_url: str = Field(default="http://127.0.0.1:8080")
    allowed_origins: str = Field(default="http://127.0.0.1:8080,http://localhost:8080")
    rate_limit_requests_per_minute: int = Field(default=60, ge=1, le=10000)

    # Security
    require_auth: bool = Field(default=False)
    shoppilot_api_key: str | None = Field(default=None)

    # Context & Memory backends
    session_service_uri: str = Field(default="memory")
    memory_service_type: Literal["memory", "vertex"] = Field(default="memory")
    vertex_agent_engine_id: str | None = Field(default=None)

    # Observability
    enable_cloud_trace: bool = Field(default=False)
    enable_console_trace: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Guardrail & Human-in-the-Loop (HITL) limits
    max_query_length: int = Field(default=300, ge=10, le=2000)
    max_budget_usd: float = Field(default=50000.0, gt=0)
    max_watchlist_items: int = Field(default=50, ge=1, le=200)
    hitl_approval_threshold_usd: float = Field(
        default=250.0,
        ge=0,
        description="Purchases at or above this amount require explicit human confirmation.",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins, excluding wildcards."""
        return [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip() and origin.strip() != "*"
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()

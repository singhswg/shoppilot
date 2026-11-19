# ==============================================================================
# Multi-stage production Dockerfile for ShopPilot on Google Cloud Run
# ==============================================================================

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY shoppilot ./shoppilot
COPY app ./app

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

# ------------------------------------------------------------------------------
# Runtime stage (minimal, non-root)
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8080 \
    ENABLE_CLOUD_TRACE=true \
    REQUIRE_AUTH=true

# Create unprivileged user
RUN groupadd --system shoppilot && useradd --system --gid shoppilot --create-home shoppilot

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=shoppilot:shoppilot shoppilot ./shoppilot
COPY --chown=shoppilot:shoppilot app ./app

USER shoppilot

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8080\")}/healthz', timeout=3)" || exit 1

CMD ["sh", "-c", "exec uvicorn app.server:app --host ${HOST:-0.0.0.0} --port ${PORT:-8080} --workers 1 --timeout-keep-alive 30"]

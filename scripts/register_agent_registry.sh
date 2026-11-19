#!/usr/bin/env bash
set -euo pipefail

# Register the deployed Cloud Run ShopPilot A2A Agent in Google Cloud Agent Registry.
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-shoppilot}"
REGISTRY_LOCATION="${AGENT_REGISTRY_LOCATION:-global}"

SERVICE_URL="${SERVICE_URL:-$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')}"

echo "==> Ensuring Agent Registry API is enabled on ${PROJECT_ID}..."
gcloud services enable agentregistry.googleapis.com --project="${PROJECT_ID}" >/dev/null 2>&1 || true

echo "==> Fetching live A2A Agent Card from ${SERVICE_URL}/.well-known/agent-card.json..."
ID_TOKEN="$(gcloud auth print-identity-token)"
AGENT_CARD_JSON="$(curl -fsS \
  -H "Authorization: Bearer ${ID_TOKEN}" \
  "${SERVICE_URL}/.well-known/agent-card.json")"

echo "==> Registering ShopPilot in Google Cloud Agent Registry (${REGISTRY_LOCATION})..."
if gcloud alpha agent-registry services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --location="${REGISTRY_LOCATION}" >/dev/null 2>&1; then
  gcloud alpha agent-registry services update "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --location="${REGISTRY_LOCATION}" \
    --display-name="ShopPilot Holiday Shopping Assistant" \
    --description="Automated holiday shopping assistant (ADK + A2A on Cloud Run)" \
    --agent-spec-type=a2a-agent-card \
    --agent-spec-content="${AGENT_CARD_JSON}"
else
  gcloud alpha agent-registry services create "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --location="${REGISTRY_LOCATION}" \
    --display-name="ShopPilot Holiday Shopping Assistant" \
    --description="Automated holiday shopping assistant (ADK + A2A on Cloud Run)" \
    --agent-spec-type=a2a-agent-card \
    --agent-spec-content="${AGENT_CARD_JSON}"
fi

echo "==> Verifying Agent Registry entry..."
gcloud alpha agent-registry services list \
  --project="${PROJECT_ID}" \
  --location="${REGISTRY_LOCATION}"

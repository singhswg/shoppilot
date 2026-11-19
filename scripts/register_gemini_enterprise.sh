#!/usr/bin/env bash
set -euo pipefail

# Link the registered Cloud Run A2A ShopPilot agent to a Gemini Enterprise App (Discovery Engine).
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-shoppilot}"
GE_LOCATION="${GE_LOCATION:-global}"
GE_ENGINE_ID="${GE_ENGINE_ID:?Set GE_ENGINE_ID to your Gemini Enterprise App / Engine ID}"
GE_ASSISTANT_ID="${GE_ASSISTANT_ID:-default_assistant}"

SERVICE_URL="${SERVICE_URL:-$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')}"

echo "==> Fetching live A2A Agent Card from ${SERVICE_URL}..."
ID_TOKEN="$(gcloud auth print-identity-token)"
ACCESS_TOKEN="$(gcloud auth print-access-token)"
AGENT_CARD_JSON="$(curl -fsS -H "Authorization: Bearer ${ID_TOKEN}" "${SERVICE_URL}/.well-known/agent-card.json")"

PAYLOAD="$(python3 -c '
import json, sys
card_str = sys.argv[1]
payload = {
    "displayName": "ShopPilot Holiday Shopping Assistant",
    "description": "Automated holiday shopping assistant that finds genuine deals, flags fake holiday markups, stacks coupons & cashback, and tracks gift budgets.",
    "a2aAgentDefinition": {
        "jsonAgentCard": card_str
    },
    "sharingConfig": {
        "scope": "ALL_USERS"
    }
}
print(json.dumps(payload))
' "${AGENT_CARD_JSON}")"

ENDPOINT="https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_ID}/locations/${GE_LOCATION}/collections/default_collection/engines/${GE_ENGINE_ID}/assistants/${GE_ASSISTANT_ID}/agents"

echo "==> Registering ShopPilot A2A agent in Gemini Enterprise Engine '${GE_ENGINE_ID}'..."
curl -fsS -X POST "${ENDPOINT}" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}"

echo ""
echo "==> ShopPilot is now available in Gemini Enterprise App '${GE_ENGINE_ID}'!"

#!/usr/bin/env bash
set -euo pipefail

# Provision a Google Cloud Agent Gateway resource linked to your project's Agent Registry.
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
GATEWAY_ID="${AGENT_GATEWAY_ID:-agent-gateway}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

echo "==> Enabling Network Services, Network Security, and Agent Registry APIs on ${PROJECT_ID}..."
gcloud services enable \
  networkservices.googleapis.com \
  networksecurity.googleapis.com \
  agentregistry.googleapis.com \
  --project="${PROJECT_ID}"

TMP_YAML="$(mktemp --suffix=.yaml)"
trap 'rm -f "${TMP_YAML}"' EXIT

cat > "${TMP_YAML}" <<EOF
name: projects/${PROJECT_NUMBER}/locations/${REGION}/agentGateways/${GATEWAY_ID}
description: "Project-level Agent Gateway for Agent Registry governance"
protocols:
  - MCP
googleManaged:
  governedAccessPath: AGENT_TO_ANYWHERE
registries:
  - "//agentregistry.googleapis.com/projects/${PROJECT_NUMBER}/locations/global"
EOF

echo "==> Importing Agent Gateway '${GATEWAY_ID}' in ${REGION} (project ${PROJECT_ID} / #${PROJECT_NUMBER})..."
gcloud beta network-services agent-gateways import "${GATEWAY_ID}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --source="${TMP_YAML}"

echo "==> Verifying Agent Gateway resource..."
gcloud beta network-services agent-gateways describe "${GATEWAY_ID}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"

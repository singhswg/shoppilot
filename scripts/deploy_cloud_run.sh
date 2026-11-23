#!/usr/bin/env bash
set -euo pipefail

# Build, deploy ShopPilot to Cloud Run, update PUBLIC_BASE_URL, and run smoke tests.
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-shoppilot}"
AR_REPO="${AR_REPO:-shoppilot}"
SA_EMAIL="${SA_NAME:-shoppilot-sa}@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}:${IMAGE_TAG}"

echo "==> Building and pushing container image: ${IMAGE_URI}"
gcloud builds submit --tag "${IMAGE_URI}" --project="${PROJECT_ID}" .

echo "==> Deploying ${SERVICE_NAME} to Cloud Run (${REGION})..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_URI}" \
  --region="${REGION}" \
  --platform=managed \
  --service-account="${SA_EMAIL}" \
  --no-allow-unauthenticated \
  --min-instances=0 \
  --max-instances=10 \
  --memory=1Gi \
  --cpu=2 \
  --set-env-vars="APP_ENV=production,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},ENABLE_CLOUD_TRACE=true,REQUIRE_AUTH=false" \
  --project="${PROJECT_ID}"

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format='value(status.url)')"

echo "==> Updating PUBLIC_BASE_URL to ${SERVICE_URL}..."
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --update-env-vars="PUBLIC_BASE_URL=${SERVICE_URL}" \
  --quiet

echo "==> Running post-deploy smoke tests..."
ID_TOKEN="$(gcloud auth print-identity-token)"
curl -fsS -H "Authorization: Bearer ${ID_TOKEN}" "${SERVICE_URL}/readyz"
echo ""
curl -fsS -H "Authorization: Bearer ${ID_TOKEN}" "${SERVICE_URL}/.well-known/agent-card.json" | head -c 400
echo ""
echo "==> Deployment verified! Cloud Run URL: ${SERVICE_URL}"

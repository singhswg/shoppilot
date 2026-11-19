#!/usr/bin/env bash
set -euo pipefail

# Provision required GCP APIs, Artifact Registry repository, and least-privilege Service Account.
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
AR_REPO="${AR_REPO:-shoppilot}"
SA_NAME="${SA_NAME:-shoppilot-sa}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Enabling required GCP APIs on project ${PROJECT_ID}..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  secretmanager.googleapis.com \
  discoveryengine.googleapis.com \
  --project="${PROJECT_ID}"

echo "==> Creating Artifact Registry repository '${AR_REPO}' in ${REGION} (if missing)..."
gcloud artifacts repositories describe "${AR_REPO}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1 || \
gcloud artifacts repositories create "${AR_REPO}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="ShopPilot ADK agent container images" \
  --project="${PROJECT_ID}"

echo "==> Creating least-privilege Service Account '${SA_EMAIL}' (if missing)..."
gcloud iam service-accounts describe "${SA_EMAIL}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1 || \
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="ShopPilot Cloud Run Runtime SA" \
  --project="${PROJECT_ID}"

echo "==> Granting least-privilege IAM roles to ${SA_EMAIL}..."
for ROLE in \
  "roles/aiplatform.user" \
  "roles/cloudtrace.agent" \
  "roles/logging.logWriter" \
  "roles/monitoring.metricWriter" \
  "roles/secretmanager.secretAccessor"
do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet >/dev/null
done

echo "==> GCP setup complete for ${PROJECT_ID} (${REGION})."

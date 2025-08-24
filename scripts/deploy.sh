#!/usr/bin/env bash
set -euo pipefail

# Load environment variables from .env if present
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi

# ========= Config =========
SERVICE_NAME=${SERVICE_NAME:-slack-adk-bot}

REGION=${GOOGLE_CLOUD_LOCATION:-us-central1}

AR_LOCATION=${AR_LOCATION:-$REGION}

AR_REPO=${AR_REPO:-slack-adk-apps}

PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is empty. Set PROJECT_ID or 'gcloud config set project ...' first." >&2
  exit 1
fi

# Artifact Registry image URL
IMAGE="${AR_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}:latest"

# ========= Pre-checks =========
if [[ -z "${SLACK_BOT_TOKEN:-}" || -z "${SLACK_SIGNING_SECRET:-}" ]]; then
  echo "SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET environment variables must be set" >&2
  exit 1
fi

# ========= Enable required APIs =========
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  --project "${PROJECT_ID}"

# ========= Ensure AR repository exists =========
if ! gcloud artifacts repositories describe "${AR_REPO}" \
  --location="${AR_LOCATION}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Creating Artifact Registry repository: ${AR_REPO} in ${AR_LOCATION}"
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker \
    --location="${AR_LOCATION}" \
    --description="Docker images for ${PROJECT_ID}" \
    --project "${PROJECT_ID}"
fi

# ========= Configure Docker auth for AR =========
gcloud auth configure-docker "${AR_LOCATION}-docker.pkg.dev" --quiet

# ========= Build & Push via Cloud Build directly to AR =========
gcloud builds submit --tag "${IMAGE}" --project "${PROJECT_ID}"

# ========= Deploy to Cloud Run =========
SERVICE_URL=$(gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --no-cpu-throttling  \
  --project "${PROJECT_ID}" \
  --set-env-vars "SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN},SLACK_SIGNING_SECRET=${SLACK_SIGNING_SECRET},GOOGLE_GENAI_USE_VERTEXAI=${GOOGLE_GENAI_USE_VERTEXAI},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},ALLOWED_SLACK_WORKSPACE=${ALLOWED_SLACK_WORKSPACE:-}" \
  --format 'value(status.url)')

echo "--------------------------------------------"
echo "✅ Deployment completed"
echo "Service: ${SERVICE_NAME}"
echo "Region:  ${REGION}"
echo "Image:   ${IMAGE}"
echo "URL:     ${SERVICE_URL}"
echo "--------------------------------------------"

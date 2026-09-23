#!/usr/bin/env bash
# Build and deploy the Atlas API to Cloud Run.
#
# One-time setup (project, APIs, secrets) is in docs/deploy.md. This script is
# the repeatable part: build the image with Cloud Build, push to Artifact
# Registry, roll a new Cloud Run revision. Secrets are referenced by name —
# nothing sensitive passes through this file or the shell history.
#
# Usage: PROJECT=atlas-rag-rush scripts/deploy_gcp.sh
#        SKIP_BUILD=1 IMAGE_TAG=abc1234 ...   deploy an image already in the registry
set -euo pipefail

PROJECT="${PROJECT:-atlas-rag-rush}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-atlas-api}"
REPO="${REPO:-atlas}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${IMAGE_TAG}"

if [[ -z "${SKIP_BUILD:-}" ]]; then
  echo "→ building ${IMAGE}"
  gcloud builds submit --project "${PROJECT}" --tag "${IMAGE}" --quiet .
else
  echo "→ SKIP_BUILD set; deploying existing ${IMAGE}"
fi

echo "→ deploying ${SERVICE} to ${REGION}"
gcloud run deploy "${SERVICE}" \
  --project "${PROJECT}" --region "${REGION}" \
  --image "${IMAGE}" \
  --platform managed --allow-unauthenticated \
  --cpu 1 --memory 2Gi --concurrency 8 \
  --min-instances 0 --max-instances 2 \
  --timeout 120 \
  --set-env-vars "AUTH_ENABLED=true,AUTH_STORE=firestore,RERANKER_ENABLED=true,\
BUDGET_DAILY_USD=${BUDGET_DAILY_USD:-0.60},BUDGET_STORE=firestore,\
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/,\
OPENAI_PRIMARY_MODEL=gemini-3.1-flash-lite,OPENAI_FALLBACK_MODEL=gemini-3.5-flash-lite,\
OPENAI_EMBEDDING_MODEL=gemini-embedding-001,OPENAI_EMBEDDING_DIMENSIONS=1536,\
ROUTER_DOMAIN=the FastAPI web framework documentation,\
ATLAS_INDEX_DIR=/app/data/index,\
REDIS_URL=" \
  --set-secrets "OPENAI_API_KEY=atlas-openai-api-key:latest,\
QDRANT_URL=atlas-qdrant-url:latest,\
QDRANT_API_KEY=atlas-qdrant-api-key:latest,\
ADMIN_SECRET=atlas-admin-secret:latest" \
  --quiet

gcloud run services describe "${SERVICE}" --project "${PROJECT}" --region "${REGION}" \
  --format 'value(status.url)'

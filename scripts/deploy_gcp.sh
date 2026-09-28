#!/usr/bin/env bash
# Build and deploy the Atlas API to Cloud Run.
#
# One-time setup (project, APIs, secrets) is in docs/deploy.md. This script is
# the repeatable part: build the image with Cloud Build, push to Artifact
# Registry, roll a new Cloud Run revision. Secrets are referenced by name —
# nothing sensitive passes through this file or the shell history.
#
# The build bakes data/index/ into the image (Dockerfile "COPY data/index/"),
# so this script is the last point at which the sparse half of the corpus can
# still be checked against the dense half in Qdrant. It checks, and refuses.
# See the verify step below for what that is protecting against.
#
# Usage: PROJECT=atlas-rag-rush scripts/deploy_gcp.sh
#        SKIP_BUILD=1 IMAGE_TAG=abc1234 ...   deploy an image already in the registry
#        SKIP_VERIFY=1 ...                    build without checking the index
set -euo pipefail

PROJECT="${PROJECT:-atlas-rag-rush}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-atlas-api}"
REPO="${REPO:-atlas}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${IMAGE_TAG}"

PYTHON="${PYTHON:-.venv/bin/python}"

# ── Index gate ────────────────────────────────────────────────────────────────
#
# The BM25 file travels inside the image; the dense vectors do not, they are
# already live in Qdrant the moment an ingest finishes. So the two halves of
# the corpus are deployed by different mechanisms at different times, and
# between them production runs a hybrid whose halves disagree — it answers
# every query and scores badly rather than failing, which is why it went
# unnoticed for a week.
#
# Two real incidents this gate would have caught:
#   2026-09-27  an ingest went to the wrong namespace, changed nothing, and
#               the deploy that followed re-baked the pre-header index.
#   2026-09-28  an ingest lost 37 of 155 files to Qdrant timeouts, leaving
#               dense at 2090/4020 headers against sparse at 3950/4020.
# Both runs looked like successes. Point counts, file sizes and mtimes all
# agreed; only the per-chunk content hashes did not.
#
# Free to run — Qdrant scrolls and a local file read, no embeddings, no LLM —
# so there is no argument for skipping it that is worth the failure mode.
verify_index() {
  if [[ -n "${SKIP_VERIFY:-}" ]]; then
    echo "!  SKIP_VERIFY set — building an index nobody checked." >&2
    return 0
  fi

  if [[ ! -x "${PYTHON}" ]]; then
    echo "!  ${PYTHON} not found; skipping the index check." >&2
    echo "   Set PYTHON=... or SKIP_VERIFY=1 to say that was deliberate." >&2
    return 0
  fi

  # Exactly the namespaces the image will carry: every directory under
  # data/index/ with a BM25 file in it, since that is what COPY takes.
  local args=() ns
  for dir in data/index/*/; do
    [[ -f "${dir}bm25_index.json" ]] || continue
    ns="$(basename "${dir}")"
    args+=(--namespace "${ns}")
  done

  if [[ ${#args[@]} -eq 0 ]]; then
    echo "!  no BM25 index under data/index/ — the image will ship without one." >&2
    return 0
  fi

  echo "→ verifying the index this build will bake in"
  if ! "${PYTHON}" scripts/verify_index.py "${args[@]}"; then
    cat >&2 <<'EOF'

Refusing to build: the index does not agree with Qdrant.

Baking it now ships a hybrid whose halves disagree, which answers queries
and scores badly instead of failing. Re-run the ingest for the namespace
named above, verify, then deploy:

  .venv/bin/python scripts/ingest.py data/corpus/fastapi --namespace default
  .venv/bin/python scripts/verify_index.py --namespace default

SKIP_VERIFY=1 overrides this if you know why the two differ.
EOF
    return 1
  fi
}

if [[ -z "${SKIP_BUILD:-}" ]]; then
  verify_index
  echo "→ building ${IMAGE}"
  gcloud builds submit --project "${PROJECT}" --tag "${IMAGE}" --quiet .
else
  # Nothing here can see inside an image built earlier, so there is nothing
  # honest to check. Say so rather than printing a check that did not happen.
  echo "→ SKIP_BUILD set; deploying existing ${IMAGE}"
  echo "   index not checked — it is whatever was baked when that tag was built"
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

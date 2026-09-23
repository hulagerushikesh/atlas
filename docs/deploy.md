# Atlas — Deployment Guide

## Local full stack (dev)

```bash
make docker-up        # Qdrant + Redis
make serve            # API at http://localhost:8010
```

## Local full stack with monitoring

```bash
make docker-up        # Qdrant + Redis + Atlas API
make monitor-up       # Prometheus (9090) + Grafana (3000)
```

Open Grafana at <http://localhost:3000> — username `admin`, password `admin`.
The **Atlas Overview** dashboard is pre-loaded.

---

## Google Cloud Run (production)

Topology, chosen for a portfolio service that must cost ≈₹0 while idle:

| Piece | Choice | Why |
|---|---|---|
| API | Cloud Run, `asia-south1`, 1 vCPU / 2 GiB, min 0 max 2 | Scales to zero; the torch image cold-starts in ~15 s, acceptable for a demo |
| Vectors | Qdrant Cloud free cluster (1 GiB RAM, 4 GiB disk) | 4,020 chunks × 1536 d ≈ 25 MB; ₹0 |
| BM25 | `data/index/<ns>/bm25_index.json` baked into the image | 3.5 MB; one artifact, no bucket to mount; corpus is static for the demo |
| API keys | Firestore (`AUTH_STORE=firestore`) | Disk is ephemeral; SQLite would reset every deploy |
| Cache / rate limit / spend cap | In-process fallbacks (no Redis) | One instance most of the time; Memorystore is ₹2,500/mo minimum |
| Secrets | Secret Manager, referenced by name in the deploy | Never in env files, images or shell history |

### One-time setup

```bash
PROJECT=atlas-rag-rush       # any globally unique id; `atlas-rag` is taken
REGION=asia-south1
gcloud projects create $PROJECT
gcloud billing projects link $PROJECT --billing-account <ACCOUNT_ID>
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  firestore.googleapis.com
gcloud artifacts repositories create atlas --repository-format docker --location $REGION
gcloud firestore databases create --location $REGION --type firestore-native
```

Billing must be linked before the API enables: `gcloud services enable` fails
on a project without it.

Secrets — each value is read from a local file or generated, never typed
into a terminal that keeps history:

```bash
grep '^OPENAI_API_KEY=' .env | cut -d= -f2- | tr -d '\n' \
  | gcloud secrets create atlas-openai-api-key --data-file=-
printf '%s' 'https://<cluster>.cloud.qdrant.io:6333' \
  | gcloud secrets create atlas-qdrant-url --data-file=-
grep '^QDRANT_API_KEY=' .env | cut -d= -f2- | tr -d '\n' \
  | gcloud secrets create atlas-qdrant-api-key --data-file=-
openssl rand -hex 24 | tr -d '\n' | gcloud secrets create atlas-admin-secret --data-file=-
```

Grant the Cloud Run service account access to them and to Firestore:

```bash
SA=$(gcloud projects describe $PROJECT --format 'value(projectNumber)')-compute@developer.gserviceaccount.com
for s in atlas-openai-api-key atlas-qdrant-url atlas-qdrant-api-key atlas-admin-secret; do
  gcloud secrets add-iam-policy-binding $s --member serviceAccount:$SA --role roles/secretmanager.secretAccessor
done
gcloud projects add-iam-policy-binding $PROJECT --member serviceAccount:$SA --role roles/datastore.user
```

### Deploy

```bash
make deploy-gcp                          # PROJECT defaults to atlas-rag-rush
SKIP_BUILD=1 IMAGE_TAG=0fdd0b2 scripts/deploy_gcp.sh   # roll an image already built
```

Builds with Cloud Build (free tier: 120 min/day, ~3 min per build), pushes to
Artifact Registry, rolls a revision. The script pins model, provider and budget
env vars; change them there, not in the console, so the deploy stays
reproducible.

`.gcloudignore` is required, not optional: without it `gcloud builds submit`
falls back to `.gitignore`, which excludes `data/`, and the build fails at
`COPY data/index/`. The file simply includes `.dockerignore`.

### Load the corpus

Ingest runs from your machine against the cloud Qdrant — the API's ingest
endpoint would time out on 155 files — and writes the BM25 file that the next
image build bakes in:

Point `QDRANT_URL` / `QDRANT_API_KEY` in `.env` at the cloud cluster, then:

```bash
.venv/bin/python scripts/ingest.py --namespace default --glob '**/*.md' data/corpus/fastapi
make deploy-gcp                       # picks up data/index/default/bm25_index.json
```

Chunk ids are deterministic (uuid5), so the local BM25 file and the cloud
Qdrant collection agree even though they were written by separate runs. Build
the image *after* the ingest — the BM25 file is baked in, so an image built
first ships a stale index.

The LLM env vars keep the `OPENAI_` prefix even on Gemini: the prefix names the
wire protocol, and `OPENAI_BASE_URL` points at Gemini's OpenAI-compatible
endpoint. Renaming them to `GEMINI_*` makes `OpenAIConfig` fail with
`api_key Field required`.

### First API key

```bash
ADMIN=$(gcloud secrets versions access latest --secret atlas-admin-secret)
curl -s -X POST https://<service-url>/keys -H "X-Admin-Secret: $ADMIN" \
  -H 'Content-Type: application/json' -d '{"name":"demo","rate_limit_rpm":10}'
```

The key is returned once. Paste it into the console's Settings dialog.

### Cost

Idle: ₹0 (Cloud Run min-instances 0, Qdrant free tier, Firestore free tier).
Artifact Registry ≈₹10/mo for the image. Per query ≈₹0.02 in Gemini tokens,
capped by `BUDGET_DAILY_USD` (429 past it). One full corpus ingest ≈₹1 in
embeddings; re-runs skip unchanged documents and cost ₹0. Set a billing budget
alert at ₹200/mo in the console as a backstop.

---

## Environment variables (production)

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENAI_API_KEY` | Yes | |
| `QDRANT_URL` | Yes | Qdrant Cloud URL |
| `QDRANT_API_KEY` | Yes (cloud) | Leave blank for local |
| `REDIS_URL` | No | Absent on Cloud Run; in-process fallbacks are used |
| `AUTH_ENABLED` | Recommended | `true` in production |
| `ADMIN_SECRET` | When auth on | Random secret for `POST /keys` |
| `AUTH_STORE` | No | `sqlite` (default) or `firestore` (Cloud Run) |
| `BUDGET_DAILY_USD` | Recommended | Daily spend cap; `0` disables |
| `SENTRY_DSN` | No | From sentry.io project settings |
| `LOG_LEVEL` | No | Default `INFO` |

---

## Health check

```
GET /health
```

Returns `200 ok` when Qdrant and Redis are reachable; `503` when Qdrant is down.
Cloud Run uses it as the startup probe.

## Prometheus metrics

```
GET /metrics
```

Standard Prometheus text exposition. Scrape from your Prometheus instance or
use the bundled `monitoring/prometheus.yml` with `make monitor-up`.

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

## Fly.io

### First deploy

```bash
# 1. Install flyctl and log in
brew install flyctl && fly auth login

# 2. Create the app (do not deploy yet — we need secrets first)
fly launch --no-deploy

# 3. Set required secrets
fly secrets set \
  OPENAI_API_KEY=sk-... \
  QDRANT_URL=https://xyz.qdrant.io \
  QDRANT_API_KEY=... \
  ADMIN_SECRET=$(openssl rand -hex 16) \
  AUTH_ENABLED=true

# Optional — Sentry error tracking
fly secrets set SENTRY_DSN=https://...@sentry.io/...

# 4. Create a persistent volume for the SQLite auth DB
fly volumes create atlas_data --size 1 --region sjc

# 5. Deploy
fly deploy
```

### Subsequent deploys

```bash
make deploy-fly       # or: fly deploy
```

### Qdrant Cloud

Sign up at <https://cloud.qdrant.io> and create a cluster.
Copy the cluster URL and API key into `fly secrets set` above.

### Create the first API key on Fly

```bash
fly ssh console -C \
  "python scripts/create_key.py --name 'prod' --email you@example.com"
```

---

## Environment variables (production)

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENAI_API_KEY` | Yes | |
| `QDRANT_URL` | Yes | Qdrant Cloud URL |
| `QDRANT_API_KEY` | Yes (cloud) | Leave blank for local |
| `REDIS_URL` | No | Fly Redis add-on or Upstash |
| `AUTH_ENABLED` | Recommended | `true` in production |
| `ADMIN_SECRET` | When auth on | Random secret for `POST /keys` |
| `SENTRY_DSN` | No | From sentry.io project settings |
| `LOG_LEVEL` | No | Default `INFO` |

---

## Health check

```
GET /health
```

Returns `200 ok` when Qdrant and Redis are reachable; `503` when Qdrant is down.
Fly.io polls this every 15 s (configured in `fly.toml`).

## Prometheus metrics

```
GET /metrics
```

Standard Prometheus text exposition. Scrape from your Prometheus instance or
use the bundled `monitoring/prometheus.yml` with `make monitor-up`.

"""
Prometheus metrics middleware.

Design rationale:
    We track four signals per endpoint:
      1. Request count (labelled by method, path, status) — throughput and
         error rate without needing a separate APM tool.
      2. Request duration histogram — p50/p95/p99 latency without storing
         every individual observation.
      3. Token usage counter — running total of LLM tokens consumed, enabling
         cost alerting via Prometheus alert rules.
      4. Cache hit counter — measures cache effectiveness.

    Histogram bucket boundaries are tuned for RAG workloads: most non-cached
    responses take 1–10 seconds (LLM call + retrieval), so we need fine
    resolution there. Sub-100ms responses are cached hits.

    We use the prometheus_client push model (Counter, Histogram) rather than
    a gauge to avoid race conditions under concurrent requests. Histograms
    are thread-safe via the underlying C extension.

    /metrics itself is excluded from latency tracking to avoid
    self-referential noise.
"""

from __future__ import annotations

import time

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "atlas_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "atlas_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["path"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

TOKEN_USAGE = Counter(
    "atlas_llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "type"],  # type: prompt | completion
)

CACHE_HITS = Counter(
    "atlas_cache_hits_total",
    "Cache hits by level",
    ["level"],  # memory | redis
)

COST_USD = Counter(
    "atlas_estimated_cost_usd_total",
    "Estimated LLM cost in USD",
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record per-request Prometheus metrics."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        path = request.url.path
        start = time.perf_counter()

        response: Response = await call_next(request)  # type: ignore[operator]

        if path != "/metrics":
            duration = time.perf_counter() - start
            REQUEST_COUNT.labels(
                method=request.method, path=path, status=response.status_code
            ).inc()
            REQUEST_LATENCY.labels(path=path).observe(duration)

        return response

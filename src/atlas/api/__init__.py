"""
Module E — FastAPI application, tracing, caching, and streaming.

Submodules:
    app         — FastAPI application factory and lifespan handler
    routes      — /query, /ingest, /health, /metrics endpoints
    middleware  — per-request tracing + Prometheus metrics
    cache       — two-level (memory + Redis) query cache
    schemas     — request/response Pydantic models for the HTTP API
    dependencies — FastAPI DI accessors for AppState, pipeline, indexer, cache
    cost        — token cost estimation per model
"""

from atlas.api.app import create_app

__all__ = ["create_app"]

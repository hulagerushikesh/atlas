"""
Structured logging configuration via structlog.

Design rationale:
    structlog gives us structured key=value log lines that are trivially
    parseable by log aggregators (Datadog, CloudWatch, etc.) while remaining
    human-readable in development. Configured once at application startup;
    every module just calls `structlog.get_logger(__name__)`.

    We bind a request_id in Module E's middleware so every log line emitted
    during a request carries that ID without threading it through call stacks.

    In tests, configure_logging(json=False) gives readable output and the
    structlog.testing helpers let you assert on log events.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", json: bool = False) -> None:
    """Call once at process start (e.g. in the FastAPI lifespan handler)."""

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

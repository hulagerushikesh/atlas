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
from collections.abc import MutableMapping
from typing import Any

import structlog

# E4.2: what people ask, and text derived from it, stays out of the general
# logs; the audit record (atlas.api.audit) holds questions for admins only.
SENSITIVE_FIELDS = frozenset({
    "query", "question", "reasoning", "sub_queries", "hypothesis", "hypotheses",
    "answer", "claims", "unsupported_claims",
})


def redact_questions(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Replace sensitive values by their size, so a log line still says one was there."""
    for name in SENSITIVE_FIELDS.intersection(event):
        value = event[name]
        size = len(value) if isinstance(value, (str, list, tuple)) else 0
        event[name] = f"[withheld, {size} {'chars' if isinstance(value, str) else 'items'}]"
    return event


def configure_logging(level: str = "INFO", json: bool = False,
                      log_questions: bool = False) -> None:
    """Call once at process start (e.g. in the FastAPI lifespan handler).

    *log_questions* keeps question text in the logs: for a laptop, never live."""

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    if not log_questions:
        shared_processors.append(redact_questions)

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

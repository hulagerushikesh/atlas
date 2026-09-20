"""
Apply PipelineConfig.overrides to Settings.

Design rationale:
    An A/B eval is "same pipeline, one knob turned". The knobs already live
    in Settings as nested pydantic models, so an override is a dotted path
    into that tree ("reranker.top_k") plus a value. Applying them here, once,
    means run_eval.py can build the pipeline the normal way from the patched
    Settings — no second construction path to drift from the API's.

    Values arrive as strings from the CLI; json.loads gives ints, floats,
    bools and quoted strings the obvious types, and anything that is not
    JSON stays a plain string (model names, paths). Unknown paths raise so
    a typo cannot silently run the baseline twice.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from atlas.config import Settings


def parse_override(spec: str) -> tuple[str, Any]:
    """'reranker.top_k=10' → ('reranker.top_k', 10)."""
    key, sep, raw = spec.partition("=")
    key = key.strip()
    if not sep or not key:
        raise ValueError(f"override must look like section.field=value, got {spec!r}")
    return key, coerce(raw.strip())


def coerce(raw: str) -> Any:
    """Best-effort typing for a CLI value: JSON if it parses, else string."""
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def apply_overrides(settings: Settings, overrides: dict[str, Any]) -> Settings:
    """Return a copy of *settings* with each dotted-path override applied."""
    patched: BaseModel = settings
    for path, value in overrides.items():
        patched = _set_path(patched, path.split("."), value)
    assert isinstance(patched, Settings)
    return patched


def _set_path(model: BaseModel, parts: list[str], value: Any) -> BaseModel:
    head, *rest = parts
    if head not in type(model).model_fields:
        known = ", ".join(sorted(type(model).model_fields))
        raise ValueError(f"unknown settings field {head!r}; known: {known}")
    if not rest:
        # model_copy skips validation; re-validate so "reranker.top_k=abc"
        # fails here rather than deep inside the retriever.
        return type(model).model_validate({**model.model_dump(), head: value})
    child = getattr(model, head)
    if not isinstance(child, BaseModel):
        raise ValueError(f"{head!r} is a leaf field, cannot descend into {'.'.join(rest)!r}")
    return model.model_copy(update={head: _set_path(child, rest, value)})

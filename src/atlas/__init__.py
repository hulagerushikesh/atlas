"""
Atlas — production-grade agentic RAG platform.

Package layout:
    atlas.interfaces   — shared ABCs and Pydantic models (no logic here)
    atlas.ingestion    — document loaders, chunkers, dual indexing (Module A)
    atlas.retrieval    — hybrid retrieval + reranking (Module B)
    atlas.orchestration — query routing, decomposition, grading, generation (Module C)
    atlas.evaluation   — metrics, dataset runner, A/B comparison (Module D)
    atlas.api          — FastAPI app, tracing, caching, streaming (Module E)

Two numbers are recorded at import and nothing is printed here. They belong
in this module because it is the first `atlas` code any entry point runs —
`atlas.api.__init__` imports `create_app` eagerly, so a timer started in
`atlas.api.asgi` begins *after* torch, transformers and sentence-transformers
have already loaded and reports 0.00s for the import it was meant to measure.
That is what the first attempt did. `atlas.api.asgi` reads these and prints
the split; see its docstring for what the split is for.
"""

import time as _time

__version__ = "0.1.0"


def _boot_age_seconds() -> float | None:
    """Seconds since this process was forked, or None where that is unknowable.

    /proc/self/stat field 22 is the process start time in clock ticks since
    boot and /proc/uptime is seconds since boot, so the difference is how long
    the interpreter had been alive when this module was imported — image pull
    and interpreter start, with none of our own imports in it yet. Linux only:
    None on a developer's Mac, because a number that quietly measured
    something else off Cloud Run would be worse than no number.
    """
    try:
        with open("/proc/uptime") as fh:
            uptime = float(fh.readline().split()[0])
        with open("/proc/self/stat") as fh:
            started_ticks = float(fh.read().rsplit(") ", 1)[1].split()[19])
        import os

        return uptime - started_ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return None


#: Monotonic clock when `atlas` was first imported, and how old the process
#: already was at that moment. Cheap, side-effect free, and the only place
#: early enough to see the import graph it is measuring.
_IMPORT_STARTED = _time.monotonic()
_BOOT_AGE_AT_IMPORT = _boot_age_seconds()

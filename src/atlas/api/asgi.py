"""
ASGI entry point for uvicorn and docker-compose.

    uvicorn atlas.api.asgi:app --reload

Separated from app.py so that importing atlas.api.app (which happens in tests)
does not trigger create_app() and therefore does not require OPENAI_API_KEY at
import time.

Why this prints timings:
    A cold start on Cloud Run measured 36.9 s on 2026-10-21 (rev
    `atlas-api-00017-x5r`): 33.9 s from "Starting new instance" to Python's
    first log line, then 2.9 s of application startup. The 2.9 s is itemised
    by the startup logs. The 33.9 s was one undifferentiated block covering
    image pull, interpreter boot and the import of torch, transformers and
    sentence-transformers — three costs with three different fixes, and
    nothing said which one to pay for. Shrinking the image and deferring the
    imports are both plausible and only one of them is worth the risk.

    `pull_and_interpreter` is how old the process already was when the first
    `atlas` module loaded, so it is image pull plus interpreter start with
    none of our imports in it. `atlas_imports` is everything from there to a
    built app, which is where torch lives. The two sum to the block Cloud Run
    reports as one.

    `print` rather than structlog: logging is configured inside `create_app`,
    and the whole point of the first number is that it covers the time before
    anything has been configured. Cloud Run captures stdout.
"""

import time

from atlas import _BOOT_AGE_AT_IMPORT, _IMPORT_STARTED
from atlas.api.app import create_app

app = create_app()

_pull = (
    "unknown (not Linux)"
    if _BOOT_AGE_AT_IMPORT is None
    else f"{_BOOT_AGE_AT_IMPORT:.2f}s"
)
print(
    f"atlas_boot_profile pull_and_interpreter={_pull} "
    f"atlas_imports_and_app={time.monotonic() - _IMPORT_STARTED:.2f}s "
    f"(torch, transformers and sentence-transformers are in the second number)",
    flush=True,
)

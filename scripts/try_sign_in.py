"""
Try Google sign-in on the laptop without touching any real data.

    make try-sign-in EMAIL=you@gmail.com

Makes a throwaway folder, and in it a test organisation whose "duckdb" sheet
reads the existing atlas_duckdb collection, with EMAIL invited as its admin.
Then starts Atlas on http://localhost:8000 with sign-in on and a session
secret made up for this run only. Ctrl+C stops it; the folder is deleted.

Needs GOOGLE_CLIENT_ID in .env, and http://localhost:8000 listed as an
authorised JavaScript origin on that Google client.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


async def _seed(email: str) -> None:
    from atlas.api import tenancy
    from atlas.api.tenancy import Invitation

    store = tenancy.configure_tenancy("sqlite")  # data/atlas.db in the throwaway folder
    await store.init()
    await store.create_org("Sign-in test", org_id="org_signin_test")
    await store.create_workspace("org_signin_test", "duckdb", collection="atlas_duckdb",
                                 workspace_id="ws_signin_test_duckdb")
    await store.put_invitation(Invitation(email=email, org_id="org_signin_test",
                                          org_admin=True, invited_by="try_sign_in"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    from atlas.config import get_settings

    if not get_settings().google_client_id:
        print("GOOGLE_CLIENT_ID is not set in .env.", file=sys.stderr)
        return 1

    work = Path(tempfile.mkdtemp(prefix="atlas-sign-in-"))
    try:
        os.chdir(work)
        asyncio.run(_seed(args.email))
        env = {**os.environ, "AUTH_ENABLED": "true", "AUTH_STORE": "sqlite",
               "SESSION_SECRET": secrets.token_urlsafe(48), "REDIS_URL": ""}
        print(f"\nOpen http://localhost:{args.port}/app and sign in as {args.email}."
              "\nCtrl+C to stop.\n", flush=True)
        uvicorn = ROOT / ".venv" / "bin" / "uvicorn"
        with contextlib.suppress(KeyboardInterrupt):
            subprocess.run([str(uvicorn), "atlas.api.asgi:app", "--port", str(args.port)],
                           env=env, check=False)
    finally:
        os.chdir(ROOT)
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

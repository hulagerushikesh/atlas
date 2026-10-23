#!/usr/bin/env python3
"""
create_key.py — create an Atlas API key from the command line.

Usage:
    python scripts/create_key.py --name "My App" --email me@example.com
    python scripts/create_key.py --name "CI" --rate-limit 120

The generated key (atl_...) is printed once. Store it securely — it cannot
be retrieved again.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "src")


def _configure() -> str:
    """Point the facade at the store AUTH_STORE names, and say which one.

    Without this the module-level default wins and every script writes to a
    local `data/atlas.db` — so with AUTH_STORE=firestore in the environment,
    `create_key.py` used to print a key that production could never
    authenticate. Printing the backend is the other half: these commands
    change live auth when the production .env is loaded.
    """
    from atlas.api.auth import configure_store
    from atlas.config import get_settings

    settings = get_settings()
    configure_store(
        settings.auth_store,
        firestore_project=settings.auth_firestore_project or None,
    )
    return settings.auth_store


async def main(args: argparse.Namespace) -> int:
    from atlas.api.auth import create_key, init_db

    backend = _configure()
    await init_db()
    raw_key, key_id = await create_key(
        name=args.name,
        email=args.email,
        rate_limit_rpm=args.rate_limit,
    )

    print("─" * 55)
    print(f"  Key created  (id: {key_id})")
    print(f"  Store        : {backend}")
    print(f"  Name         : {args.name}")
    if args.email:
        print(f"  Email        : {args.email}")
    print(f"  Rate limit   : {args.rate_limit} rpm")
    print()
    print(f"  API key      : {raw_key}")
    print()
    print("  Store this key securely — it cannot be retrieved again.")
    print("─" * 55)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create an Atlas API key.")
    parser.add_argument("--name", required=True, help="Human label for this key")
    parser.add_argument("--email", default="", help="Owner email address")
    parser.add_argument("--rate-limit", type=int, default=60,
                        help="Max requests per minute (default: 60)")
    sys.exit(asyncio.run(main(parser.parse_args())))

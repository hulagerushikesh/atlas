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
from pathlib import Path

sys.path.insert(0, "src")


async def main(args: argparse.Namespace) -> int:
    from atlas.api.auth import create_key, init_db

    await init_db()
    raw_key, key_id = await create_key(
        name=args.name,
        email=args.email,
        rate_limit_rpm=args.rate_limit,
    )

    print("─" * 55)
    print(f"  Key created  (id: {key_id})")
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

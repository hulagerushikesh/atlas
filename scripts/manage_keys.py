#!/usr/bin/env python3
"""
manage_keys.py — list, revoke and restore Atlas API keys.

Usage:
    python scripts/manage_keys.py list
    python scripts/manage_keys.py revoke  <key_id>
    python scripts/manage_keys.py restore <key_id>

Which store it talks to is whatever AUTH_STORE says (sqlite by default,
firestore in production), so running this with the production .env loaded
revokes a production key. `scripts/create_key.py` is the other half.

Revocation is immediate — the middleware looks the key up on every request
and an inactive key is a 401 — and reversible, which is the point: the only
way to undo a mistaken revoke before this script existed was to edit the key
store by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

sys.path.insert(0, "src")


def _when(ts: float | None) -> str:
    if not ts:
        return "never"
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M")


async def _list() -> int:
    from atlas.api.auth import list_keys

    records = await list_keys()
    if not records:
        print("no keys in this store")
        return 0
    # Ids print in full, however wide that makes the column: a Firestore id is
    # a 64-character hash and `revoke` needs all of it, so a tidy truncation
    # would hand back something that cannot be pasted into the next command.
    w = max(len("id"), *(len(str(r.id)) for r in records))
    print(f"{'id':<{w}} {'name':<20} {'state':<8} {'rpm':>5} {'queries':>8}  "
          f"{'created (UTC)':<17} {'last query (UTC)':<17}")
    for r in records:
        print(f"{r.id!s:<{w}} {r.name[:20]:<20} "
              f"{'active' if r.is_active else 'REVOKED':<8} "
              f"{r.rate_limit_rpm:>5} {r.total_queries:>8}  "
              f"{_when(r.created_at):<17} {_when(r.last_query_at):<17}")
    return 0


async def _set_active(key_id: str, is_active: bool) -> int:
    from atlas.api.auth import set_key_active

    record = await set_key_active(key_id, is_active)
    if record is None:
        print(f"no key with id {key_id!r} in this store", file=sys.stderr)
        return 1
    verb = "restored" if is_active else "revoked"
    print(f"{verb}: {record.name} ({record.id})")
    return 0


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
    from atlas.api.auth import init_db

    backend = _configure()
    await init_db()
    print(f"store: {backend}")
    if args.command == "list":
        return await _list()
    return await _set_active(args.key_id, args.command == "restore")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List, revoke and restore Atlas API keys.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Show every key with its usage counters")
    for name, help_text in (("revoke", "Deactivate a key"), ("restore", "Reactivate a key")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("key_id", help="Key id as `list` prints it")
    sys.exit(asyncio.run(main(parser.parse_args())))

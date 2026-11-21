#!/usr/bin/env python3
"""
migrate_tenancy.py — move today's namespaces and keys into the tenancy model.

Usage:
    python scripts/migrate_tenancy.py            # dry run: says what it would do
    python scripts/migrate_tenancy.py --apply    # writes

Creates the public organisation, turns every Atlas Qdrant collection into a
workspace in it (keeping its collection, so nothing is re-ingested) and makes
every key editor on all of them, so every key in use keeps working. Safe to
re-run. Talks to whatever AUTH_STORE and QDRANT_URL say, so with the
production .env loaded it changes production.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "src")


async def main(args: argparse.Namespace) -> int:
    from qdrant_client import AsyncQdrantClient

    from atlas.api import auth, tenancy
    from atlas.api.namespaces import collection_to_namespace
    from atlas.config import get_settings

    settings = get_settings()
    project = settings.auth_firestore_project or None
    auth.configure_store(settings.auth_store, firestore_project=project)
    store = tenancy.configure_tenancy(settings.auth_store, firestore_project=project)
    await auth.init_db()
    await store.init()

    key = settings.qdrant.api_key
    qdrant = AsyncQdrantClient(url=settings.qdrant.url,
                               api_key=key.get_secret_value() if key else None)
    collections = (await qdrant.get_collections()).collections
    namespaces = [ns for c in collections if (ns := collection_to_namespace(c.name))]
    key_ids = [r.id for r in await auth.list_keys()]

    report = await tenancy.migrate(store, namespaces, key_ids, apply=args.apply)
    verb = "Wrote" if args.apply else "Dry run, would write"
    print(f"{verb} to: auth store {settings.auth_store}, Qdrant {settings.qdrant.url}")
    print(f"  public organisation   : {'created' if report.org_created else 'already there'}")
    print(f"  workspaces created    : {', '.join(report.workspaces_created) or 'none'}")
    print(f"  workspaces kept       : {', '.join(report.workspaces_kept) or 'none'}")
    print(f"  keys given access     : {report.keys_granted}")
    print(f"  keys already done     : {report.keys_already_done}")
    if report.keys_skipped_other_org:
        print(f"  keys in another org   : {report.keys_skipped_other_org} (left alone)")
    if not args.apply:
        print("Nothing written. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate namespaces and keys into tenancy.")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    sys.exit(asyncio.run(main(parser.parse_args())))

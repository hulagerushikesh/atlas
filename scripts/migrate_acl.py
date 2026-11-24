#!/usr/bin/env python3
"""
migrate_acl.py — give every existing passage an access list (E2).

Usage:
    python scripts/migrate_acl.py            # dry run: says what it would do
    python scripts/migrate_acl.py --apply    # writes

After E2.1 both searches read only passages whose `acl` shares one of the
caller's tokens, and a passage with no `acl` is readable by nobody. So before
that code is deployed every passage written before E2 needs `acl = ["all"]`,
which is exactly today's access: everyone with a role on the sheet.

For every Atlas Qdrant collection this creates the keyword index on `acl`
(so filtered search stays fast) and sets `acl = ["all"]` on the points that
have none, with `set_payload`: no re-embedding, ₹0. A passage that already
has an access list is never touched, so it is safe to re-run after a
document has been narrowed.

It also adds the same field to the keyword index files under data/index/,
which the deploy bakes into the image. The running server only rebuilds
those from Qdrant when the passage count changes, which this does not.

Talks to whatever QDRANT_URL says, so with the production .env loaded it
changes production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

INDEX_DIR = Path("data/index")


def patch_bm25_files(apply: bool) -> list[tuple[Path, int]]:
    """(file, entries missing acl) for each baked keyword index; writes if *apply*."""
    from atlas.access import ACL_FIELD
    from atlas.api.tenancy import ACCESS_ALL

    out = []
    for path in sorted(INDEX_DIR.glob("*/bm25_index.json")):
        entries = json.loads(path.read_text())
        missing = [e for e in entries if ACL_FIELD not in e.get("metadata", {})]
        if missing and apply:
            for e in missing:
                e.setdefault("metadata", {})[ACL_FIELD] = [ACCESS_ALL]
            path.write_text(json.dumps(entries, indent=2))
        out.append((path, len(missing)))
    return out


async def main(args: argparse.Namespace) -> int:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http.exceptions import UnexpectedResponse
    from qdrant_client.models import (
        Filter,
        IsEmptyCondition,
        PayloadField,
        PayloadSchemaType,
    )

    from atlas.access import ACL_FIELD
    from atlas.api.namespaces import collection_to_namespace
    from atlas.api.tenancy import ACCESS_ALL
    from atlas.config import get_settings

    settings = get_settings()
    key = settings.qdrant.api_key
    qdrant = AsyncQdrantClient(url=settings.qdrant.url,
                               api_key=key.get_secret_value() if key else None)
    missing = Filter(must=[IsEmptyCondition(is_empty=PayloadField(key=ACL_FIELD))])

    verb = "Wrote" if args.apply else "Dry run, would write"
    print(f"{verb} to Qdrant {settings.qdrant.url} and {INDEX_DIR}/")
    unmigrated = 0
    for c in (await qdrant.get_collections()).collections:
        if collection_to_namespace(c.name) is None:
            continue
        total = (await qdrant.count(c.name, exact=True)).count
        if args.apply:
            # First: Qdrant Cloud refuses any filter on a field without an
            # index (400 "Index required"), the count just below included.
            await qdrant.create_payload_index(c.name, field_name=ACL_FIELD,
                                              field_schema=PayloadSchemaType.KEYWORD)
        try:
            without = (await qdrant.count(c.name, count_filter=missing, exact=True)).count
        except UnexpectedResponse as e:
            # Dry run before any --apply: no index means no passage has been
            # migrated, so all of them are without (and --check refuses).
            if args.apply or e.status_code != 400 or b"Index required" not in e.content:
                raise
            without = total
        if args.apply:
            if without:
                await qdrant.set_payload(c.name, payload={ACL_FIELD: [ACCESS_ALL]},
                                         points=missing, wait=True)
            left = (await qdrant.count(c.name, count_filter=missing, exact=True)).count
            print(f"  {c.name:<40} {total:>6} passages, {without} given 'all', "
                  f"{left} still without")
        else:
            print(f"  {c.name:<40} {total:>6} passages, {without} without an access list")

        unmigrated += 0 if args.apply else without

    for path, n in patch_bm25_files(args.apply):
        print(f"  {path}: {n} keyword entries {'given' if args.apply else 'would get'} 'all'")
        unmigrated += 0 if args.apply else n
    if not args.apply:
        print("Nothing written. Re-run with --apply to write.")
    # --check is the deploy's guard: code that filters on `acl` shipped
    # against passages without one answers every question with "not covered",
    # which looks like a quiet bad day rather than a failure.
    return 1 if args.check and unmigrated else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--check", action="store_true",
                        help="dry run that exits 1 if any passage has no access list")
    sys.exit(asyncio.run(main(parser.parse_args())))

"""
Personal keys (E4, docs/e4-mcp-server.md): a key that acts as the person who
made it, for AI assistants that reach Atlas over MCP.

An organisation's service-account key acts as a machine: it reads what its
roles and groups allow, and never a document shared with one person's email.
A personal key carries its owner's identity instead, so an assistant sees
exactly what its owner sees in the console, Drive sharing included.

Stored as a tenancy record (kind "personal_key", key = the key's id) beside
the key itself. The owner is read on every request: removing the member, or
revoking the key, takes effect on the next call. A key with no record is a
service-account key and is resolved as before.
"""

from __future__ import annotations

import time
from typing import Any

from atlas.api import auth as auth_db
from atlas.api import tenancy

KIND = "personal_key"
MAX_PER_PERSON = 10
RATE_LIMIT_RPM = 30


async def create(principal: tenancy.Principal, name: str) -> tuple[str, str]:
    """A new key for *principal*, a signed-in person: (the key, its id)."""
    raw, key_id = await auth_db.create_key(name=name, email=principal.email,
                                           rate_limit_rpm=RATE_LIMIT_RPM)
    record = {"key_id": str(key_id), "user_id": principal.subject_id,
              "org_id": principal.org_id, "email": principal.email,
              "hosted_domain": principal.hosted_domain, "name": name,
              "created_at": time.time(), "revoked": False}
    try:
        await tenancy.get_tenancy().put_record(KIND, str(key_id), principal.org_id, record)
    except Exception:
        # Without its record the key would read as an old service key.
        await auth_db.set_key_active(key_id, False)
        raise
    return raw, str(key_id)


async def mine(principal: tenancy.Principal) -> list[dict[str, Any]]:
    rows = await tenancy.get_tenancy().list_records(KIND, principal.org_id)
    return sorted((r for r in rows if r.get("user_id") == principal.subject_id
                   and not r.get("revoked")), key=lambda r: r.get("created_at") or 0)


async def revoke(principal: tenancy.Principal, key_id: str) -> bool:
    store = tenancy.get_tenancy()
    record = await store.get_record(KIND, key_id)
    if record is None or record.get("user_id") != principal.subject_id or record.get("revoked"):
        return False
    # Refused first, then marked: a key is never left active without a record.
    await auth_db.set_key_active(key_id, False)
    record["revoked"] = True
    await store.put_record(KIND, key_id, record["org_id"], record)
    return True


async def principal_for_key(key_id: object) -> tenancy.Principal | None:
    """Who a key acts as. None: a personal key that no longer may act at all."""
    try:
        record = await tenancy.get_tenancy().get_record(KIND, str(key_id))
    except Exception as exc:
        raise tenancy.TenancyUnavailable(str(exc)) from exc
    if record is None:
        return await tenancy.principal_for_key(key_id)
    if record.get("revoked"):
        return None
    return await tenancy.principal_for_user(
        str(record["user_id"]), email=str(record.get("email", "")),
        hosted_domain=str(record.get("hosted_domain", "")))

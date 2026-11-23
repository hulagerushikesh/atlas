# E1 — Identity and tenancy: design

Written 2026-11-20 after D8 (owner approved phases E1–E6). Product context:
`docs/enterprise-product.md`. This note is the engineering design for E1;
code starts at box E1.1.

**Exit test (from the product note):** two organisations on one deployment
cannot see each other's workspaces, documents, answers or usage — proved by
a test suite that tries every route.

---

## 1. What exists today (read from the code, 2026-11-20)

| Piece | Today | Problem for a company |
|---|---|---|
| Who is asking | An API key (SHA-256 hash in SQLite or Firestore) with name, email, rate limit | No user, no organisation, no role |
| Key admin | One shared `X-Admin-Secret` header for create, list, revoke | Anyone with the secret runs every company |
| Namespace | One Qdrant collection `atlas_{name}`; global names | Two companies cannot both have "engineering" |
| Who may read a namespace | Any valid key, any namespace | No separation at all |
| Public routes | `/namespaces` and `/namespaces/{ns}/sources` need no key | Every set's name and file list is visible to strangers |
| Answer cache | Keyed by namespace + question | Safe only while names are global and readers are everyone |
| Keyless demo | One namespace, ₹10/day cap, 3 a minute per visitor | Keep: becomes a public workspace |

## 2. The model

```
Organisation ─┬─ Workspace (holds documents; one Qdrant collection each)
              ├─ User (signs in with Google) ── Membership(workspace, role)
              └─ Service account (the old API key) ── scopes(workspace, role)
```

- **Organisation**: id, name, optional Google Workspace domain (used to
  place a signing-in user automatically).
- **Workspace**: id, org id, name, and the Qdrant collection it reads. New
  workspaces get `atlas_{org}__{workspace}` so names may repeat across
  organisations; existing ones keep their collection, so nothing is
  re-ingested.
- **Roles**, per workspace: **reader** (ask), **editor** (ask + add or
  remove documents), **admin** (also members, service accounts, usage).
  An organisation admin is admin on every workspace in it.
- **Service account**: today's API key plus an org id and workspace scopes.
  Machines use these; people sign in.
- **Principal**: what every request carries after the middleware —
  org id, kind (user / service / visitor), subject id, and roles by
  workspace. Routes never look at keys or cookies again; they ask
  `authorize(principal, workspace, action)`.

Groups (for document permissions) are deliberately left to E2, which also
maps them from Google.

## 3. Sign-in (box E1.3)

Google Identity Services in the console → Google ID token → `POST
/auth/google` → server verifies the token (audience = Atlas's client id,
issuer Google, not expired) → sets a signed session cookie (HttpOnly,
Secure, SameSite=Lax, 8 hours). The user joins an organisation by its
Workspace domain (`hd` claim) or by an invitation from an admin; a personal
Gmail address gets in only by invitation. ₹0: the Google client is free.
The owner creates the client id once (owner item O7).

The shared admin secret stays only as break-glass: it can create the first
organisation admin, and a setting turns it off afterwards.

## 4. Where isolation is enforced

Every one of these becomes a check, and each has a test that tries the
other organisation:

1. `/namespaces` returns only workspaces the principal has a role on; no
   longer public.
2. `/namespaces/{ns}/sources` needs reader on that workspace; no longer public.
3. `/query` needs reader; the workspace is looked up inside the
   principal's organisation, so another organisation's name is "not found",
   never "forbidden" (no confirming that it exists).
4. `/ingest`, `/ingest/upload` need editor.
5. The answer cache is keyed by workspace id, not name.
6. `/usage` shows the principal's own usage; admins see their organisation's.
7. `/keys` becomes service-account management inside one organisation.
8. Log lines carry org and workspace ids (E4's audit builds on them).
9. The keyless demo becomes a public workspace in a demo organisation;
   its ₹10/day cap and per-visitor limit are unchanged.

**A route policy table** lists every route as public, or authenticated with
a required action. A test walks the app's routes and fails if one is
missing from the table, so a route added later cannot skip the check.

## 5. Storage and migration

Same pattern as keys today: one store interface, SQLite for tests and the
laptop, Firestore live (free tier; one or two extra document reads per
request at today's traffic). No caching of principals at first, so a
revoked key or removed member stops working on the next request, as now.

A one-off, re-runnable migration creates the public organisation, turns
every existing collection into a workspace in it, and every existing key
into a service account with editor on those workspaces — so every key in
use today keeps working unchanged. It writes to the live database, so the
owner runs it (₹0).

## 6. Boxes

| Box | Builds | Proved by |
|---|---|---|
| **E1.1** | Model + store (both backends) + principal on every request + migration; no change in behaviour | Existing suite unchanged; migration tests; a key resolves to the same access it has today |
| **E1.2** | Route policy table, `authorize` on every route, private listings, cache keyed by workspace | Isolation suite: two organisations, every route, both directions, in CI |
| **E1.3** | Google sign-in, sessions, invitations, a members and service-accounts page in the console | Sign-in tests with a fake Google key; console checked in the browser |
| **E1.4** | Migration run and deployed | Live: the demo still answers a visitor; a second organisation's key gets "not found" on the demo workspace |

### Decided while building E1.2 (2026-11-21)

- **Unmigrated keys and the dev box are confined to the public
  organisation.** They keep today's access there, including a pre-E1
  collection with no workspace record yet, and reach nothing in any other
  organisation. A name containing `__` is never resolved this way, because
  `atlas_{org}__{ws}` is how new organisations' collections are named.
- **Fail closed.** A tenancy store that cannot be read answers 503; it never
  falls back to legacy access.
- **Not found, not forbidden.** A workspace the caller cannot read answers
  exactly like one that does not exist. A reader trying to add documents
  gets 403, since it already knows the workspace exists.
- **The keyless demo** may also open the set list and the demo sheet's
  sources (30 a minute per visitor, separate from its 3 questions a minute);
  the list shows the demo sheet only.
- **Public metrics** label requests by route template, not URL, so they no
  longer carry set names.
- **Left for E1.3:** creating a workspace in a new organisation (today only
  the store can), service-account management inside an organisation (`/keys`
  is still the shared admin secret, and a key made there is legacy), and
  `/usage` for an organisation admin (it shows the caller's own key).

### Decided while building E1.3 (2026-11-23)

- **The cookie holds an account number and an expiry, never roles.** Roles
  are read from the store on every request, so removing a member or changing
  a role applies on their next request. The cookie is HMAC-signed with
  `SESSION_SECRET` (a new secret for T21), HttpOnly, Secure, SameSite=Lax,
  8 hours. Signed-in people are limited to 60 requests a minute.
- **A cookie wins over a stored API key** in the same browser, and every
  cookie-carrying write must also send `X-Requested-With: atlas` (the
  console always does). The API's CORS policy allows no credentials, so
  another site cannot send both.
- **Placement order:** existing user → invitation (used up on first sign-in,
  with its grants) → organisation whose domain is the token's `hd` claim
  (joins with no sheets) → refused. The email address alone never places
  anyone: `hd` is what proves Google runs the account for that domain.
- **Only the client id is used**, never the client secret, which is stored
  nowhere. Google's certificates are cached for the max-age Google sends; an
  unknown key id refetches at most once a minute.
- **Revoking a service account deactivates its key and keeps its record.**
  Deleting the record would turn it back into a legacy key with the public
  organisation's access.
- **New sheet names are their own collection slug** (`a-z 0-9 - _`, no
  `__`), so two names can never share a collection.
- **Break-glass:** `POST /admin/orgs` and `POST /admin/invitations` (admin
  secret) make an organisation and invite its first admin; everything after
  is that admin, signed in, on the Members page.
- **Sign-in is on only with auth on** and both `GOOGLE_CLIENT_ID` and
  `SESSION_SECRET` set. `/privacy` exists because Google will not let the app
  leave Testing without one.
- **Still not done:** `/usage` for an organisation admin, and charging a
  signed-in person's questions to their own usage record (they count against
  the global daily cap only). Both move to E4 (budgets and audit).

## 7. Not in E1, on purpose

SAML, SCIM, groups and per-document permissions (E2), audit store (E4),
per-workspace budgets (E4), principal caching (E5, once traffic needs it).

Nothing here has been validated with a buyer; it follows what company
security teams commonly ask for (product note §7).

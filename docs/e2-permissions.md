# E2 — Document permissions: design

Written 2026-11-23, after E1 went live (T21). Product context:
`docs/enterprise-product.md` §4–5. E1's design: `docs/e1-identity.md`. This
note is the engineering design for E2; code starts at box E2.1.

**Exit test (from the product note):** a reader without access never
receives a forbidden passage's text, title, or an answer built from it,
proved by adversarial tests that include cached and reworded questions.

---

## 1. What exists today (read from the code, 2026-11-23)

| Piece | Today | Problem once documents have owners |
|---|---|---|
| Passage record | Qdrant payload: content, doc id, source, position, content hash | Nothing says who may read it |
| Dense search | `query_points` on the sheet's collection, no filter | Returns any passage in the sheet |
| Keyword search | BM25 over the whole sheet in memory (rebuilt from Qdrant, or baked into the image for the demo) | Same |
| Retrievers | Built once per sheet and shared by every caller | The caller's access is not an input |
| Answer cache | Keyed by workspace id + question | One person's answer is served to everyone in the sheet |
| Source list | `/namespaces/{ns}/sources` scrolls the whole collection | Shows every title |
| Removing a document | No route; only a whole re-ingest | A document cannot be taken back |
| Groups | None (E1 left them to E2) | Nothing to grant access to |

What already helps: every request carries a `Principal` (E1); a sheet's
collection is private to its organisation; every answer logs the ids of the
passages it used (M9 S1); passage ids are deterministic per document.

## 2. The model

```
Organisation ─┬─ Group (name, members: users and service accounts)
              └─ Workspace ── Document (id, source, title, access list)
                                └─ Passage (copies its document's access list)
```

- **Access list**: a short list of tokens on every document, copied onto
  each of its passages:
  - `all` — everyone with a role on the sheet (today's behaviour);
  - `group:{id}` — members of one group in the sheet's organisation;
  - `user:{id}` — one person or service account.
- **What a caller holds**, worked out per request from the principal:
  `all`, its own `user:{id}`, and `group:{id}` for each group it is in.
  Visitors and legacy keys hold `all` only.
- **A passage is readable** when the two lists share a token. A passage
  with no access list is readable by nobody (fail closed); the migration
  gives every existing passage `all`, so nothing changes for anyone today.
- **Organisation admins get no bypass.** They manage sheets, members and
  groups, but read only what their own tokens allow, as in Google Drive.
  An admin who must read a document adds themselves to its group, which
  E4's audit trail will record.
- **New uploads default to `all`.** An editor may narrow a document to
  groups when adding it, or change it later.

Groups are Atlas's own in E2, kept on the Members page. E3 maps Drive
sharing (people and Google Groups) onto the same tokens, so retrieval does
not change when the connector arrives.

## 3. Where it is enforced

Rule from the product note: **filter at retrieval, never after.** A
forbidden passage is never fetched, so it is never reranked, graded,
quoted, cached or cited. Filtering an answer afterwards leaks through its
wording.

1. **Dense search:** a Qdrant filter, `acl` matches any of the caller's
   tokens, on the search itself, with a keyword payload index on `acl` so
   filtered search stays fast.
2. **Keyword search:** each BM25 entry carries `acl`; entries the caller
   cannot read are dropped before ranking is cut to top-k, so they never
   leave the index.
3. **One retriever, many callers:** the caller's tokens become an argument
   of `retrieve()`, passed through the pipeline (plain, decomposed and HyDE
   searches alike). Retrievers stay shared per sheet.
4. **Answer cache:** the key adds a fingerprint of the caller's tokens for
   that sheet. People with the same access share answers; anyone else
   misses and runs the pipeline. Simple to prove; costs some hit rate,
   which E2.5 can win back.
5. **Source list:** filtered the same way, so a forbidden title never shows.
6. **Citations and the evidence trail:** built only from retrieved
   passages, so they inherit the filter. A test checks it anyway.
7. **"Not covered" looks the same either way.** A question about a forbidden
   document gets the answer a missing document gets.

Not a leak path: the router, the question splitter and HyDE read only the
question and the sheet's description, never passages.

## 4. Changing and removing documents

- **Change access:** `PUT .../documents/{id}/access` rewrites `acl` on the
  document's passages in Qdrant (`set_payload` by doc id: no re-embedding,
  ₹0) and in the keyword index, then clears that sheet's cached answers.
- **Remove:** `DELETE .../documents/{id}` deletes the passages from both
  indexes and clears the sheet's cached answers. Clearing the whole sheet,
  not only answers that cited the document, is deliberate: an answer can
  depend on a passage it did not cite.
- Both need editor on the sheet. Both go to the log with the document id;
  E4 turns that into the audit record.
- The known gap from M9 still applies: with two servers and no shared cache,
  the other server keeps its cached answers for up to an hour. Live runs
  `--max-instances 2`, so E2.3 either turns on the shared cache or limits
  live to one server until E5. That is priced before it is built.

## 5. Storage and migration

- Documents get a small record (sheet, id, source, title, access list) in
  the same tenancy store as E1 (SQLite for tests, Firestore live). The
  passages' copy of `acl` is what search reads, so a store outage cannot
  widen access.
- Groups go in the same store: org id, name, member ids.
- A one-off, re-runnable migration sets `acl = ["all"]` on every existing
  passage (`set_payload`, no re-embedding), creates the payload index, and
  writes a document record per source. The demo's baked keyword index is
  rebuilt with `acl` before the deploy that turns the check on. ₹0. It
  writes to the live database, so the owner runs it.

## 6. Boxes

| Box | Builds | Proved by |
|---|---|---|
| **E2.1** | Access lists on passages, groups, filter in both searches, migration | Unit tests: a reader outside a group gets no passage from a group-only document, by dense, keyword and decomposed search |
| **E2.2** | Cache key, source list, citations and evidence respect it | Tests: a privileged person asks first, then an unprivileged one asks the same and a reworded question; no hit, no title, no text |
| **E2.3** | Change access, remove a document; cache cleared; one-server or shared cache decided | Tests; a removed document stops being answered on the next question |
| **E2.4** | Adversarial suite in CI, then the same run live with two test accounts | Live: the "Live check" organisation, one forbidden document with a unique phrase, zero leaks; a few paise of answers |
| **E2.5** | Evidence-based reuse (old 9.4), only for callers allowed every cited passage, behind a switch | Paraphrase hit rate measured; the E2.4 suite still passes with it on |

Each box costs ₹0 to build. Only E2.4's live run spends anything, a few
paise of model calls.

### Decided while building E2.1 (2026-11-23)

- **The caller's tokens travel in a context variable** (`atlas/access.py`),
  set by the auth middleware for every request and read by the dense and
  keyword retrievers where they search. Threading an argument through the
  pipeline would leave one path (decomposed, HyDE, retry, streaming) to
  forget; a test proves the streamed path sees the tokens too. Outside a
  request (laptop scripts) nothing is filtered.
- **A request starts with no tokens**, and a passage with no `acl` matches
  no request. So the live code must not ship before `scripts/migrate_acl.py
  --apply`; the deploy script now refuses until every passage has a list.
  The migration is harmless to the code live today, which ignores `acl`.
- **Keyword ranking scores the whole sheet, then drops what the caller
  cannot read before the top-k cut.** Scores do not depend on who asks, and
  a forbidden passage cannot take a place in the results.
- **Service accounts hold `user:{key id}`**, like people; group membership
  for them, and the group controls on the Members page, come with E2.3.
- **Document records** (§5) move to E2.3, where changing access needs them.
  E2.1 needs only the passages' own `acl`.
- **A member update that does not mention groups keeps them**, so the
  current console cannot take groups away by accident.

### Decided while building E2.2 (2026-11-23)

- **Two locks on cached answers, not one.** The key holds the caller's
  tokens *that the sheet uses* (its tokens intersected with every token on
  the sheet's passages), so people who can read exactly the same passages
  share answers: everyone on the demo still shares one entry, and a
  personal `user:{id}` token splits nothing unless a passage is shared with
  that person. The entry also stores each retrieved passage's access list,
  and a hit is served only if the asker may read all of them. The second
  lock covers what the first cannot see: this server's keyword copy may lag
  a document another server just added. An entry without lists (from before
  E2) is never served.
- **The source list shows a caller only what it may open**, and never how
  much is hidden: its counts are its own, and an index mismatch is reported
  to it without numbers.
- **Citations and the evidence trail need no code of their own:** they are
  built from retrieved passages only, which the filter already decided.
  The cached path re-checks them (lock 2).

## 7. Not in E2, on purpose

Drive sharing and Google Groups (E3), the audit record (E4), passage-level
permissions inside one document (nobody has asked), and deny rules (an
allow list is enough while sources are Drive-like).

The owner confirmed both choices above on 2026-11-23 (D9): **admins get no
bypass**, and **new uploads default to everyone on the sheet**.

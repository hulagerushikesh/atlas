# E3 — Google Drive connector: design

Written 2026-11-27. Product context: `docs/enterprise-product.md` §4–6.
Permissions it builds on: `docs/e2-permissions.md`. The owner chose Drive
first on 2026-11-27 (D10) instead of waiting for the five conversations;
their own company's Microsoft 365 Copilot setup is the reference point in §2.

**Exit test (from the product note):** a page deleted or unshared in Drive
stops being answered within 15 minutes, measured live.

---

## 1. What exists today

| Piece | Today | What a connector needs |
|---|---|---|
| Getting documents in | Upload in the console, or a path on the server | Pull from Drive, unattended |
| Access lists | `all`, `group:{id}`, `user:{id}` on every passage (E2) | Drive's own sharing, mapped onto the same tokens |
| Changing / removing one document | Routes exist (E2.3); a per-sheet version tells every server | Called by the sync, not by a person |
| A caller's tokens | Built from the signed-in principal | Also their verified email, and their Workspace domain |
| Background work | None scheduled except the weekly health check | A sync every few minutes |

Retrieval, the cache, the source list and citations do not change: E2 put
the access check inside both searches, so a connector only has to write the
right list on each passage.

## 2. How others do it (researched 2026-11-27)

| | Microsoft 365 Copilot connectors | Glean | Atlas E3 (proposed) |
|---|---|---|---|
| Model | Synced connectors copy content and an access list per item into Microsoft's index; federated ones query the source live ([overview][ms-overview]) | Crawls plus webhooks; permissions applied at query time ([key terms][glean-terms]) | Synced: content and access list on every passage |
| Who can read | The item's list names users, groups or everyone; non-Microsoft groups become "external groups" that must be kept in sync ([external groups][ms-groups]) | Separate identity crawls for users and groups | Drive users, Workspace domain, "anyone"; Google Groups via a mapping (§4) |
| Freshness | Confluence and Jira Cloud: incremental every 15 min, full daily ([Confluence][ms-confluence], [Jira][ms-jira]); permission changes reportedly picked up only on the full crawl | Webhooks where the source has them; e.g. hourly identity refresh on GitLab ([GitLab][glean-gitlab]) | Change feed every 5 min, sharing included; full check daily |
| Default when unsure | Docs warn that "everyone" on sensitive items is the main misconfiguration risk ([blog][ms-risk]) | — | Deny: a file whose sharing cannot be read is readable by nobody |

The owner's company uses Copilot with SharePoint/OneDrive, Confluence, Jira,
Teams chats and a few MCP servers. Two things follow. Every serious product
here is *synced with a per-item access list*, which is exactly the shape E2
built, so Drive is the first instance of a general connector, not a one-off.
And permission freshness is where the incumbents are weakest (daily for
permission changes), so a 15-minute guarantee that includes *unsharing* is
worth measuring and saying out loud.

## 3. Access to Drive: the decision with a price on it

| Option | How | Cost / limit | Verdict |
|---|---|---|---|
| **A. Per-user sign-in, `drive.readonly`** | An editor clicks "Connect Google Drive" and picks a folder; Atlas syncs with their permission | `drive.readonly` is a *restricted* scope. While the Google app stays in **Testing**, up to 100 named test users, no review, ₹0 — but refresh tokens expire after 7 days, so a test connection must be reconnected weekly ([audience][g-audience]). Publishing to everyone needs a yearly security assessment (CASA), reported at about $540/year ≈ ₹45,000/year ([one report][casa]) | **Build on this**, in Testing |
| B. `drive.file` + Google Picker | The person picks files; non-sensitive scope, no assessment | Picking a *folder* reportedly does not grant access to the files inside it ([thread][drive-file]); every file would be picked by hand | Rejected for folders |
| C. Service account with domain-wide delegation | A company's Workspace admin grants Atlas read access for the whole domain | No Google review, but needs a Workspace admin; the owner's account is personal Gmail, so it cannot be tested here | The enterprise route later; same sync code |

A company can also mark Atlas **Trusted** in its own Workspace admin
console, which lifts the 100-user cap and the 7-day expiry for its users
without a public review ([audience][g-audience]). So the assessment is only
needed to sell to companies that will not do that. Decision for later (D11),
not for E3.

**Keep Drive in its own Google app (found while building E3.1).** The
sign-in app is about to be published (O7) so that anyone invited can sign
in; it asks only for name and email, which needs no review. If the Drive
scope were added to that same app, publishing it would put a restricted
scope in front of Google's review. So Drive gets its own OAuth client in a
separate Google Cloud project that stays in Testing, and the sign-in app
stays reviewable as it is. The code reads the Drive client's id from
`DRIVE_CLIENT_ID` when set, else the sign-in client's.

## 4. Drive sharing → Atlas tokens

| Drive permission on a file | Token on its passages | Who holds it |
|---|---|---|
| `user` / owner, email *e* | `email:{e}` | A signed-in person whose verified Google email is *e* (new token, §5) |
| `domain` *d* (with or without "discoverable") | `domain:{d}` | A person signed in with a Google Workspace account whose `hd` claim is *d* (new token) |
| `anyone` (link or public) | `all` | Everyone with a role on the sheet — narrower than Drive's own rule |
| `group`, Google Group *g* | `group:{id}` if an admin has linked *g* to an Atlas group; otherwise nothing | Members of that Atlas group |
| Sharing not readable by the connecting account | *(empty list)* | Nobody — fail closed, counted in the sync report |

- Emails are used rather than Atlas user ids so a person who joins the
  organisation later reads what Drive already shares with them, with no
  re-sync. Only *verified* Google emails count, so a password account
  cannot claim one.
- Google Group membership is not readable without a Workspace admin
  (Cloud Identity / Admin SDK). E3 therefore lets an organisation admin
  link a Google Group's address to an Atlas group on the Members page; an
  unlinked group grants nothing, and the sheet's Drive panel says how many
  files are shared that way. Reading Google Groups directly is the
  domain-wide-delegation follow-up (option C).
- The connecting person must be able to see a file's sharing (Drive shows
  it to editors). A file they can only view is synced with an empty list
  and reported, never opened to the sheet.

## 5. What gets built

```
Connection (sheet, Drive folder id, connected by, encrypted refresh token,
            change cursor, last sync, counts)
   │
   ├─ first sync: walk the folder tree → for each supported file:
   │      fetch text → chunk/embed (existing indexer) → acl from §4
   │
   └─ every 5 min: Drive change feed since the cursor →
          removed / trashed / moved out of the folder → delete_document (E2.3)
          content changed (version differs)           → re-index
          sharing changed                              → set_document_acl (₹0)
          then the sheet's version moves on (E2.3), the cursor is saved
   daily: full walk; anything Atlas holds that Drive no longer lists is removed
```

- **Files:** Google Docs (exported as text), PDF, plain text and Markdown.
  Sheets, Slides and images are skipped and listed as skipped. A file's
  source name is its Drive path, its document id the Drive file id, so a
  rename does not create a duplicate (the T26 lesson).
- **Principal:** gains `email` and `hosted_domain` from the sign-in token;
  `access` adds `email:{e}` and `domain:{d}`. API keys get neither.
- **Secrets:** refresh tokens are encrypted with a key held in Secret
  Manager, never stored or logged in plain text. One new secret version,
  about ₹5/month (the project is past its free versions).
- **Trigger:** Cloud Scheduler calls an authenticated sync route every 5
  minutes (free tier covers it). Side effect: the server is woken every 5
  minutes, which should also remove most of the ~15 s first-question wait
  found on 2026-11-14; to be measured, not assumed.
  *As built (T32):* one job, `POST /connectors/drive/tick`, with a Google
  OIDC token whose audience is `DRIVE_PUBLIC_URL` and whose email is
  `DRIVE_SCHEDULER_EMAIL`; anything else gets 401. Each sheet's pass reads
  the feed and walks the folder only when a change names a held file or
  lands under one of the folder's folders; a full walk runs when the last
  one is older than `DRIVE_FULL_EVERY_SECONDS` (a day), so the daily check
  needs no second job. The work runs inside the request, because Cloud Run
  gives a request-billed server its processor only while a request is open.
  The cursor is read before the walk, so a change made during it is seen
  next time; an unreadable cursor walks and starts afresh.
- **Console:** on a sheet, a "Google Drive" panel: connect, pick a folder,
  last sync, files synced / skipped / not readable, disconnect (which
  removes the synced documents).
- **Cost:** the Drive API is free; embedding is the existing per-passage
  cost (a 20-page document ≈ ₹0.01). A sync that finds no change calls no
  model.

## 6. Boxes

| Box | Builds | Proved by |
|---|---|---|
| **E3.1** | Connect a folder (OAuth, encrypted token), first sync, §4 mapping, email/domain tokens, Google Group links | Tests against a fake Drive: each sharing type lands as its token; a person not shared on a file gets nothing from it, by search, cache and source list; unreadable sharing is closed |
| **E3.2** | Change feed every 5 min, daily full check, console panel | Tests: delete, trash, move out, edit, unshare and re-share each reach the passages; a re-run changes nothing |
| **E3.3** | Live run on the owner's Drive | A shared document is answered; after it is unshared (and, separately, deleted) in Drive it stops being answered within 15 minutes, measured to the minute |

## 7. After Drive (for the owner's decision, D11)

From the owner's company stack, in the order the shared design makes cheap:

1. **Atlas as an MCP server** — a `search` and `ask` tool over Atlas's API,
   so Copilot, Claude or any MCP client can query a sheet with the caller's
   own permissions. Small, and it is how Atlas would sit *inside* a
   Copilot setup rather than compete with it.
2. **Confluence Cloud** — space permissions plus page restrictions map to
   the same tokens; Microsoft's connector refreshes every 15 min.
3. **SharePoint / OneDrive** — Microsoft Graph's delta query gives changes
   with sharing information ([delta][ms-delta]); needs a Microsoft Entra
   app and an admin's consent, and a test tenant.
4. **Jira Cloud** — project and issue-security permissions.
5. **Teams chats** — the hardest: chat content is behind Microsoft's
   protected APIs, and Microsoft's own route is its Copilot-licensed MCP
   server. Last, if at all.

## 8. What this note does not claim

The prices above come from other developers' reports, not from quotes; the
folder behaviour of `drive.file` comes from forum answers, and whether a
sharing change alone produces an entry in Drive's change feed is read from
the reference wording, not tested. E3.1 starts with a one-hour check of the
last point against the owner's Drive, because the exit test depends on it;
if it does not, the 5-minute sync re-reads the sharing of every file in the
folder instead (more API calls, still free).

[ms-overview]: https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/overview
[ms-groups]: https://learn.microsoft.com/en-us/graph/connecting-external-content-external-groups
[ms-confluence]: https://learn.microsoft.com/en-ie/microsoft-365/copilot/connectors/confluence-cloud-deployment
[ms-jira]: https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/jira-cloud-deployment
[ms-risk]: https://blog.bajonczak.com/bringing-your-own-data-into-microsoft-365-copilot-without-breaking-security/
[ms-delta]: https://learn.microsoft.com/en-us/graph/api/driveitem-delta
[glean-terms]: https://docs.glean.com/connectors/key-terms
[glean-gitlab]: https://docs.glean.com/connectors/native/gitlab-onprem/about
[g-audience]: https://support.google.com/cloud/answer/15549945
[casa]: https://yurudeep.com/posts/aicoding/2026/20260717/en/
[drive-file]: https://groups.google.com/g/google-apps-script-community/c/_W-NKbttfbo

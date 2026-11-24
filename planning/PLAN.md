# Atlas — the plan

**Read this file first, every session. It is the only planning file that is
current.** Last updated 2026-11-20.

Status of this plan: **APPROVED by the owner, 2026-11-12.** Work proceeds
through section 4 in order.

---

## 1. What Atlas is for

Atlas answers questions about a set of documents, shows the exact passages
each claim came from, and says how far to trust its own answer.

**Since 2026-11-20 (owner):** Atlas is built and judged as an
**enterprise-grade product** a company of thousands would buy, not a solo
project that does the basics well; its portfolio value follows from that.
Product, gaps and phases: `docs/enterprise-product.md`; **D8 approved
2026-11-20**: phases E1–E6 are milestones in section 3.

So the goal has two halves:

| Half | Meaning | State |
|---|---|---|
| **A. It works, and that is measured** | built, tested, live, costs known | **Done** — 20 of 20 |
| **B. It is seen and understood** | strangers get it in two minutes; the owner can present it; it stays alive without attention | **In progress** — see section 3 |
| **C. An enterprise product** (M9 2026-11-19; E1–E6 2026-11-20, D8) | sign-in and organisations, document permissions, a connector, governance, scale, quality loop | **In progress** — see M9 and E1–E6 |

Half A was the old roadmap. Half B is this plan.

## 2. Where it stands (checked 2026-11-12)

| | |
|---|---|
| Live site | https://atlas.hulage.in — console at `/app` |
| Live version | revision `atlas-api-00046-htz`, deployed 2026-11-14, carries every merged change up to T15 |
| Demo documents | DuckDB 2.0 manual — 226 pages, 3,975 passages |
| Measured quality | finds the right page **16 of 16**; answers stick to the pages **0.99**; answers correct **0.77** (16 test questions, 2026-11-03) |
| Cost | **₹0** while idle · about **₹0.20** per question · ₹6 per full test run |
| Speed | about 7 s typical, 14 s slow case; first visit after idle waits ~15 s |
| Code health | 892 automated tests, all passing on GitHub |
| Real use | **No question of any kind has reached the live site since 3 Nov.** The two invited friends sent 6 questions that day and never returned. |
| Money runway | Gemini prepaid balance was **₹161.51** when last seen (~4 Nov), auto-reload **on** (AutoPay, owner's decision 2026-11-18), so the site no longer stops at ₹0; visitor spend is held by the ₹10/day cap. |
| **The locked door** | **A visitor cannot ask anything without a personal key from the owner, pasted into Settings.** The landing page says "Open the console" and does not mention it. Anyone arriving from the README, the resume or the landing page meets "Not authorised". Found 2026-11-12; see decision D5. |

**The honest read.** The build finished on 24 Oct. Every session since has
been repair and polish with no milestone behind it — four changes shipped
for first-time visitors, and no first-time visitor has seen any of them.
The project does not need more building. It needs people, a way to present
it, and a way to leave it running safely.

## 3. The redesign

Three small milestones, in order. Ten checkboxes in total. Then the project
goes into maintenance and stops consuming sessions.

### M6 — A stranger gets it in two minutes

- [ ] **6.1** A 90-second screen recording (question → answer → evidence →
      trust verdict) sits at the top of the README and on the landing page.
- [ ] **6.2** The README's first screen is: what it is, one screenshot,
      three measured numbers, the live link. Every number quoted in README,
      landing page and pitch is checked against one source by the test
      suite, so they cannot drift again.
- [ ] **6.3** Five outside people each ask at least two real questions in
      one visit. Counted from the server logs (free).
- [ ] **6.4** What those visits showed is written as at most five findings,
      and the top one is fixed and live.

### M7 — The owner can present it

- [x] **7.1** A one-page interview sheet: the 12 questions an interviewer
      will ask about Atlas, each with a three-sentence answer and the number
      behind it.
- [x] **7.2** A public case study, 800 words at most: the problem, three
      decisions the measurements overturned, what it costs to run.
- [x] **7.3** Fresh resume bullets with today's numbers, written here as
      text for the owner to paste (the resume lives in another project).

### M8 — It stays alive on its own

- [ ] **8.1** Money runway is known and safe: balance checked, auto-reload
      decided, and when the balance is gone the site says "demo paused"
      in plain words instead of failing.
- [x] **8.2** A weekly automatic check, costing under ₹1 a month, that
      contacts the owner only when something is wrong.
- [ ] **8.3** Loose ends closed: ~~old Gemini key revoked (O4)~~ (revoked 2026-11-19) · ~~old FastAPI
      documents kept or deleted~~ (kept, D3) · ~~the "depth setting ignored on a repeat
      question" defect fixed or accepted~~ (accepted, D4) · this file marked "maintenance" (last, once everything else is ticked).

### M9 — Ready for a 10,000-person company (opened by the owner 2026-11-19, D7)

Design and numbers: `docs/company-scale.md`. Measure before building.

- [ ] **9.1** A pasted question with hidden characters (WhatsApp) reuses the
      earlier answer instead of paying again. Built and tested 2026-11-19;
      ticked when live.
- [ ] **9.2** Every answer's log line names the passages it read (IDs and a
      fingerprint, no text). Built 2026-11-19; ticked when live.
- [x] **9.3** Reuse measured on 48 rewordings of 16 questions, ≈₹0.01:
      **69% would reuse, 1 of 120 unrelated pairs would match wrongly**
      (rule: 3 of top 5 passages shared and the questions close in meaning).
- ~~9.4~~ evidence-based reuse → moved to **E2.5** (D8: behind permissions).
- ~~9.5~~ per-document permissions → became **E2.1–E2.4** (D8).

### E1–E6 — An enterprise product (approved by the owner 2026-11-20, D8)

Why and for whom: `docs/enterprise-product.md`. E1 design: `docs/e1-identity.md`.

**E1 Identity and tenancy** — two organisations cannot see each other's anything.
- [x] **E1.1** Organisations, workspaces, users, roles and service accounts
      stored; every request carries "who is asking"; today's keys keep working.
- [x] **E1.2** Every route checks it; listings private; isolation suite in CI.
- [x] **E1.3** Google sign-in, invitations, a members page in the console. **Done 2026-11-23.**
- [x] **E1.4** Live: migrated and deployed; a second organisation is refused live. **Done 2026-11-23.**

**E2 Document permissions** — a reader never receives a passage they cannot open.
- [x] **E2.1** Allowed groups on every passage; filter inside both searches. **Done 2026-11-23** (not live until T26).
- [x] **E2.2** Cache, source listings and citations respect it. **Done 2026-11-23** (not live until T26).
- [x] **E2.3** Delete a document, and its cached answers with it. **Done 2026-11-23** (not live until T26).
- [ ] **E2.4** Adversarial suite (cached and reworded questions) passes live.
- [ ] **E2.5** Evidence-based reuse (old 9.4), permission-aware, behind a switch.

**E3 First connector** (choice settled by the owner's five conversations, O8).
- [ ] **E3.1** Google Drive folder synced into a workspace.
- [ ] **E3.2** Edits, deletions and Drive sharing followed.
- [ ] **E3.3** A deleted or unshared page stops being answered within 15 min, measured.

**E4 Governance**
- [ ] **E4.1** Append-only audit record with a retention setting.
- [ ] **E4.2** Question text out of general logs.
- [ ] **E4.3** Budget per workspace with a hard cap.
- [ ] **E4.4** Admin console: sources, members, usage, spend.

**E5 Scale and reliability**
- [ ] **E5.1** Keyword search inside the database; servers hold no state.
- [ ] **E5.2** Shared answer cache across servers.
- [ ] **E5.3** Uptime and speed targets; 50 questions a second load test (≈₹50–150, priced first).
- [ ] **E5.4** Backup with a timed restore drill; request tracing.

**E6 Quality loop**
- [ ] **E6.1** Thumbs up/down and "wrong source" in the console.
- [ ] **E6.2** Unanswered-questions report for knowledge owners.
- [ ] **E6.3** 40-question set, release blocked on a drop, answers correct ≥0.85 (≈₹30).

### The stop rule

**Nothing new is built** — no features, no polish, no research — unless
(a) it is a task in section 4, or (b) a real outside user hit it, or
(c) the owner opens a new milestone in this file. Good ideas go to the
parking lot in section 7 as one line, and the session moves on.

## 4. Task queue — do these in order

`Who`: **C** = Claude does it · **You** = only the owner can.

| ID | Task | Who | Cost | Done when | Ticks |
|---|---|---|---|---|---|
| ~~T1~~ | ~~Write the 90-second recording script and shot list~~ | C | ₹0 | **done 2026-11-12** — `docs/demo-script.md` | — |
| T2 | Record the screen following the script; share the file | You | ₹0.20 | video file exists | — |
| T3 | Put the video on README + landing, plus one still from it as the README screenshot; rebuild; deploy | C + You | ₹0 | visible on the live site | 6.1, 6.2 |
| ~~T4~~ | ~~Rewrite the README first screen; add the numbers check to the tests~~ | C | ₹0 | **done 2026-11-13** — 42 quotes checked; the screenshot comes with T3 | — |
| ~~T15~~ | ~~Let visitors ask the demo sheet without a key, ₹10/day cap~~ | C + You | ≤₹10/day | **done 2026-11-14** — live; a keyless question answered with 4 citations, faithfulness 1.0, ₹0.20 | — |
| T5 | Send the invitation in section 5 to five people — **no key needed** (T15 is live) | You | ₹0 | five sent | — |
| T6 | Read the logs 3 days after T5; write the findings | C | ₹0 | findings in section 8 | 6.3 |
| T7 | Fix the top finding; deploy | C + You | ₹0 | live | 6.4 |
| ~~T8~~ | ~~Write the interview sheet~~ | C | ₹0 | **done 2026-11-13** — `learning/interview-sheet.md`, its numbers checked by tests | 7.1 |
| ~~T9~~ | ~~Write the case study; publish on the site~~ | C + You | ₹0 | **done 2026-11-13** — `docs/case-study.md`, linked from the landing page, live since 2026-11-13 | 7.2 |
| ~~T10~~ | ~~Write new resume bullets as text~~ | C | ₹0 | **done 2026-11-13** — `docs/resume-bullets.md`, its numbers checked by tests | 7.3 |
| ~~T11~~ | ~~Check what the site does when Gemini refuses for lack of credit; make it say "demo paused"~~ | C | ₹0 | **done 2026-11-13** — tested with a built refusal; live since 2026-11-13 | 8.1 (half) |
| T12 | Check the prepaid balance; decide auto-reload | You | your call | decision written in section 6 — **auto-reload decided 2026-11-18 (on)**; left: look at the balance once | 8.1 |
| ~~T13~~ | ~~Build the weekly health check~~ | C | <₹1/month | **done 2026-11-14** — every Monday 09:00 India, ≈₹0.87/month; the test alert reached the owner's inbox | 8.2 |
| T14 | Close the loose ends in 8.3 | C + You | ₹0 | all four struck through — three struck (O4 on 2026-11-19); left: "maintenance", last, once everything else is ticked | 8.3 |

| ~~T16~~ | ~~E1 design: model, sign-in, enforcement points, migration~~ | C | ₹0 | **done 2026-11-20** — `docs/e1-identity.md` | — |
| ~~T17~~ | ~~Build E1.1: tenancy store, principal on every request, migration~~ | C | ₹0 | **done 2026-11-21** — gate green; nothing enforced yet, so every key behaves as before | E1.1 |
| ~~T18~~ | ~~Build E1.2: route policy table, checks everywhere, isolation suite~~ | C | ₹0 | **done 2026-11-21** — isolation suite green on the laptop; CI runs it on push. Not live until T21 | E1.2 |
| ~~T19~~ | ~~Create the Google sign-in client id (O7)~~ | You | ₹0 | **done 2026-11-23** — id in the laptop `.env`; app in Testing (owner is a test user). Not in Secret Manager: the id is public, it goes in as a plain setting at T21 | — |
| ~~T20~~ | ~~Build E1.3: Google sign-in, invitations, members page~~ | C | ₹0 | **done 2026-11-23** — 56 sign-in tests green; console checked in a headless browser (light, dark, phone); the owner signed in with Google on the laptop and opened Members. Not live until T21 | E1.3 |
| ~~T21~~ | ~~Run the migration; deploy; live check with a second organisation~~ | C + You | ≈₹5/month | **done 2026-11-23** — migration wrote the public organisation, sheets default and duckdb, 5 keys; deployed with sign-in on; the owner, signed in to a second organisation "Live check", got "not found" on the public organisation's `default` sheet and an empty sheet list; a keyless visitor still got a cited demo answer. The new secret is the project's 8th active secret version, past the 6 free | E1.4 |

| ~~T22~~ | ~~E2 design: access lists, where they are enforced, cache, removal, migration~~ | C | ₹0 | **done 2026-11-23** — `docs/e2-permissions.md`; two choices wait on the owner (D9) | — |
| ~~T23~~ | ~~Build E2.1: access lists on passages, groups, filter in both searches, migration~~ | C | ₹0 | **done 2026-11-23** — 1296 tests green; a reader outside a group gets nothing from a group-only passage by either search, streamed or not; the deploy refuses until `scripts/migrate_acl.py --apply` has run. Not live until T26 | E2.1 |
| ~~T24~~ | ~~Build E2.2: cache key, source list, citations respect access~~ | C | ₹0 | **done 2026-11-23** — 1307 tests green; someone allowed less never gets an answer built for someone allowed more (typed, streamed, reworded, stale index, pre-E2 entry); same access still shares; the source list hides titles and counts; each protection was removed once to check its test fails. Not live until T26 | E2.2 |
| ~~T25~~ | ~~Build E2.3: change access, remove a document; decide one server or shared cache (priced first)~~ | C | ₹0 | **done 2026-11-23** — 1372 tests green, 8 of them against a real in-memory Qdrant; a removed or narrowed document stops being answered on every server through a per-sheet version (₹0, one Firestore read per question; no Redis, still two servers). Not live until T26 | E2.3 |
| ~~T28~~ | ~~Console: groups on the Members page; "who can read" and "remove" on each document in the sources pane~~ | C | ₹0 | **done 2026-11-24** — checked in a browser against a mocked server in light, dark and phone width; 1395 tests green. Phones have no source list (DESIGN §5), so the per-source control is tablet and desktop only. Not live until T26 | — |
| T26 | E2.4: adversarial suite in CI, migration run, deploy, live run with two test accounts | C + You | a few paise | zero leaks live | E2.4 |
| T27 | E2.5: evidence-based reuse behind a switch | C | ₹0 | paraphrase hit rate measured; T26's suite still passes | E2.5 |

T26 is next (C + You, a few paise): merge, run the acl migration, deploy, then the live test with two accounts. The owner holds the friend invitation (O1) until Claude signals, after T26 is live. Left from T21 for the owner: Google's Branding page (homepage and `/privacy`) and Publish app (O7). Older Claude tasks still wait on the owner: T3 on the video (T2), T6 on the invitations (T5) plus three days, T14 on everything else being ticked. T12 is yours too.

## 5. The owner's list — things only you can do

- [ ] **O1 — Send the invitation (T5).** Five people, any mix of engineers
      and friends. **Ready now:** no key needed, the demo sheet answers
      anyone (₹10/day cap; about 3 questions a minute per visitor). Send by
      WhatsApp, LinkedIn or email, or post once on LinkedIn. Paste this:

      > Hey! I built a tool called Atlas that answers questions about a
      > technical manual (DuckDB, a database tool). It shows exactly which
      > page each sentence came from, and how much to trust the answer.
      > Could you try it for 2 minutes? No sign-up needed.
      >
      > 1. Open https://atlas.hulage.in/app
      > 2. Press the suggested question on the screen.
      > 3. Then try one or two of these, or ask your own:
      >    • How do I read a CSV file in DuckDB?
      >    • Does DuckDB support CREATE TRIGGER?
      >    • Can a DuckDB schema contain another schema?
      >    • How do you list the triggers in a DuckDB database?
      >    • How do I send every DuckDB change into Kafka? (a trick question:
      >      the manual doesn't cover it, so it should say so instead of
      >      making something up)
      > 4. Click the little numbers in the answer to see the page it came from.
      >
      > Then just tell me the first thing that confused you. That's the only
      > feedback I need 🙂

      Afterwards: forward any replies to Claude and say the date you sent it.

- [ ] **O2 — Record the 90-second video (T2).** The script is ready: `docs/demo-script.md`.
- [ ] **O3 — Look at the Gemini prepaid balance once (T12).** Auto-reload is
      decided: on (AutoPay). Planned for the weekend of 21–22 Nov.
- [x] **O4 — Revoke the old Gemini key.** **Done 2026-11-19**; the live site
      answered a real question afterwards.
- [x] **O5 — Put the new Gemini key into sextant.** **Done by the owner
      before 2026-11-19.**
- [ ] **O6 — Five recovery-code files in Downloads:** save to a password
      manager, then delete them.
- [x] **O7 — Google sign-in client id (T19), ₹0.** **Done 2026-11-23.** The
      client secret was shown once and then deleted and replaced; Atlas never
      uses it, so it is stored nowhere. Left for T21: add the homepage and
      privacy page on Google's Branding page, then press Publish app.
- [ ] **O8 — Five short conversations before E3** with people who run
      internal tools: where docs live, how people find answers, what would
      stop their security team, what they would pay per user per month.

## 6. Decisions waiting on you

| # | Decision | Claude's recommendation |
|---|---|---|
| D1 | ~~Approve this plan, or change M6–M8~~ | **Approved as is, 2026-11-12** |
| D2 | ~~Gemini auto-reload: on or off~~ | **Decided 2026-11-18: on** (AutoPay). Claude had recommended off |
| D6 | **What comes after M8?** Options: **(a)** two small first-visit fixes, ₹0: the daily-cap message says "demo paused until tomorrow" instead of "wait a minute", and the ~15 s wait after idle is measured to find where it goes (every page already wakes the same server, so the cause is unknown) · **(b)** M9: raise "answers correct" from 0.77 to 0.85 on a 40-question test set, about ₹30 of test runs · **(c)** a second public manual so Atlas is not DuckDB-only, a few ₹, priced before starting · **(d)** visitors try one small document of their own, capped — biggest, riskiest | **(a) now, before the weekend visits; then (b) after T6**, unless the findings point elsewhere. 0.77 is the number an interviewer will push on |
| ~~D7~~ **Decided 2026-11-19: yes, M9 opened** | **Open M9 "Ready for a 10,000-person company"?** Reuse the evidence an answer needs instead of the exact question text, then per-document permissions. Steps S1–S5 and costs in `docs/company-scale.md` | **Yes, measure first:** S1–S2 (≈ ₹3) decide whether S3 is worth building; S4 (permissions) is the blocker for any real company either way. S0 (clean pasted text) is a real-user fix and needs no decision |
| ~~D8~~ **Decided 2026-11-20: yes, approved** | **Adopt the enterprise phases E1–E6** in `docs/enterprise-product.md` as the plan after M9's first three boxes? Order: identity and organisations → document permissions → Google Drive connector → audit and team budgets → scale and reliability → quality loop. Evidence reuse (9.4) moves behind permissions. Each phase becomes a milestone with its exit test; the footer's denominator grows when approved | **Yes, and start E1 now.** Every later piece (permissions, budgets, audit) needs "who is asking", which does not exist today. Do the five short conversations in section 6 of that note before E3 picks a connector |
| ~~D9~~ **Decided 2026-11-23: yes to both** | **E2's two choices** (`docs/e2-permissions.md` §2): (a) organisation admins read only the documents their groups allow, no bypass; (b) a new upload is open to everyone on its sheet unless the editor narrows it | **Yes to both.** (a) matches Google Drive and what security teams ask for; (b) keeps today's behaviour, so nothing breaks for current users |
| D3 | Old FastAPI documents: keep or delete | **Decided 2026-11-13: keep** |
| D4 | "Depth setting ignored on a repeat question" | **Decided 2026-11-13: accepted** — known, never hit a real user |
| ~~D5~~ **Decided 2026-11-13: yes, ₹10/day cap; task T15** | **Let visitors ask the demo documents without a key?** Today nobody can try Atlas unless you hand them a key. | **Yes, with a hard limit:** no key needed for the demo documents only, capped at about **₹10 a day** in total and a few questions a minute per visitor; uploads and everything else stay key-only. Worst case ≈ ₹300 a month if someone abuses it every day; the cap can be lowered or switched off in one setting. If no: every invitation and the README must say "ask me for a key". This would become a new task before T5. |

Write the answer in the table when decided. Claude never decides these.

## 7. Parking lot — not scheduled, one line each

- A description for every uploaded set of documents, learned automatically
- Better handling of PDFs with tables
- Per-user usage page in the console
- Test-set upload for a visitor's own documents
- Moving the search database nearer the server (about 25% faster)
- Keyboard shortcut help in the console · `make demo`
- Research ideas: see `planning/BACKLOG.md` under *Ideas*
- The daily spend cap's refusal reads "rate limited, wait a minute" in the console; it lasts until midnight UTC
- A signed-in person from another organisation cannot open the public demo sheet (their list is their own organisation's); visitors without an account can
- Sign-in attempts (`/auth/google`) have no per-visitor limit; a refusal costs ≈₹0, so low priority

## 8. Log — one line per session, newest first

- 2026-11-24 — T28 done: Members page gains groups (add, delete, who is in each); each source in the corpus pane gains "who can read" and "remove" for editors; a read-only route shows a source's current readers and the organisation's groups to editors who are not admins. Checked light, dark, phone width. Not live. ₹0.
- 2026-11-23 — T25 done: change a document's readers or remove it (editor only; hidden documents answer "not found"); a per-sheet version makes every server drop old answers and rebuild its keyword copy; re-uploads keep a document's access. Shared cache not needed. T28 (console controls) added before T26. Not live. ₹0.
- 2026-11-23 — T24 done: cached answers keyed by the access the sheet uses and re-checked against each passage's list on every hit; source list filtered without revealing hidden counts. Owner will send the friend invitation only after Claude's signal (after T26). Not live. ₹0.
- 2026-11-23 — T23 done: access lists on every passage (`all` by default), groups on the organisation page's API, both searches filtered by the caller's tokens set per request, `scripts/migrate_acl.py` (₹0, owner runs it in T26), deploy guard. Not live. ₹0.
- 2026-11-23 — T22 done: E2 design written (`docs/e2-permissions.md`): access lists on passages, filtered inside both searches, cache keyed by the caller's access, document removal, ₹0 migration; tasks T23–T27 added; D9 opened. ₹0.
- 2026-11-23 — T21 done, E1 complete: session secret in Secret Manager, migration applied to Firestore, sign-in live on atlas.hulage.in, second organisation refused live, demo still answers visitors. A signed-in person in another organisation does not see the public demo sheet (by design: their list is their organisation's). ≈₹5/month for the secret.
- 2026-11-23 — T20 done (owner signed in with Google on the laptop): Google sign-in with an 8-hour signed cookie, invitations, domain joining, members page (people, invitations, sheets, service accounts), break-glass org creation, privacy page. Roles read on every request, so removal applies next request. Not live. ₹0.
- 2026-11-23 — T19 done by the owner: Google sign-in client created in atlas-rag-rush, id in the laptop `.env`; leaked client secret deleted and replaced (unused by Atlas); app stays in Testing until a privacy page exists. ₹0.
- 2026-11-21 — T18 done: every route checks who is asking against a policy table; set lists private; answers cached per workspace; a failed access check refuses; isolation suite (two organisations, every route, both ways) green. Unmigrated keys keep the public sets only. Not live. ₹0.
- 2026-11-21 — T17 done: organisations, workspaces, users, roles and service accounts stored (laptop and live stores); every request carries who is asking; re-runnable migration with a dry run; not live, nothing enforced yet. ₹0.
- 2026-11-20 — D8 approved: E1–E6 added as milestones (plan 36 boxes, project 56), 9.4/9.5 folded into E2; E1 design written (T16). ₹0.
- 2026-11-20 — Owner reframed Atlas as an enterprise product; gap review against the code (4 blockers: identity, tenancy, document permissions, connector + delete) and phases E1–E6 written; D8 added. ₹0.

- 2026-11-19 — D7 yes, M9 opened (plan now 15 boxes, project 35): pasted-text fix and passage logging built, not live; reuse measured, 69% of rewordings / 1 of 120 wrong; ≈₹0.01.
- 2026-11-19 — First real visit: owner and one friend asked 12 questions (the invitation's five plus the suggested one); findings below; owner set the company-scale lens, design note written, D7 added. ₹1.25 of visitor questions, ₹0 for reading them.
- 2026-11-19 — Owner revoked the old Gemini key; live check answered a real question afterwards ($0.0021); laptop key still works. ₹0.18.
- 2026-11-18 — Invitation not sent yet, friends will try 21–22 Nov; D2 decided (AutoPay on); O4 waits on another project; next-milestone options written as D6. ₹0.
- 2026-11-15 — Invitation rewritten for non-engineers: five example questions, including one trick question. ₹0.
- 2026-11-15 — Owner list brought up to date: invitations need no key, video script ready; nothing else unblocked. ₹0.
- 2026-11-14 — T13 done: second test alert emailed the owner; T14 two of four struck (D3, D4); every Claude task now waits on the owner. ₹0.
- 2026-11-14 — T13 test alert opened an issue but no email (owner not watching the repo); alerts now assign and mention the owner. ₹0.
- 2026-11-14 — T13 built: Monday check of pages, health and one real cited question; opens an issue only on failure; test alert waits on merge. ₹0.
- 2026-11-14 — T15 deployed and checked live: keyless DuckDB question answered, cited, faithful; other sheets and uploads still refused. ₹0.20.
- 2026-11-14 — T15 finished in code: console wording, visitor guide and README, deploy settings (₹10/day, 3 a minute). ₹0.
- 2026-11-13 — D3 keep, D4 accept, D5 yes, T13 approved; T15 server half built and tested (off until deploy settings added). ₹0.
- 2026-11-13 — T11 deployed and checked live; T9 done: case study, its numbers checked by tests, linked from the landing page. ₹0.
- 2026-11-13 — T11 done: no credit → "Demo paused" instead of the generic failure, no retries or fallback; needs a deploy to go live. ₹0.
- 2026-11-13 — T10 done: resume bullets (four, two swap-ins, one-liner) with their numbers added to the drift test. ₹0.
- 2026-11-13 — T8 done: interview sheet, 12 questions with answers and numbers; its headline numbers added to the drift test. ₹0.
- 2026-11-13 — T4 done: README first screen rewritten; README, landing, pitch and tour numbers now checked by tests; pitch's stale FastAPI figures replaced. ₹0.
- 2026-11-12 — T1 done (recording script). Found the locked door: no visitor can ask without a key → decision D5. ₹0.
- 2026-11-12 — Plan redesigned and approved; old planning files frozen as history; no-progress-lines rule added. ₹0.
- 2026-11-11 — "Asked already" fix merged and deployed (revision 00043). ₹0.

Findings from T6 go here, five lines at most.

- 2026-11-19 (early read: one friend + owner, about 20:20 India): 12 questions, **12 answered, 0 errors**; 9 fresh answers took 8–11 s, every one fully backed by the manual; 3 repeats came back instantly.
- The Kafka trick question was declined in about 1 s both times, even when pasted with its hint text.
- No wait on first open: the server was already awake. The ~10 s per answer is the answer itself, not a wake-up.
- Small: text copied from WhatsApp carries an invisible character, so two repeats were answered and paid again (≈₹0.35); the tab icon is missing on every page.
- Not seen in logs: the answer wording, and what confused anyone — that needs the friend's own words.

---

## 9. Rules for Claude — follow exactly

### At the start of every session

1. Read **this file only**. Do not read `STATUS.md`, `DECISIONS.md` or
   `BACKLOG.md` whole — they are history, 400 KB together. Search them with
   `grep` when one specific fact is needed.
2. Find the first task in section 4 that is not done and not waiting on the
   owner. That is the work. If every remaining task waits on the owner, say
   so in one reply and stop.
3. If the owner asks for something that is not in section 4, do it only if
   it passes the stop rule. Otherwise answer in two lines: what it is, and
   that it has gone to the parking lot.

### While working

- One task at a time, finished before the next starts.
- Standing rules still apply and are not repeated here: `CLAUDE.md` in this
  folder (quality checks, design file, rebuilt console), plus the owner's
  global rules (one command per message, the owner runs every push, merge
  and deploy, ask before any spend with the ₹ amount, secrets never in chat
  or in tracked files, work on a branch, no Claude credit lines, nothing
  left running).
- Never touch another project from an Atlas session.
- **Think at company scale** (owner, 2026-11-19): judge every design as if
  Atlas served a 10,000-person company — permissions, freshness, privacy,
  shared state, cost per team, ingestion volume. Measure before building.
  Reference: `docs/company-scale.md`.
- **Work as a staff engineer on a product** (owner, 2026-11-20): engineering,
  system design, product owner and analyst together. Ask who uses it, who
  buys it, what blocks a pilot, and what proves it, before what to code.
  Reference: `docs/enterprise-product.md`.

### Writing limits — these stop the files growing again

| Thing | Limit |
|---|---|
| Log entry in section 8 | 1 line |
| Commit message | title + 5 lines at most |
| Pull request description | 10 lines at most |
| New entry in `DECISIONS.md` | only when a real choice was made; 10 lines at most |
| `STATUS.md`, `BACKLOG.md` | **frozen — never add to them** |
| Code comments | say what the code cannot; 3 lines at most |

When a task finishes: tick its box in section 3, strike the row in
section 4, add the log line, update section 2 if a fact changed. Nothing
else is written anywhere.

### The reply — every finished piece of work, exactly this shape

```
Completed **<task ID and plain name>** and pushed <where> / nothing pushed.

- <result, key fact in bold>
- <result>
- <result>            (3 to 5 bullets, one line each)

<One sentence: what this does not prove or finish.>

**Next:** <task ID and name> — <what it waits on, if anything>.

**<Nothing needed from you. / The one thing needed from you.>**

This task: <N>% · Plan: <ticked> of 36 · Whole project: <20 + ticked> of 56
```

- Plain words for a non-engineer. No file paths, commit ids, branch names,
  test counts, tool names or command output unless the owner asks.
- The whole reply fits on one screen.
- **Nothing is written between steps — no progress lines at all**, not
  even when a reminder says the owner has not heard anything for a while.
  No "reading the files…", no "now writing…", no "sending it to you now".
  Work silently; the one final reply is the only text in a turn. The only
  exception is an emergency (money being charged, something broken).
- No file captions and no unasked file sends. Link the file in the reply.
- When the owner must run something: one command, alone, in the format the
  global rules give, then stop and wait for "done".
- If a session did work outside the plan, the reply says so in its first
  line.

### At the end of every session

- Nothing left running on this machine or in the cloud.
- This file is true: boxes, task rows, log, the facts in section 2.
- The reply ends with the owner's open items from section 5 **only if one
  of them now blocks the next task** — name that one item, not the list.

## 10. Where the old material lives

| File | What it is now |
|---|---|
| `planning/ROADMAP.md` | Half A — the five finished milestones and their 20 criteria |
| `planning/STATUS.md` | Session-by-session history up to 2026-11-05. Frozen. |
| `planning/DECISIONS.md` | Why each technical choice was made. Add only real decisions. |
| `planning/BACKLOG.md` | Old bugs, debts and ideas. Frozen; the parking lot above replaces it. |
| `planning/BUDGET.md` | The speed and cost ceilings. Still in force. |
| `planning/PITCH.md` | The spoken explanation. Source material for T8 and T9. |

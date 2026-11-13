# Atlas — the plan

**Read this file first, every session. It is the only planning file that is
current.** Last updated 2026-11-12.

Status of this plan: **APPROVED by the owner, 2026-11-12.** Work proceeds
through section 4 in order.

---

## 1. What Atlas is for

Atlas answers questions about a set of documents, shows the exact passages
each claim came from, and says how far to trust its own answer. It is the
owner's portfolio centrepiece for a senior software-engineering job search.

So the goal has two halves:

| Half | Meaning | State |
|---|---|---|
| **A. It works, and that is measured** | built, tested, live, costs known | **Done** — 20 of 20 |
| **B. It is seen and understood** | strangers get it in two minutes; the owner can present it; it stays alive without attention | **Not started** — 0 of 10 |

Half A was the old roadmap. Half B is this plan.

## 2. Where it stands (checked 2026-11-12)

| | |
|---|---|
| Live site | https://atlas.hulage.in — console at `/app` |
| Live version | revision `atlas-api-00044-k8c`, deployed 2026-11-13, carries every merged change up to T11 |
| Demo documents | DuckDB 2.0 manual — 226 pages, 3,975 passages |
| Measured quality | finds the right page **16 of 16**; answers stick to the pages **0.99**; answers correct **0.77** (16 test questions, 2026-11-03) |
| Cost | **₹0** while idle · about **₹0.20** per question · ₹6 per full test run |
| Speed | about 7 s typical, 14 s slow case; first visit after idle waits ~15 s |
| Code health | 892 automated tests, all passing on GitHub |
| Real use | **No question of any kind has reached the live site since 3 Nov.** The two invited friends sent 6 questions that day and never returned. |
| Money runway | Gemini prepaid balance was **₹161.51** when last seen (~4 Nov), auto-reload **off**. At ₹0 the site stops answering. |
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
- [ ] **8.2** A weekly automatic check, costing under ₹1 a month, that
      contacts the owner only when something is wrong.
- [ ] **8.3** Loose ends closed: old Gemini key revoked · old FastAPI
      documents kept or deleted · the "depth setting ignored on a repeat
      question" defect fixed or accepted · this file marked "maintenance".

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
| T5 | Send the invitation in section 5 to five people — **each needs their own key unless D5 says yes** | You | ₹0 | five sent | — |
| T6 | Read the logs 3 days after T5; write the findings | C | ₹0 | findings in section 8 | 6.3 |
| T7 | Fix the top finding; deploy | C + You | ₹0 | live | 6.4 |
| ~~T8~~ | ~~Write the interview sheet~~ | C | ₹0 | **done 2026-11-13** — `learning/interview-sheet.md`, its numbers checked by tests | 7.1 |
| ~~T9~~ | ~~Write the case study; publish on the site~~ | C + You | ₹0 | **done 2026-11-13** — `docs/case-study.md`, linked from the landing page after your next deploy | 7.2 |
| ~~T10~~ | ~~Write new resume bullets as text~~ | C | ₹0 | **done 2026-11-13** — `docs/resume-bullets.md`, its numbers checked by tests | 7.3 |
| ~~T11~~ | ~~Check what the site does when Gemini refuses for lack of credit; make it say "demo paused"~~ | C | ₹0 | **done 2026-11-13** — tested with a built refusal; live since 2026-11-13 | 8.1 (half) |
| T12 | Check the prepaid balance; decide auto-reload | You | your call | decision written in section 6 | 8.1 |
| T13 | Build the weekly health check | C | <₹1/month | one test alert received | 8.2 |
| T14 | Close the loose ends in 8.3 | C + You | ₹0 | all four struck through | 8.3 |

T14 (the defect part) is next for Claude; T13 needs a yes on its cost first. T6 cannot start until three days after T5.

## 5. The owner's list — things only you can do

- [ ] **O1 — Send the invitation (T5).** Five people, any mix of engineers
      and friends. **Wait for decision D5 first:** as things stand each
      person also needs a key from you and the line "open Settings, paste
      this key", or the suggested question will refuse them. Paste this:

      > I built a tool that answers questions about a technical manual and
      > shows you exactly where each sentence came from, plus how much to
      > trust it. Two minutes: open https://atlas.hulage.in/app, press the
      > suggested question, then ask one of your own about DuckDB. Tell me
      > the first thing that confused you — that is the only feedback I need.

- [ ] **O2 — Record the 90-second video (T2)** once Claude gives the script.
- [ ] **O3 — Check the Gemini prepaid balance and decide auto-reload (T12).**
- [ ] **O4 — Revoke the old Gemini key.** Already proven safe to revoke.
- [ ] **O5 — Put the new Gemini key into sextant** (separate project,
      separate session).
- [ ] **O6 — Five recovery-code files in Downloads:** save to a password
      manager, then delete them.

## 6. Decisions waiting on you

| # | Decision | Claude's recommendation |
|---|---|---|
| D1 | ~~Approve this plan, or change M6–M8~~ | **Approved as is, 2026-11-12** |
| D2 | Gemini auto-reload: on or off | Off, with a small manual top-up, plus the "demo paused" message (T11) |
| D3 | Old FastAPI documents: keep or delete | Keep — deleting saves nothing and re-adding costs ₹6 |
| D4 | "Depth setting ignored on a repeat question" | Accept and note it; it has never affected a real user |
| **D5** | **Let visitors ask the demo documents without a key?** Today nobody can try Atlas unless you hand them a key. | **Yes, with a hard limit:** no key needed for the demo documents only, capped at about **₹10 a day** in total and a few questions a minute per visitor; uploads and everything else stay key-only. Worst case ≈ ₹300 a month if someone abuses it every day; the cap can be lowered or switched off in one setting. If no: every invitation and the README must say "ask me for a key". This would become a new task before T5. |

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

## 8. Log — one line per session, newest first

- 2026-11-13 — T11 deployed and checked live; T9 done: case study, its numbers checked by tests, linked from the landing page. ₹0.
- 2026-11-13 — T11 done: no credit → "Demo paused" instead of the generic failure, no retries or fallback; needs a deploy to go live. ₹0.
- 2026-11-13 — T10 done: resume bullets (four, two swap-ins, one-liner) with their numbers added to the drift test. ₹0.
- 2026-11-13 — T8 done: interview sheet, 12 questions with answers and numbers; its headline numbers added to the drift test. ₹0.
- 2026-11-13 — T4 done: README first screen rewritten; README, landing, pitch and tour numbers now checked by tests; pitch's stale FastAPI figures replaced. ₹0.
- 2026-11-12 — T1 done (recording script). Found the locked door: no visitor can ask without a key → decision D5. ₹0.
- 2026-11-12 — Plan redesigned and approved; old planning files frozen as history; no-progress-lines rule added. ₹0.
- 2026-11-11 — "Asked already" fix merged and deployed (revision 00043). ₹0.

Findings from T6 go here, five lines at most.

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

This task: <N>% · Plan: <ticked> of 10 · Whole project: <20 + ticked> of 30
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

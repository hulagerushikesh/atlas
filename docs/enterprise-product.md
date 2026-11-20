# Atlas as an enterprise product

Written 2026-11-20, after the owner's correction: Atlas has been treated as a
solo portfolio project that builds the basics well. The owner wants it built
and judged as an **enterprise-grade product** a company would buy. The
portfolio value comes from that, not the other way round.

This note is the product owner's and staff engineer's view: who it is for,
what a company would demand, where today's code stands against each demand
(checked in the code, not remembered), and the order in which to close the
gaps. `docs/company-scale.md` stays as the deep dive on cost and caching.

---

## 1. The product in one paragraph

Employees at a company with thousands of people waste hours finding answers
that already exist somewhere in its documents: wikis, drives, runbooks,
policies, tickets. Atlas answers in plain language, cites the exact passage
behind every sentence, says how far to trust the answer, and **never shows
anyone a passage they are not allowed to open**. Admins see what is being
asked, what could not be answered, and what it costs, per team.

What makes it different from "chat with your PDFs": the evidence and the
trust verdict (built and measured), permissions that match the source
systems (not built), and a "questions we could not answer" report that tells
knowledge owners which documents are missing (not built).

## 2. Who uses it, who buys it

| Persona | What they need | What they would reject Atlas for |
|---|---|---|
| **Employee (asker)** | A right answer in seconds, with a link to the source | One confident wrong answer; seeing it can't reach the doc they know exists |
| **Knowledge owner** (team lead, docs owner) | Their docs answer correctly; to know what people ask and what fails | Stale answers after they edit a page |
| **Workspace admin** | Connect sources, manage who sees what, budgets per team | Managing users by hand; pasting keys |
| **IT / security (the gate)** | SSO, permissions, audit trail, data stays in region, no training on their data | Any route by which a person sees a document they cannot open |
| **Buyer** (Head of Platform / Eng Productivity) | Measured time saved; predictable cost | No usage numbers; cost that grows without a cap |

The **first market** to aim at: an engineering organisation of 200 to 2,000
people asking about internal technical docs. That matches what Atlas is
measured on today (a technical manual) and the owner's own network.

**Success measures** a buyer would ask for: share of questions answered with
a citation; share marked wrong by users; median time to answer; cost per
answer and per team per month; questions per active user per week (does it
stick?); unanswered-question count falling as owners fill gaps.

## 3. Where today's code stands (checked 2026-11-20)

Severity: **Blocker** = no company would pilot without it · **High** = needed
before more than one team · **Later** = needed to sell widely.

| Area | A company expects | Atlas today | Severity |
|---|---|---|---|
| **Identity** | Sign in with the company's identity provider (OIDC/SAML); users and groups synced (SCIM) | Shared API keys pasted into Settings; key admin is one shared secret header; no users, no sign-in | **Blocker** |
| **Tenancy** | Organisation → workspaces → users; one org can never see another | A "namespace" is one Qdrant collection; any valid key can query any namespace; the namespace list is public | **Blocker** |
| **Document permissions** | A reader sees only passages from documents they can open in the source system | None. Every passage is visible to every caller of its namespace, including through cached answers | **Blocker** |
| **Sources** | Connectors to Drive / Confluence / SharePoint / Notion / Git, kept in sync, deletions honoured | Manual upload of PDF, HTML, Markdown, text; no sync; **no way to delete a document** | **Blocker** (one connector + delete) |
| **Freshness** | An edited or deleted page stops being answered within minutes | Only by re-uploading; answers cached up to 1 h; the two servers can disagree | High |
| **Audit & privacy** | Append-only record of who asked what and what was shown; retention policy; question text not in general logs | Question text sits in application logs with no retention policy; no audit record | High |
| **Cost governance** | Budget and usage per team; chargeback; hard caps | One global ₹10/day cap for keyless visitors; per-key request rate; usage counters per key | High |
| **Admin experience** | A console page to manage sources, members, roles, budgets, and to read usage and gaps | None; admin is API calls with a secret header | High |
| **Scale** | Thousands of users, millions of passages, stateless servers | Keyword index held in each server's memory and rebuilt from the database; answer cache per server; max 2 servers | High |
| **Reliability** | Stated uptime target, backups with a tested restore, alerting | Weekly health email; no target; no restore ever tested | High |
| **Quality loop** | Users flag wrong answers; each workspace has its own test set; a regression blocks a release | 16-question test set for one manual; answers correct **0.77**; no feedback button | High |
| **Observability** | Traces across a request; per-tenant dashboards | Request IDs in logs; Prometheus/Grafana configured locally only | Later |
| **Deployment choice** | Their own model key or model; their own cloud for some buyers | One shared model key; one region (Mumbai) | Later |
| **Compliance** | SOC 2 / ISO 27001, DPA | Out of reach for a solo owner; design so audit, encryption and retention are already there | Later |

**What is already enterprise-grade** and should be said so: cited answers
with a measured faithfulness check (0.99), finding the right page 16 of 16,
honest refusal on out-of-scope questions, cost known per answer (≈₹0.18),
streaming, 1,000+ automated tests with CI, spend caps, deterministic chunk
IDs that make re-ingest safe.

## 4. Target shape

```
Identity provider (Google Workspace first) ──► Atlas sign-in ──► principal = user + groups + org
                                                                   │
Connectors (Drive first) ──► sync worker ──► passages + ACL (allowed groups) ──► Qdrant (dense + sparse vectors, payload filter)
                                                                   │
Query: principal → filter by org/workspace/ACL at retrieval → rerank → answer → faithfulness → cache keyed by evidence + checked per passage
                                                                   │
Audit store (append-only, retention)  ·  usage per team  ·  admin console  ·  unanswered-questions report
```

Four design rules that follow from the table:

1. **Permissions are enforced at retrieval, never after.** A filter on the
   search itself, so a forbidden passage is never fetched, never reranked,
   never cached and never cited. Post-filtering an answer leaks through the
   wording.
2. **Servers hold no state that matters.** The keyword index moves into the
   database (sparse vectors) and the cache into a shared store, so any server
   answers the same.
3. **Every passage knows where it came from and who may see it.** Source
   system, source ID, version, allowed groups. Deleting or re-permissioning a
   source updates its passages and drops only the cached answers that read
   them (the evidence logging built in M9 is the first half of this).
4. **Identity before features.** Every later piece (budgets, audit, admin,
   feedback) hangs off "who is asking", which today does not exist.

## 5. The order — what to build, in phases

Each phase ends in something a person can see working, with a test that
proves its guarantee. Costs are rough and checked before starting.

| Phase | Builds | Done when (exit test) | Rough cost |
|---|---|---|---|
| **E1 Identity & tenancy** | Organisations, workspaces, users, roles (admin · editor · reader); Google sign-in for people; API keys become service accounts scoped to one org and its workspaces | Two organisations on one deployment cannot see each other's workspaces, documents, answers or usage — proved by a test suite that tries | ₹0 (Google sign-in and Firestore free tier) |
| **E2 Document permissions** | Allowed groups stored on every passage; filter at retrieval for both search methods; cache and source listings respect it; delete a document | A reader without access never receives a forbidden passage's text, title or an answer built from it — adversarial tests, including cached and reworded questions | ₹0 |
| **E3 First connector** | Google Drive: sync, edits, deletes, and Drive sharing mapped to groups; freshness target 15 minutes | A page deleted or unshared in Drive stops being answered within 15 minutes, measured | ≈₹0 (Drive API free); sync job pennies a day |
| **E4 Governance** | Audit record (append-only, retention setting); question text out of general logs; budget per workspace with a hard cap; admin console pages | An admin can answer "who saw document X last week" and "what did team Y spend" from the console | ₹0–small |
| **E5 Scale & reliability** | Keyword search inside Qdrant; shared cache; uptime and latency targets; load test; backup and a restore drill; tracing | 50 questions per second on synthetic load without errors; a restore drill completed and timed | load test ≈₹50–150, priced first |
| **E6 Quality loop** | Thumbs up/down and "wrong source"; unanswered-questions report; per-workspace test sets; release blocked on a quality drop; raise answers-correct to 0.85 | Correctness ≥0.85 on a 40-question set; the gaps report lists real unanswered questions | ≈₹30 of test runs |
| Later | Bring-your-own model key, second connector, single-tenant deploy, SSO beyond Google (SAML), SCIM | — | — |

**Where M9 goes.** Its first three boxes (pasted text, passage logging,
reuse measured) stay. **Evidence reuse (9.4) moves behind permissions
(9.5 → E2)**: at today's traffic it saves pennies, and a reuse cache built
before permissions would have to be rebuilt to respect them. Being
honest about priority is the staff-engineer call here.

## 6. What a business analyst would do before E3

The connector choice (Drive vs Confluence vs SharePoint) and the first
buyer are guesses until people who run internal tools are asked. Five short
conversations through the owner's network, four questions each: where do
your docs live; how do people find answers today; what would stop your
security team; what would you pay per user per month. ₹0, and it decides E3.

## 7. Constraints, stated

- One owner, ₹50–100 a day shared with another project. That rules out
  managed Redis, SOC 2 and paid identity products for now; every phase above
  is designed to fit free tiers.
- The owner runs every push, merge, deploy and spend; nothing here changes that.
- Nothing in this note has been validated with a buyer. The requirements
  table is what enterprise buyers commonly ask for, not what one has asked
  Atlas for. Section 6 is how that changes.

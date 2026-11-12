# Atlas

Agentic RAG platform. Python 3.11, FastAPI, Qdrant, OpenAI-compatible LLM (live runs use Gemini via `OPENAI_BASE_URL`; key shared with sextant, in `.env` only).

## Before touching any UI
Read `DESIGN.md` first. It is the visual contract — tokens, type, layout,
components, copy rules, and a do-not-ship list. Stylesheets that disagree
with it are bugs.

## Planning and learning
**Read `planning/PLAN.md` first, every session, and follow its section 9
exactly** — it holds the goal, the current state, the ordered task queue,
the owner's to-do list, the reply shape and the writing limits. It is the
only planning file that is current. Do not read `planning/STATUS.md`,
`DECISIONS.md` or `BACKLOG.md` whole: they are frozen history, about 400 KB
together — `grep` them for a specific fact. `planning/ROADMAP.md` holds the
five finished milestones. `learning/` is study material for the user — keep
it accurate when the code it references changes.

## Replies
One reply per turn, in the shape PLAN.md section 9 gives, and **no text
before it**: no progress lines between steps ("reading the files…", "now
writing…", "sending it to you now"), even when a reminder says the owner
has not heard anything for a while. No file captions; link files in the
reply instead of sending them. The owner would rather wait in silence.

## Console
`console/` is a Vite + React + Tailwind + shadcn + Motion app with two pages:
`index.html` (the console, served at `/app`) and `landing.html` (served at `/`).
`make console-build` writes both to `src/atlas/api/static/`. The built
output is committed so the Python package and Docker image need no Node.
Rebuild and commit `static/` whenever `console/src` changes — CI fails
if you forget.

## Quality gate
`make lint && make typecheck && make test` must pass before commit.
Tests mock all infrastructure; a green suite does not prove a live path
works. Validate against real API surfaces (`create_autospec`, qdrant local
mode) rather than permissive mocks.

`.github/workflows/ci.yml` runs those three targets on every push and PR, so
"the gate is green" is checkable rather than a claim about one laptop. It
also runs `cd console && npm run lint && npm run build` and fails if the
committed `src/atlas/api/static/` differs from a fresh build. The workflow
calls the make targets rather than its own copy of the commands — change the
Makefile and CI follows. Note the suite needs `OPENAI_API_KEY` set to
anything at all (`OpenAIConfig.api_key` is required), which `.env` supplies
locally and the workflow supplies as a dummy.

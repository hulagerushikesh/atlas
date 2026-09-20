# Atlas

Agentic RAG platform. Python 3.11, FastAPI, Qdrant, OpenAI-compatible LLM (live runs use Gemini via `OPENAI_BASE_URL`; key shared with sextant, in `.env` only).

## Before touching any UI
Read `DESIGN.md` first. It is the visual contract — tokens, type, layout,
components, copy rules, and a do-not-ship list. Stylesheets that disagree
with it are bugs.

## Planning and learning
`planning/STATUS.md` is where the project stands; read it at session start
and update it when a milestone moves. `planning/ROADMAP.md` holds the
milestones. `learning/` is study material for the user — keep it accurate
when the code it references changes.

## Console
`console/` is a Vite + React + Tailwind + shadcn + Motion app with two pages:
`index.html` (the console, served at `/app`) and `landing.html` (served at `/`).
`make console-build` writes both to `src/atlas/api/static/`. The built
output is committed so the Python package and Docker image need no Node.
Rebuild and commit `static/` whenever `console/src` changes.

## Quality gate
`make lint && make typecheck && make test` must pass before commit.
Tests mock all infrastructure; a green suite does not prove a live path
works. Validate against real API surfaces (`create_autospec`, qdrant local
mode) rather than permissive mocks.

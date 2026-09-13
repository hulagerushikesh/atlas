# Atlas

Agentic RAG platform. Python 3.11, FastAPI, Qdrant, OpenAI.

## Before touching any UI
Read `DESIGN.md` first. It is the visual contract — tokens, type, layout,
components, copy rules, and a do-not-ship list. Stylesheets that disagree
with it are bugs.

## Quality gate
`make lint && make typecheck && make test` must pass before commit.
Tests mock all infrastructure; a green suite does not prove a live path
works. Validate against real API surfaces (`create_autospec`, qdrant local
mode) rather than permissive mocks.

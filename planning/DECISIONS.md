# Decisions

Short log. One entry per decision that someone might later ask "why?" about.
Format: date — decision — alternatives — reason.

- **2026-07** — Fixed pipeline DAG with bounded retry loops, not a free
  ReAct agent. *Alt:* tool-calling agent. *Why:* predictable latency and
  cost; the router gives most of the adaptivity. Sextant explores the other
  shape.
- **2026-07** — RRF for fusion, k=60. *Alt:* min-max score normalisation,
  learned fusion. *Why:* no calibration, no training, robust to one bad
  retriever; the original paper's default.
- **2026-07** — Cross-encoder MiniLM-L-6 as reranker. *Alt:* bigger
  rerankers, Cohere. *Why:* CPU-friendly, ~95% of the quality, no API
  dependency.
- **2026-07** — Faithfulness failures flag, not suppress. *Alt:* refuse on
  low score. *Why:* an honest answer with a warning is more useful than a
  refusal; the caller decides.
- **2026-07** — Recursive chunker, 512/64, as default. *Alt:* semantic.
  *Why:* free, structure-aware, good on docs; semantic costs embeddings per
  document.
- **2026-08-15** — Prove the dense path against real Qdrant local mode
  rather than mocks. *Why:* mocks hid the removed `search()` API for weeks.
- **2026-09-13** — Cartographic design direction. *Alt:* dark dev-tool
  teal/violet, warm-cream serif. *Why:* both alternatives are the category
  default now; the name is Atlas; metaphor in structure and vocabulary, not
  decoration. See `DESIGN.md`.
- **2026-09-13** — Console as a React app (Vite + Tailwind v4 + shadcn +
  Motion), built output committed to `static/`. *Alt:* static HTML/CSS.
  *Why:* static version rejected as amateur; real component primitives and
  motion needed; committing the build keeps the Python image Node-free.
- **2026-09-13** — Hero entrance via CSS keyframes, not Motion. *Why:*
  rAF-driven entrances stall under load; CSS runs off the main thread.
- **2026-09-14** — `learning/` and `planning/` folders; `SUMMARY.md` archived,
  `DEPLOY.md` → `docs/deploy.md`. *Why:* one place for progress that survives
  context loss; one place for study material separate from reference docs.
- **2026-09-20** — Gemini via OpenAI-compatible endpoint instead of OpenAI.
  *Alt:* buy OpenAI credits; write a native Gemini provider. *Why:* credits
  already exist on the AI Studio account shared with sextant; one config knob
  (`OPENAI_BASE_URL`) keeps the OpenAI SDK, retry ladder and tests unchanged.
  Models: `gemini-3.1-flash-lite` primary (same as sextant), `gemini-3.5-flash-lite`
  fallback, `gemini-embedding-001` at 1536-d. Verified: embeddings, JSON mode,
  streaming. Gemini omits `usage` on embeddings → embedder tolerates `None`.

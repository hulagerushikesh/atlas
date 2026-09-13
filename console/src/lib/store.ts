import { create } from "zustand"
import {
  ApiError, getHealth, getSheets, getSources, postQuery, streamQuery, store as ls,
  type Citation, type Evidence, type Health, type QueryResponse, type SourceInfo, type TokenUsage,
} from "./api"

/* ── Stages ────────────────────────────────────────────────────────────── */

export type StageName = "routing" | "decompose" | "retrieval" | "grading" | "generation" | "faithfulness"
export type StageStatus = "pending" | "running" | "done" | "skipped" | "failed"
export interface Stage { status: StageStatus; ms?: number; detail?: string }

/** Order, colour family (blue = retrieval, ochre = model) and label. */
export const STAGES: { name: StageName; kind: "ret" | "llm"; label: string }[] = [
  { name: "routing", kind: "llm", label: "route" },
  { name: "decompose", kind: "llm", label: "decompose" },
  { name: "retrieval", kind: "ret", label: "retrieve" },
  { name: "grading", kind: "llm", label: "grade" },
  { name: "generation", kind: "llm", label: "generate" },
  { name: "faithfulness", kind: "llm", label: "check" },
]

const freshStages = (): Record<StageName, Stage> =>
  Object.fromEntries(STAGES.map((s) => [s.name, { status: "pending" }])) as Record<StageName, Stage>

/* ── Strength ──────────────────────────────────────────────────────────── */

export type StrengthKind = "good" | "warn" | "bad" | "none"
export interface Strength { label: string; kind: StrengthKind; note?: string }

export function strengthFrom(j: QueryResponse): Strength {
  const s = j.faithfulness_score
  if (j.classification === "out_of_scope") return { label: "Out of scope", kind: "none" }
  if (!j.evidence?.some((e) => e.selected)) return { label: "Unsupported", kind: "bad", note: "no references" }
  if (s == null) return { label: "Unchecked", kind: "none" }
  const n = s.toFixed(2)
  if (j.is_faithful && s >= 0.8 && !j.grader_retries) return { label: "Supported", kind: "good", note: n }
  if (j.is_faithful && (s >= 0.5 || j.grader_retries)) return { label: "Mixed", kind: "warn", note: n }
  if (s >= 0.3) return { label: "Weak", kind: "warn", note: n }
  return { label: "Unsupported", kind: "bad", note: n }
}

/* ── Errors ────────────────────────────────────────────────────────────── */

export interface Failure { what: string; why: string; next: string }

export function failureFrom(e: unknown): Failure {
  const err = e instanceof ApiError ? e : new ApiError(-1, e instanceof Error ? e.message : String(e))
  if (err.status === 401 || err.status === 403)
    return { what: "Not authorised.", why: "The sheet requires an API key and none was accepted.", next: "Add a key under Settings." }
  if (err.status === 429)
    return { what: "Rate limited.", why: "This key has used its requests-per-minute budget.", next: "Wait a minute, or use a key with a higher limit." }
  if (err.status >= 500)
    return { what: "Atlas could not complete the survey.", why: err.message, next: "Check `make health`; if Qdrant or OpenAI is down the survey cannot run." }
  if (err.status === 0)
    return { what: "Could not reach Atlas.", why: err.message, next: "Check the API base under Settings, and that the server is running." }
  return { what: "Query failed.", why: err.message, next: "Try again." }
}

/* ── Store ─────────────────────────────────────────────────────────────── */

export type RunPhase = "idle" | "running" | "done" | "refused" | "failed"

interface RunState {
  phase: RunPhase
  question: string
  answer: string          // raw text; may still be streaming
  streaming: boolean
  stages: Record<StageName, Stage>
  evidence: Evidence[]
  citations: Citation[]
  numberToChunk: Record<number, string>
  strength: Strength | null
  claims: string[]
  failure: Failure | null
  startedAt: number
  totalMs: number | null
  tokens: TokenUsage | null
  cached: boolean
}

interface AtlasState {
  // corpus
  sheet: string
  sheets: string[]
  sources: SourceInfo[]
  sourcesLoading: boolean
  totals: { sources: number; chunks: number } | null
  health: Health["status"] | "unreachable" | "checking"
  // run
  run: RunState
  // ui
  surveyOpen: boolean
  evidenceOpen: boolean
  keyOpen: boolean
  settingsOpen: boolean
  paletteOpen: boolean
  flashChunk: string | null
  theme: "" | "light" | "dark"

  boot: () => Promise<void>
  setSheet: (s: string) => void
  loadSources: () => Promise<void>
  ask: (q: string, opts: { top_k: number; stream: boolean }) => Promise<void>
  jumpTo: (chunkId: string) => void
  set: (patch: Partial<AtlasState>) => void
  setTheme: (t: "" | "light" | "dark") => void
}

const idleRun = (): RunState => ({
  phase: "idle", question: "", answer: "", streaming: false, stages: freshStages(), evidence: [],
  citations: [], numberToChunk: {}, strength: null, claims: [], failure: null, startedAt: 0,
  totalMs: null, tokens: null, cached: false,
})

export function applyTheme(t: "" | "light" | "dark") {
  const dark = t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches)
  document.documentElement.classList.toggle("dark", dark)
}

export const useAtlas = create<AtlasState>((set, get) => ({
  sheet: ls.get("atlas_sheet") || "default",
  sheets: [],
  sources: [],
  sourcesLoading: true,
  totals: null,
  health: "checking",
  run: idleRun(),
  surveyOpen: false,
  evidenceOpen: false,
  keyOpen: false,
  settingsOpen: false,
  paletteOpen: false,
  flashChunk: null,
  theme: (ls.get("atlas_theme") as "" | "light" | "dark") || "",

  set: (patch) => set(patch),

  setTheme: (t) => { ls.set("atlas_theme", t); applyTheme(t); set({ theme: t }) },

  boot: async () => {
    getHealth().then((h) => set({ health: h.status })).catch(() => set({ health: "unreachable" }))
    let names: string[] = []
    try { names = await getSheets() } catch { /* offline */ }
    if (!names.length) names = ["default"]
    const wanted = get().sheet
    if (!names.includes(wanted)) names.unshift(wanted)
    set({ sheets: names })
    await get().loadSources()
  },

  setSheet: (s) => {
    ls.set("atlas_sheet", s)
    set({ sheet: s })
    void get().loadSources()
  },

  loadSources: async () => {
    set({ sourcesLoading: true })
    try {
      const j = await getSources(get().sheet)
      set({ sources: j.sources, totals: { sources: j.total_sources, chunks: j.total_chunks }, sourcesLoading: false })
    } catch {
      set({ sources: [], totals: null, sourcesLoading: false })
    }
  },

  jumpTo: (chunkId) => {
    set({ evidenceOpen: true, flashChunk: chunkId })
    setTimeout(() => set({ flashChunk: null }), 600)
  },

  ask: async (q, { top_k, stream }) => {
    const sheet = get().sheet
    const run: RunState = { ...idleRun(), phase: "running", question: q, streaming: stream, startedAt: performance.now() }
    set({ run, evidenceOpen: false })

    const patch = (p: Partial<RunState>) => set((s) => ({ run: { ...s.run, ...p } }))
    const stage = (name: StageName, status: StageStatus, ms?: number, detail?: string) =>
      set((s) => {
        const cur = s.run.stages[name]
        return { run: { ...s.run, stages: { ...s.run.stages, [name]: { status, ms: ms ?? cur.ms, detail: detail ?? cur.detail } } } }
      })
    const skipRest = () => (["decompose", "retrieval", "grading", "generation", "faithfulness"] as StageName[]).forEach((n) => stage(n, "skipped"))
    const finish = (extra: Partial<RunState> = {}) =>
      patch({ totalMs: extra.totalMs ?? Math.round(performance.now() - run.startedAt), ...extra })

    try {
      if (!stream) {
        const j = await postQuery(q, sheet, top_k)
        const t = j.timings
        stage("routing", "done", t.routing_ms ?? undefined, j.classification)
        if (j.classification === "out_of_scope") {
          skipRest()
          finish({ phase: "refused", strength: strengthFrom(j), totalMs: t.total_ms })
          return
        }
        if (t.decompose_ms != null) stage("decompose", "done", t.decompose_ms, `${j.sub_queries.length} sub-queries`)
        else stage("decompose", "skipped")
        stage("retrieval", "done", t.retrieval_ms ?? undefined, `${j.evidence.filter((e) => e.selected).length} selected of ${j.evidence.length}`)
        stage("grading", "done", t.grading_ms ?? undefined, gradeDetail(j.grader_score, j.grader_retries))
        stage("generation", "done", t.generation_ms ?? undefined, `${fmt(j.token_usage.prompt_tokens)} in · ${fmt(j.token_usage.completion_tokens)} out`)
        stage("faithfulness", "done", t.faithfulness_ms ?? undefined, j.faithfulness_score != null ? `score ${j.faithfulness_score.toFixed(2)}` : "")
        const numberToChunk = Object.fromEntries(j.citations.map((c) => [c.number, c.chunk_id]))
        finish({
          phase: "done", answer: j.answer, evidence: j.evidence, citations: j.citations, numberToChunk,
          strength: strengthFrom(j), claims: j.unsupported_claims, tokens: j.token_usage, cached: j.cached, totalMs: t.total_ms,
        })
        return
      }

      let answer = ""
      let genStart = 0
      for await (const ev of streamQuery(q, sheet, top_k)) {
        if (ev.type === "stage") {
          if (ev.status === "start") {
            stage(ev.name as StageName, "running")
            if (ev.name === "generation") genStart = performance.now()
            if (ev.name === "retrieval" && get().run.stages.decompose.status === "pending") stage("decompose", "skipped")
          } else if (ev.name === "routing") stage("routing", "done", ev.ms, ev.classification)
          else if (ev.name === "decompose") stage("decompose", "done", ev.ms, `${ev.sub_queries} sub-queries`)
          else if (ev.name === "retrieval") {
            stage("retrieval", "done", ev.ms, `${ev.evidence.filter((e) => e.selected).length} selected of ${ev.evidence.length}`)
            patch({ evidence: ev.evidence })
          } else if (ev.name === "grading") stage("grading", "done", ev.ms, gradeDetail(ev.score, 0, ev.sufficient))
        } else if (ev.type === "delta") {
          answer += ev.text
          patch({ answer })
        } else if (ev.type === "done") {
          if (ev.classification === "out_of_scope") {
            skipRest()
            finish({ phase: "refused", strength: { label: "Out of scope", kind: "none" } })
            return
          }
          stage("generation", "done", genStart ? Math.round(performance.now() - genStart) : undefined, "tokens not tracked on stream")
          stage("faithfulness", "skipped", undefined, "skipped while streaming")
          const numberToChunk = Object.fromEntries(ev.citations.map((c) => [c.number, c.chunk_id]))
          const byChunk = Object.fromEntries(ev.citations.map((c) => [c.chunk_id, c.number]))
          const evidence = get().run.evidence.map((e) => ({ ...e, citation: byChunk[e.chunk_id] ?? null }))
          finish({ phase: "done", streaming: false, answer, evidence, citations: ev.citations, numberToChunk, strength: { label: "Unchecked", kind: "none", note: "streamed" } })
        }
      }
    } catch (e) {
      const stages = get().run.stages
      for (const s of STAGES) if (stages[s.name].status === "running") stage(s.name, "failed")
      finish({ phase: "failed", streaming: false, failure: failureFrom(e) })
    }
  },
}))

function gradeDetail(score: number | null | undefined, retries?: number, sufficient?: boolean) {
  let d = score != null ? `score ${score.toFixed(2)}` : ""
  if (sufficient === false) d += " · insufficient"
  if (retries) d += ` · ↻ ${retries}`
  return d
}

export const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("en-US"))
export const fmtScore = (k: string, v: number) => (k === "bm25" ? v.toFixed(1) : k === "rrf" ? v.toFixed(3) : v.toFixed(2))


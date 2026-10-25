/**
 * Export a finished run as JSON.
 *
 * The record is the whole run, not the evidence array on its own: a list of
 * passages with nothing attached cannot be audited, because nothing in it
 * says what was asked, which of the passages the generator was actually
 * given, or what it wrote from them. Evidence *of* something.
 *
 * Everything here is already in the store. Exporting never calls the API and
 * never re-runs the query, so it cannot spend a token — which is the whole
 * reason it is worth having over "ask it again and copy the response".
 */

import { toast } from "sonner"

import type { Citation, Evidence, TokenUsage } from "./api"
import { STAGES, type RunPhase, type RunState } from "./store"

export interface RunExport {
  schema: "atlas.run.v1"
  exported_at: string
  sheet: string
  question: string
  /**
   * How the run ended. Without it a failed run exports as an empty evidence
   * list and an "Unchecked" verdict, which is indistinguishable from a run
   * that simply found nothing — the file would be wrong about what happened.
   */
  phase: RunPhase
  failure: { what: string; why: string } | null
  /**
   * "full" is the non-streaming /query, which checks faithfulness and counts
   * tokens. "stream" is SSE, which checks faithfulness too — the verdict
   * arrives after the answer — but still counts no tokens, so `token_usage`
   * is null on that path. That null is an absence, not a zero, and the mode
   * is recorded so a reader can tell which kind of null they are looking at.
   */
  mode: "full" | "stream"
  answer: string
  verdict: { label: string; kind: string; note: string | null }
  unsupported_claims: string[]
  citations: Citation[]
  /**
   * Every passage retrieved, not only the cited ones. `selected: false` means
   * the reranker cut it and the generator never saw it — dropping those would
   * hide what Atlas considered and rejected, which is half of what makes a
   * retrieval run reviewable.
   */
  evidence: Evidence[]
  stages: { name: string; status: string; ms: number | null; detail: string | null }[]
  total_ms: number | null
  token_usage: TokenUsage | null
  cached: boolean
}

export function buildRunExport(run: RunState, now: Date = new Date()): RunExport {
  return {
    schema: "atlas.run.v1",
    exported_at: now.toISOString(),
    sheet: run.sheet,
    question: run.question,
    phase: run.phase,
    failure: run.failure ? { what: run.failure.what, why: run.failure.why } : null,
    mode: run.streamed ? "stream" : "full",
    answer: run.answer,
    verdict: run.strength
      ? { label: run.strength.label, kind: run.strength.kind, note: run.strength.note ?? null }
      : { label: "Unchecked", kind: "none", note: null },
    unsupported_claims: run.claims,
    citations: run.citations,
    evidence: run.evidence,
    stages: STAGES.map(({ name }) => ({
      name,
      status: run.stages[name].status,
      ms: run.stages[name].ms ?? null,
      detail: run.stages[name].detail || null,
    })),
    total_ms: run.totalMs,
    token_usage: run.tokens,
    cached: run.cached,
  }
}

/** `atlas-fastapi-20261024-0915.json` — sheet first, because that is what the reader sorts by. */
export function exportFilename(run: RunExport): string {
  const sheet = run.sheet.replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "sheet"
  const t = run.exported_at.replace(/[-:]/g, "").replace("T", "-").slice(0, 13)
  return `atlas-${sheet}-${t}.json`
}

/**
 * Hand the file to the browser. Nothing is uploaded: the Blob is built in the
 * tab and the object URL is revoked on the next frame, so the data never
 * leaves the machine the console is running on.
 */
function downloadRunExport(run: RunState): string {
  const record = buildRunExport(run)
  const name = exportFilename(record)
  const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: "application/json" }))
  const a = document.createElement("a")
  a.href = url
  a.download = name
  a.click()
  requestAnimationFrame(() => URL.revokeObjectURL(url))
  return name
}

/**
 * The whole action, so that both callers -- the evidence header and ⌘K --
 * say the same thing. They used to each write their own toast, which is how
 * one surface ends up reporting a different outcome from the other.
 */
export function exportRun(run: RunState): void {
  const name = downloadRunExport(run)
  const n = run.evidence.length
  // Filename in the description, not the title: as a title it wraps
  // mid-token and the break lands inside the timestamp.
  toast.success("Run exported", {
    description: `${name} — ${n} reference${n === 1 ? "" : "s"}, the question, the answer and the stage timings.`,
  })
}

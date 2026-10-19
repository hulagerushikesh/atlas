/**
 * Atlas API client. Mirrors src/atlas/api/schemas.py — keep in step.
 */

export type Scores = Partial<Record<"dense" | "bm25" | "rrf" | "rerank" | "score", number>>

export interface Evidence {
  chunk_id: string
  source: string
  chunk_index: number
  start_char: number
  end_char: number
  page_number: number | null
  excerpt: string
  scores: Scores
  selected: boolean
  citation: number | null
}

export interface Citation {
  number: number
  chunk_id: string
  source: string
  page_number: number | null
}

export interface StageTimings {
  routing_ms?: number | null
  decompose_ms?: number | null
  // Only present when HyDE is on; it is an LLM call, not retrieval.
  hyde_ms?: number | null
  retrieval_ms?: number | null
  grading_ms?: number | null
  generation_ms?: number | null
  faithfulness_ms?: number | null
  total_ms: number
}

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  estimated_cost_usd: number
}

export interface QueryResponse {
  query: string
  answer: string
  classification: "simple" | "complex" | "out_of_scope"
  citations: Citation[]
  // null when no verdict was reached — the check was off, or the answer was
  // a refusal, which asserts nothing to ground. Not false: nothing was found
  // wrong, nothing was checked. strengthFrom() renders it "Unchecked".
  is_faithful: boolean | null
  faithfulness_score: number | null
  retrieved_chunk_ids: string[]
  timings: StageTimings
  token_usage: TokenUsage
  grader_retries: number
  cached: boolean
  sub_queries: string[]
  grader_score: number | null
  unsupported_claims: string[]
  evidence: Evidence[]
  // The passages retrieval searched with when HyDE is on, empty otherwise.
  hypotheses?: string[]
}

export interface SourceInfo { source: string; doc_type: string; chunks: number }
export interface SourceList {
  namespace: string; sources: SourceInfo[]; total_sources: number
  // total_chunks is the keyword index's count; dense_chunks is the vector
  // store's. They are persisted separately and can disagree — null means the
  // vector store could not be read, which is not the same as zero.
  total_chunks: number; dense_chunks: number | null
  consistent: boolean | null; warning: string | null
}
export interface Health { status: "ok" | "degraded" | "down"; version: string }
export interface IngestResult {
  documents_processed: number; documents_skipped: number; chunks_indexed: number
  total_tokens: number; duration_seconds: number
}

export interface RejectedUpload { filename: string; reason: string }

export interface UploadResult extends IngestResult {
  namespace: string
  accepted: string[]
  // Files the server would not index, each with a reason. Surfaced in the UI
  // rather than summarised: an upload that drops 3 of 10 files and reports
  // "7 indexed" is indistinguishable from a complete one.
  rejected: RejectedUpload[]
}

/** Streaming events as emitted by _stream_query. */
export type StreamEvent =
  | { type: "stage"; name: string; status: "start" }
  | { type: "stage"; name: "routing"; status: "done"; classification: string; ms: number }
  | { type: "stage"; name: "decompose"; status: "done"; sub_queries: number; ms: number }
  | { type: "stage"; name: "retrieval"; status: "done"; chunks: number; ms: number; evidence: Evidence[] }
  | { type: "stage"; name: "grading"; status: "done"; score: number; sufficient: boolean; ms: number }
  | { type: "delta"; text: string }
  // `is_faithful` is always null here: the streaming path skips the
  // faithfulness check, so there is no verdict to report. It is typed
  // nullable rather than omitted so that reading it cannot look like a
  // pass -- the API used to send `true` on this path, which it had not
  // checked. The store renders "Unchecked" off the absent score.
  | { type: "done"; classification: string; citations: Citation[]; is_faithful: boolean | null; answer?: string }
  // Sent when the pipeline throws after the first byte. The response is a 200
  // by then — the status line left before the pipeline had a chance to fail —
  // so this event is the only way the failure can reach the client at all.
  | { type: "error"; error: string; stage: string }

const KEY = "atlas_api_key"
const BASE = "atlas_api_base"

export const store = {
  get(k: string) { try { return localStorage.getItem(k) ?? "" } catch { return "" } },
  set(k: string, v: string) { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k) } catch { /* private mode */ } },
}

export class ApiError extends Error {
  status: number
  // The raw `detail`, kept because some errors carry structure a string
  // cannot hold -- /ingest/upload's 422 lists every refused file and why.
  detail?: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message); this.status = status; this.detail = detail
  }
}

function base() { return store.get(BASE).replace(/\/$/, "") }

export async function api(path: string, init: RequestInit = {}, timeoutMs?: number): Promise<Response> {
  const headers = new Headers(init.headers)
  const key = store.get(KEY)
  if (key) headers.set("Authorization", `Bearer ${key}`)
  const signal = timeoutMs ? AbortSignal.timeout(timeoutMs) : init.signal
  let r: Response
  try {
    r = await fetch(base() + path, { ...init, headers, signal })
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : "network error")
  }
  if (!r.ok) {
    let detail: unknown = r.statusText
    try { const j = await r.json(); detail = j.detail ?? detail } catch { /* not json */ }
    const message = typeof detail === "string" ? detail : r.statusText
    throw new ApiError(r.status, message, detail)
  }
  return r
}

export const getHealth = () => api("/health", {}, 3000).then((r) => r.json() as Promise<Health>)
export const getSheets = () =>
  api("/namespaces", {}, 3000).then((r) => r.json()).then((j) => (j.namespaces as { name: string }[]).map((n) => n.name))
export const getSources = (sheet: string) =>
  api(`/namespaces/${encodeURIComponent(sheet)}/sources`, {}, 4000).then((r) => r.json() as Promise<SourceList>)
export const postIngest = (path: string, namespace: string) =>
  api("/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path, namespace }) })
    .then((r) => r.json() as Promise<IngestResult>)

/**
 * Upload files and index them into `namespace`, creating it if it is new.
 *
 * Multipart, because `/ingest` takes a path on the *server* and a browser has
 * no way to give it one -- the console may be talking to a container in
 * another region. No Content-Type is set: the browser must add the multipart
 * boundary itself, and setting it by hand produces a request the server
 * cannot parse.
 */
export async function postUpload(files: File[], namespace: string): Promise<UploadResult> {
  const form = new FormData()
  for (const f of files) form.append("files", f, f.name)
  form.append("namespace", namespace)
  try {
    const r = await api("/ingest/upload", { method: "POST", body: form })
    return await r.json() as UploadResult
  } catch (e) {
    // A 422 means every file was refused, and its `detail` is an object whose
    // reasons are the whole answer; the generic handler would stringify it to
    // "[object Object]".
    if (e instanceof ApiError && e.status === 422) {
      const d = e.detail as { rejected?: RejectedUpload[] } | undefined
      const why = d?.rejected?.map((r) => `${r.filename}: ${r.reason}`).join("; ")
      throw new ApiError(422, why ? `nothing could be indexed — ${why}` : e.message)
    }
    throw e
  }
}

export const postQuery = (query: string, namespace: string, top_k: number) =>
  api("/query", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, namespace, top_k, stream: false }) })
    .then((r) => r.json() as Promise<QueryResponse>)

/** Iterate SSE events from the streaming /query endpoint. */
export async function* streamQuery(query: string, namespace: string, top_k: number): AsyncGenerator<StreamEvent> {
  const r = await api("/query", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, namespace, top_k, stream: true }) })
  if (!r.body) return
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ""
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let nl: number
    while ((nl = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 2)
      if (!raw.startsWith("data:")) continue
      const data = raw.slice(5).trim()
      if (data === "[DONE]") continue
      try { yield JSON.parse(data) as StreamEvent } catch { /* malformed line */ }
    }
  }
}

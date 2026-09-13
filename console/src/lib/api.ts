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
  is_faithful: boolean
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
}

export interface SourceInfo { source: string; doc_type: string; chunks: number }
export interface SourceList { namespace: string; sources: SourceInfo[]; total_sources: number; total_chunks: number }
export interface Health { status: "ok" | "degraded" | "down"; version: string }
export interface IngestResult {
  documents_processed: number; documents_skipped: number; chunks_indexed: number
  total_tokens: number; duration_seconds: number
}

/** Streaming events as emitted by _stream_query. */
export type StreamEvent =
  | { type: "stage"; name: string; status: "start" }
  | { type: "stage"; name: "routing"; status: "done"; classification: string; ms: number }
  | { type: "stage"; name: "decompose"; status: "done"; sub_queries: number; ms: number }
  | { type: "stage"; name: "retrieval"; status: "done"; chunks: number; ms: number; evidence: Evidence[] }
  | { type: "stage"; name: "grading"; status: "done"; score: number; sufficient: boolean; ms: number }
  | { type: "delta"; text: string }
  | { type: "done"; classification: string; citations: Citation[]; is_faithful: boolean; answer?: string }

const KEY = "atlas_api_key"
const BASE = "atlas_api_base"

export const store = {
  get(k: string) { try { return localStorage.getItem(k) ?? "" } catch { return "" } },
  set(k: string, v: string) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k) } catch { /* private mode */ } },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
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
    let detail = r.statusText
    try { const j = await r.json(); detail = j.detail ?? detail } catch { /* not json */ }
    throw new ApiError(r.status, detail)
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

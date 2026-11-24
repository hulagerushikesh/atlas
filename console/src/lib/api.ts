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
  // False for the corpus ROUTER_DOMAIN describes: the ingest endpoints
  // refuse it, because a document that does not fit the description indexes
  // fine and is then refused as out of scope at query time. `description` is
  // the sentence being protected -- the reason, without which read-only
  // reads as arbitrary. Optional so a console pointed at an older server
  // defaults to writable and behaves as it did before.
  writable?: boolean; description?: string | null
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
  // `is_faithful` is always null here: at the moment `done` is sent nothing
  // has been checked yet. It is typed nullable rather than omitted so that
  // reading it cannot look like a pass -- the API used to send `true` on
  // this path, which it had not checked.
  //
  // `verdict_pending` says whether a `verdict` event is still coming, so the
  // UI can show "checking" instead of guessing. Optional, because a server
  // older than the verdict event does not send it: absent reads as false,
  // and the client then behaves exactly as it did before.
  //
  // `cached` is present only when the whole stream was replayed from the
  // query cache. Worth surfacing rather than swallowing: a replayed answer
  // was produced against the corpus as it stood up to an hour ago, and the
  // stage timings in that stream are the original run's, not this one's.
  | { type: "done"; classification: string; citations: Citation[]; is_faithful: boolean | null; answer?: string; verdict_pending?: boolean; cached?: boolean }
  // The faithfulness verdict, sent after `done` because the check runs once
  // the answer is already on screen. Nulls mean no verdict was reached --
  // the answer was a refusal, or the judge itself failed -- which is not the
  // same as a failed check, and renders "Unchecked" rather than a bad grade.
  | { type: "verdict"; is_faithful: boolean | null; score: number | null; unsupported_claims: string[]; ms: number }
  // Sent when the pipeline throws after the first byte. The response is a 200
  // by then — the status line left before the pipeline had a chance to fail —
  // so this event is the only way the failure can reach the client at all.
  // `code` is "demo_paused" when the model provider has no credit left.
  | { type: "error"; error: string; stage: string; code?: string }

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
  // A signed-in person's writes must carry this: the session cookie rides on
  // any request to this site, and this header is what says the console sent it.
  headers.set("X-Requested-With", "atlas")
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

/* ── Key lifecycle ─────────────────────────────────────────────────────────
 * Guarded by X-Admin-Secret, not by the Bearer key the rest of this client
 * sends. The secret is passed in by the caller on every call and never
 * reaches `store` — it is the credential that can revoke every key, so it
 * lives in memory for the tab and nowhere else.
 */

export interface KeyRecord {
  key_id: number | string
  name: string
  email: string
  is_active: boolean
  rate_limit_rpm: number
  created_at: number | null
  total_queries: number
  last_query_at: number | null
}

export const getKeys = (secret: string) =>
  api("/keys", { headers: { "X-Admin-Secret": secret } }, 5000)
    .then((r) => r.json())
    .then((j) => j.keys as KeyRecord[])

export const setKeyActive = (keyId: number | string, isActive: boolean, secret: string) =>
  api(`/keys/${encodeURIComponent(String(keyId))}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-Admin-Secret": secret },
    body: JSON.stringify({ is_active: isActive }),
  }, 5000).then((r) => r.json() as Promise<KeyRecord>)

/* ── Sign-in and the organisation page (E1.3) ──────────────────────────────
 * The session is an HttpOnly cookie: this code never sees it, the browser
 * sends it. Roles are named by sheet, the way the server takes them.
 */

export type Role = "reader" | "editor" | "admin"
export type Grants = Record<string, Role>

export interface AuthConfig { enabled: boolean; google_client_id: string }
export interface Me {
  kind: "user" | "service" | "visitor" | "anonymous"
  user: { id: string; email: string; name: string } | null
  org: { id: string; name: string } | null
  org_admin: boolean
  workspaces: { name: string; role: Role }[]
}
export interface OrgMember { id: string; email: string; name: string; org_admin: boolean; roles: Grants; you: boolean; groups: string[] }
export interface OrgGroup { id: string; name: string }
export interface OrgInvitation { email: string; org_admin: boolean; roles: Grants; created_at: number | null }
export interface OrgServiceAccount {
  key_id: number | string; name: string; is_active: boolean; roles: Grants
  total_queries: number; last_query_at: number | null
}
export interface Org {
  org: { id: string; name: string }
  domain: string
  workspaces: { id: string; name: string }[]
  members: OrgMember[]
  invitations: OrgInvitation[]
  service_accounts: OrgServiceAccount[]
  groups: OrgGroup[]
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
})

export const getAuthConfig = () => api("/auth/config", {}, 3000).then((r) => r.json() as Promise<AuthConfig>)
/** Null when nobody is signed in: the server answers 401 for that. */
export const getMe = () =>
  api("/auth/me", {}, 3000).then((r) => r.json() as Promise<Me>).catch((e) => {
    if (e instanceof ApiError && e.status === 401) return null
    throw e
  })
export const signInWithGoogle = (credential: string) =>
  api("/auth/google", { method: "POST", ...json({ credential }) }, 10000).then((r) => r.json() as Promise<Me>)
export const signOut = () => api("/auth/logout", { method: "POST" }, 5000)

export const getOrg = () => api("/org", {}, 5000).then((r) => r.json() as Promise<Org>)
export const createSheet = (name: string) =>
  api("/org/workspaces", { method: "POST", ...json({ name }) }, 5000)
export const invite = (email: string, org_admin: boolean, roles: Grants) =>
  api("/org/invitations", { method: "POST", ...json({ email, org_admin, roles }) }, 5000)
export const withdrawInvitation = (email: string) =>
  api(`/org/invitations/${encodeURIComponent(email)}`, { method: "DELETE" }, 5000)
export const updateMember = (id: string, org_admin: boolean, roles: Grants, groups?: string[]) =>
  api(`/org/members/${encodeURIComponent(id)}`, { method: "PUT", ...json({ org_admin, roles, groups }) }, 5000)
export const createGroup = (name: string) =>
  api("/org/groups", { method: "POST", ...json({ name }) }, 5000)
export const deleteGroup = (id: string) =>
  api(`/org/groups/${encodeURIComponent(id)}`, { method: "DELETE" }, 5000)

/* ── One document's readers, and removing it (E2.3) ────────────────────────
 * Editor only. A document the caller cannot read answers 404 exactly like
 * one that does not exist, so a hidden document's name cannot be probed.
 */

export interface DocumentAccess {
  source: string
  everyone: boolean
  groups: string[]
  people: string[]
  passages: number
  /** Readers that no longer resolve: a deleted group, someone who left. */
  others: number
  /** Every group in the organisation, to choose from. */
  choices: string[]
}
const docs = (sheet: string) => `/namespaces/${encodeURIComponent(sheet)}/documents`
export const getDocumentAccess = (sheet: string, source: string) =>
  api(`${docs(sheet)}/access?source=${encodeURIComponent(source)}`, {}, 5000)
    .then((r) => r.json() as Promise<DocumentAccess>)
export const setDocumentAccess = (sheet: string, source: string, everyone: boolean, groups: string[], people: string[]) =>
  api(`${docs(sheet)}/access`, { method: "PUT", ...json({ source, everyone, groups, people }) }, 10000)
    .then((r) => r.json() as Promise<DocumentAccess>)
export const removeDocument = (sheet: string, source: string) =>
  api(`${docs(sheet)}?source=${encodeURIComponent(source)}`, { method: "DELETE" }, 10000)
    .then((r) => r.json() as Promise<{ source: string; passages_removed: number }>)
export const removeMember = (id: string) =>
  api(`/org/members/${encodeURIComponent(id)}`, { method: "DELETE" }, 5000)
export const createServiceAccount = (name: string, roles: Grants) =>
  api("/org/service-accounts", { method: "POST", ...json({ name, roles }) }, 5000)
    .then((r) => r.json() as Promise<{ key: string; key_id: number | string; name: string }>)
export const revokeServiceAccount = (keyId: number | string) =>
  api(`/org/service-accounts/${encodeURIComponent(String(keyId))}`, { method: "DELETE" }, 5000)

/** The message a structured error carries, else the plain one. */
export function messageOf(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { message?: unknown } | undefined
    if (d && typeof d.message === "string") return d.message
    return e.message
  }
  return e instanceof Error ? e.message : String(e)
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

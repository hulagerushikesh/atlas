import { useState, type ReactNode } from "react"
import { motion } from "motion/react"
import { ArrowRight, Check, Code2, Copy, SunMoon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { applyTheme } from "@/lib/store"
import { store as ls } from "@/lib/api"

const EASE = [0.23, 1, 0.32, 1] as const
export const GITHUB = "https://github.com/hulagerushikesh/atlas"

/* ── Reveal ────────────────────────────────────────────────────────────── */

export function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.5, ease: EASE, delay }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

export function SectionHead({ eyebrow, title, children }: { eyebrow: string; title: ReactNode; children?: ReactNode }) {
  return (
    <Reveal className="max-w-[60ch]">
      <div className="label">{eyebrow}</div>
      <h2 className="mt-2 font-display text-[36px] font-semibold uppercase leading-[1.02] tracking-[0.01em] text-balance sm:text-[44px]">{title}</h2>
      {children && <p className="mt-4 text-[18px] leading-relaxed text-ink-2">{children}</p>}
    </Reveal>
  )
}

/* ── Nav ───────────────────────────────────────────────────────────────── */

export function Nav() {
  const cycle = () => {
    const cur = ls.get("atlas_theme") as "" | "light" | "dark"
    const next = cur === "" ? "dark" : cur === "dark" ? "light" : ""
    ls.set("atlas_theme", next); applyTheme(next)
  }
  return (
    <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-12 max-w-6xl items-center gap-6 px-5">
        <a href="/" className="font-display text-xl font-bold uppercase tracking-[0.06em]">Atlas</a>
        <nav className="label hidden items-center gap-5 md:flex">
          <a href="#how" className="transition-colors hover:text-foreground">How it works</a>
          <a href="#notes" className="transition-colors hover:text-foreground">Field notes</a>
          <a href="#start" className="transition-colors hover:text-foreground">Quick start</a>
        </nav>
        <div className="ml-auto flex items-center gap-1.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" className="press" onClick={cycle} aria-label="Cycle theme"><SunMoon className="size-4" /></Button>
            </TooltipTrigger>
            <TooltipContent>Theme</TooltipContent>
          </Tooltip>
          <Button asChild variant="ghost" size="sm" className="press font-mono text-[11px] uppercase tracking-wider">
            <a href={GITHUB} target="_blank" rel="noreferrer"><Code2 className="size-3.5" /> <span className="hidden sm:inline">GitHub</span></a>
          </Button>
          <Button asChild size="sm" className="press font-mono text-[11px] uppercase tracking-wider">
            <a href="/app">Open console <ArrowRight className="size-3.5" /></a>
          </Button>
        </div>
      </div>
    </header>
  )
}

/* ── Principles ────────────────────────────────────────────────────────── */

const PRINCIPLES = [
  {
    k: "faithfulness",
    t: "Every claim is checked against the evidence.",
    b: "After generating, Atlas splits the answer into claims and verifies each one against the retrieved references. Unsupported claims are flagged in the answer — dashed, visible — never silently included.",
  },
  {
    k: "refusal",
    t: "When the sheet doesn't cover it, it says so.",
    b: "The router classifies every question before retrieval runs. Out-of-scope questions stop there: no retrieval, no generation, no plausible-sounding guess. A refusal is a designed state with its own screen.",
  },
  {
    k: "provenance",
    t: "The survey is part of the answer.",
    b: "Dense and BM25 scores, the RRF fusion, the rerank cut, the grader's verdict, timing per stage, tokens and cost — all of it ships with the response and all of it is on screen. Nothing is hidden behind a spinner.",
  },
]

export function Principles() {
  return (
    <section className="mx-auto max-w-6xl px-5 py-24">
      <SectionHead eyebrow="Why Atlas" title="Wrong answers cost more than slow ones.">
        Most RAG systems optimise for fluency. Atlas optimises for trust: every response is grounded, traceable, and honest about its limits.
      </SectionHead>
      <div className="mt-12 border-t">
        {PRINCIPLES.map((p, i) => (
          <Reveal key={p.k} delay={i * 0.06}>
            <div className="group grid gap-3 border-b py-7 md:grid-cols-[180px_1fr] md:gap-8">
              <div className="label pt-1.5 text-blue">{p.k}</div>
              <div>
                <h3 className="font-display text-[24px] font-semibold leading-tight">{p.t}</h3>
                <p className="mt-2 max-w-[62ch] text-[16.5px] leading-relaxed text-ink-2">{p.b}</p>
              </div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

/* ── Pipeline ──────────────────────────────────────────────────────────── */

const STAGES = [
  { n: "Route", kind: "llm", d: "Classifies the question as simple, complex, or out of scope. Out-of-scope questions exit here — no retrieval, no generation." },
  { n: "Decompose", kind: "llm", d: "Complex, multi-hop questions are split into up to four sub-questions, each retrieved independently and merged before grading." },
  { n: "Retrieve", kind: "ret", d: "Dense (Qdrant ANN) and sparse (BM25) search run in parallel. Reciprocal Rank Fusion merges the lists; a cross-encoder reranks the top 20 and keeps the best 5." },
  { n: "Grade", kind: "llm", d: "Scores whether the retrieved context can answer the question. If not, reformulates and retries — up to twice — before anything is generated." },
  { n: "Generate", kind: "llm", d: "Writes the answer with inline citations, each linked to its reference. The prompt forbids facts that are not in the context." },
  { n: "Check", kind: "llm", d: "Splits the answer into claims and verifies each against the references. Anything ungrounded is flagged in the answer and listed beneath it." },
]

export function Pipeline() {
  return (
    <section id="how" className="border-t bg-card">
      <div className="mx-auto grid max-w-6xl gap-12 px-5 py-24 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="lg:sticky lg:top-24 lg:self-start">
          <SectionHead eyebrow="How it works" title="Six stages. Each one can stop the next.">
            Atlas does not call one model and return whatever comes back. Every query is routed, retrieved, graded, generated, and checked — and each stage can halt or retry before the next runs.
          </SectionHead>
          <div className="label mt-8 flex flex-wrap gap-x-5 gap-y-1">
            <span className="inline-flex items-center gap-2"><i className="size-2.5 rounded-[2px] bg-blue" />retrieval</span>
            <span className="inline-flex items-center gap-2"><i className="size-2.5 rounded-[2px] bg-ochre" />language model</span>
          </div>
        </div>
        <ol className="relative border-l border-border">
          {STAGES.map((s, i) => (
            <Reveal key={s.n} delay={i * 0.05}>
              <li className="relative pb-9 pl-8 last:pb-0">
                <i className={cn("absolute -left-[5px] top-2 size-[9px] rounded-[2px]", s.kind === "ret" ? "bg-blue" : "bg-ochre")} />
                <div className="flex items-baseline gap-3">
                  <span className="label tabular">{String(i + 1).padStart(2, "0")}</span>
                  <h3 className="font-display text-[24px] font-semibold leading-none">{s.n}</h3>
                </div>
                <p className="mt-2 max-w-[58ch] text-[16px] leading-relaxed text-ink-2">{s.d}</p>
              </li>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  )
}

/* ── Field notes ───────────────────────────────────────────────────────── */

const NOTES = [
  { t: "Reciprocal Rank Fusion", b: <>BM25 sums and cosine similarity live on incompatible scales; averaging them is meaningless. RRF uses rank alone — <code>score = Σ 1/(k + rank)</code>, <code>k = 60</code> — so any retriever contributes without calibration.</> },
  { t: "Two-level cache", b: <>An in-memory LRU sits in front of Redis. Keys are the lower-cased query hash, per sheet. A repeated question answers in under a millisecond and costs nothing.</> },
  { t: "Idempotent indexing", b: <>Every chunk is fingerprinted with xxhash. Re-running ingestion skips unchanged content, so the index can be refreshed on a schedule without duplicating a single reference.</> },
  { t: "Quota-aware retries", b: <>OpenAI returns 429 for both throttling and an exhausted balance. Atlas retries the first with back-off and fails the second immediately — the difference between a two-second error and a seven-minute hang.</> },
  { t: "Per-request tracing", b: <>Each request gets a UUID bound to the structured log context. The same id appears on every line from every stage, and comes back as <code>X-Request-Id</code>.</> },
  { t: "Tested against the real client", b: <>Retrieval tests run against Qdrant's in-process local mode, not a mock. A mock once let a removed method survive a fully green suite; this one would not.</> },
]

export function FieldNotes() {
  return (
    <section id="notes" className="mx-auto max-w-6xl px-5 py-24">
      <SectionHead eyebrow="Field notes" title="Decisions worth writing down." />
      <div className="mt-12 grid gap-x-10 gap-y-8 md:grid-cols-2">
        {NOTES.map((n, i) => (
          <Reveal key={n.t} delay={(i % 2) * 0.06}>
            <div className="border-t pt-4">
              <h3 className="font-mono text-[13px] font-medium uppercase tracking-[0.08em]">{n.t}</h3>
              <p className="mt-2 text-[15.5px] leading-relaxed text-ink-2 [&_code]:rounded-sm [&_code]:border [&_code]:bg-well [&_code]:px-1 [&_code]:font-mono [&_code]:text-[13px] [&_code]:text-foreground">{n.b}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

/* ── Measured ──────────────────────────────────────────────────────────── */

const MEASURED = [
  { k: "Context precision", v: "0.42", d: "of the 5 chunks handed to the generator came from a labelled-relevant page" },
  { k: "Context recall", v: "0.78", d: "of labelled pages had at least one chunk retrieved — 3 of 15 questions missed" },
  { k: "Faithfulness", v: "1.00", d: "of answer claims grounded in the retrieved references, per the claim-level judge" },
  { k: "Answer relevance", v: "0.83", d: "question ↔ answer alignment (RAGAS reverse-question), ±0.01 run to run" },
]

export function Measured() {
  return (
    <section id="measured" className="mx-auto max-w-6xl px-5 py-24">
      <SectionHead eyebrow="Measured · 2026-09-20" title="First live run, numbers included.">
        Full FastAPI documentation — 155 files, 4,021 references — indexed and queried through the real
        pipeline. 15 questions, three runs; retrieval metrics are deterministic run to run. Two of the first
        run&apos;s five misses were labelling errors — fixed in the dataset, not the code, and re-measured.
      </SectionHead>
      <div className="mt-12 grid gap-px overflow-hidden rounded-[3px] border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {MEASURED.map((m, i) => (
          <Reveal key={m.k} delay={i * 0.05} className="bg-background p-5">
            <div className="label">{m.k}</div>
            <div className="mt-2 font-display text-[40px] font-semibold leading-none tabular">{m.v}</div>
            <p className="mt-3 text-[14px] leading-relaxed text-ink-2">{m.d}</p>
          </Reveal>
        ))}
      </div>
      <Reveal delay={0.2} className="mt-6 max-w-[72ch] text-[15px] leading-relaxed text-ink-2">
        The honest read: faithfulness is real but easy on documentation questions; precision is the number to
        move. The three remaining recall misses are genuine — adjacent tutorial pages outranked the target — and
        the planned fixes are a wider rerank window, HyDE, and contextual chunk headers. Full per-question
        breakdown in the README.
      </Reveal>
    </section>
  )
}

/* ── Quick start ───────────────────────────────────────────────────────── */

const STEPS = [
  { t: "Add your API key", b: <>Copy <code>.env.example</code> to <code>.env</code> and set <code>OPENAI_API_KEY</code> — any OpenAI-compatible endpoint works via <code>OPENAI_BASE_URL</code>; the measured run used Gemini. Everything else has local defaults.</> },
  { t: "Start the infrastructure", b: <>Qdrant and Redis run in Docker; the API runs on your machine.</> },
  { t: "Fetch and index a corpus", b: <>The bundled script downloads the FastAPI docs (MIT, 155 files). Ingest fails fast and names the file if anything goes wrong.</> },
  { t: "Serve", b: <>Console at <code>/app</code>, Swagger at <code>/docs</code>, Prometheus at <code>/metrics</code>.</> },
  { t: "Ask", b: <>Use the console, or <code>POST /query</code> and read the evidence straight from the response.</> },
]

const SCRIPT = `cp .env.example .env            # set OPENAI_API_KEY
make docker-up                    # qdrant + redis
make install
make fetch-corpus && make ingest  # 155 FastAPI docs
make serve                        # → http://localhost:8010/app`

export function QuickStart() {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    // Synchronous path first: it completes inside the click gesture and
    // never waits on a permission prompt. The async API is the fallback.
    let ok = false
    const ta = document.createElement("textarea")
    ta.value = SCRIPT; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0"
    document.body.appendChild(ta); ta.select()
    try { ok = document.execCommand("copy") } catch { ok = false } finally { ta.remove() }
    if (!ok) void navigator.clipboard?.writeText(SCRIPT).catch(() => {})
    setCopied(true); setTimeout(() => setCopied(false), 1600)
  }
  return (
    <section id="start" className="border-t bg-card">
      <div className="mx-auto grid max-w-6xl gap-12 px-5 py-24 lg:grid-cols-2">
        <div>
          <SectionHead eyebrow="Quick start" title="From zero to cited answers in five commands.">
            Requires Docker, Python 3.11, and an OpenAI-compatible key (Gemini works). The whole pipeline — ingestion, retrieval, faithfulness — runs locally.
          </SectionHead>
          <ol className="mt-10 space-y-5">
            {STEPS.map((s, i) => (
              <Reveal key={s.t} delay={i * 0.04}>
                <li className="grid grid-cols-[32px_1fr] gap-3">
                  <span className="label pt-1 tabular">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <h3 className="font-display text-[20px] font-semibold leading-tight">{s.t}</h3>
                    <p className="mt-1 text-[15px] leading-relaxed text-ink-2 [&_code]:rounded-sm [&_code]:border [&_code]:bg-well [&_code]:px-1 [&_code]:font-mono [&_code]:text-[13px] [&_code]:text-foreground">{s.b}</p>
                  </div>
                </li>
              </Reveal>
            ))}
          </ol>
        </div>
        <Reveal delay={0.1} className="lg:sticky lg:top-24 lg:self-start">
          <div className="overflow-hidden rounded-lg border bg-background">
            <div className="label flex h-9 items-center justify-between border-b px-3">
              <span>bash</span>
              <Button variant="ghost" size="sm" className="press h-6 gap-1.5 px-2 font-mono text-[11px] uppercase tracking-wider" onClick={copy}>
                {copied ? <Check className="size-3.5 text-good" /> : <Copy className="size-3.5" />}{copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed"><code>{SCRIPT.split("\n").map((l, i) => {
              const [cmd, comment] = l.split(/\s{2,}#/)
              return <span key={i} className="block">{cmd}{comment && <span className="text-ink-3">{"  # " + comment}</span>}</span>
            })}</code></pre>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

/* ── Footer ────────────────────────────────────────────────────────────── */

export function Footer() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-5 py-6">
        <span className="label">Atlas · MIT · Python 3.11 · FastAPI · Qdrant · OpenAI</span>
        <nav className="label ml-auto flex gap-5">
          <a href="/app" className="transition-colors hover:text-foreground">Console</a>
          <a href="/docs" className="transition-colors hover:text-foreground">API docs</a>
          <a href={GITHUB} className="transition-colors hover:text-foreground" target="_blank" rel="noreferrer">GitHub</a>
        </nav>
      </div>
    </footer>
  )
}

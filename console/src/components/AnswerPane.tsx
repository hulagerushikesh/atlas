import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { AnimatePresence, motion } from "motion/react"
import { ArrowRight, ArrowUp, Compass } from "lucide-react"
import { Button } from "@/components/ui/button"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Kbd } from "@/components/ui/kbd"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { fmtScore, useAtlas, type Strength } from "@/lib/store"
import type { Evidence } from "@/lib/api"
import { cn } from "@/lib/utils"
import { WhatIsThis } from "@/components/WhatIsThis"
import { Orientation } from "@/components/Orientation"
import { ASK, openerFor } from "@/lib/glossary"

const EASE = [0.23, 1, 0.32, 1] as const

/* ── Answer document ───────────────────────────────────────────────────── */

const SENTENCE = /(?<=[.!?])\s+(?=[A-Z0-9[(])/
// The model writes a small markdown subset: **bold**, `code`, bullet and
// numbered lists, the odd heading. A full markdown library would be more
// than the answer needs and would fight the citation chips; this covers
// what the generator prompt actually produces.
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[\d+\])/
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/
const HEADING = /^#{1,6}\s+/

type CiteRenderer = (n: number, key: number) => ReactNode

function Inline({ text, cite }: { text: string; cite: CiteRenderer }) {
  return (
    <>
      {text.split(INLINE).map((part, k) => {
        if (!part) return null
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={k} className="font-semibold text-foreground">{part.slice(2, -2)}</strong>
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return <code key={k} className="rounded-[3px] border border-border bg-well px-1 py-px font-mono text-[0.86em]">{part.slice(1, -1)}</code>
        }
        const m = part.match(/^\[(\d+)\]$/)
        if (m) return cite(Number(m[1]), k)
        return <span key={k}>{part}</span>
      })}
    </>
  )
}

// One paragraph → sentences; sentences without a citation get the dashed
// "unsourced" underline. Skipped while streaming: the last sentence would
// flicker between states as tokens arrive.
function Sentences({ text, cite, streaming }: { text: string; cite: CiteRenderer; streaming: boolean }) {
  if (streaming) return <Inline text={text} cite={cite} />
  return (
    <>
      {text.split(SENTENCE).map((sent, si) => {
        const body = <Inline text={sent} cite={cite} />
        return /\[\d+\]/.test(sent) ? (
          <span key={si}>{body}{" "}</span>
        ) : (
          <span key={si} className="text-ink-2 underline decoration-dashed decoration-ink-3 decoration-1 underline-offset-[3px]" title="No reference supports this sentence.">
            {body}{" "}
          </span>
        )
      })}
    </>
  )
}

function Blocks({ text, cite, streaming }: { text: string; cite: CiteRenderer; streaming: boolean }) {
  const paras = text.trim().split(/\n{2,}/)
  // The streaming caret sits on the last block so it follows the text.
  const tail = (pi: number) => streaming && pi === paras.length - 1 ? "caret" : undefined
  return (
    <>
      {paras.map((para, pi) => {
        const lines = para.split("\n")
        if (lines.length > 0 && lines.every((l) => BULLET.test(l) || !l.trim())) {
          const items = lines.filter((l) => l.trim())
          const ordered = /^\s*\d/.test(items[0] ?? "")
          const Tag = ordered ? "ol" : "ul"
          return (
            <Tag key={pi} className={cn("space-y-1.5 pl-5", ordered ? "list-decimal" : "list-disc marker:text-ink-3")}>
              {items.map((l, li) => (
                <li key={li} className={li === items.length - 1 ? tail(pi) : undefined}>
                  <Sentences text={l.replace(BULLET, "")} cite={cite} streaming={streaming} />
                </li>
              ))}
            </Tag>
          )
        }
        if (HEADING.test(para) && lines.length === 1) {
          return <p key={pi} className={cn("font-semibold text-foreground", tail(pi))}>{para.replace(HEADING, "")}</p>
        }
        return <p key={pi} className={tail(pi)}><Sentences text={para} cite={cite} streaming={streaming} /></p>
      })}
    </>
  )
}

function AnswerDoc({ text, evidenceByChunk, numberToChunk, streaming }: {
  text: string
  evidenceByChunk: Record<string, Evidence>
  numberToChunk: Record<number, string>
  streaming: boolean
}) {
  // While streaming: same block layout so markdown never shows raw, but
  // citations stay plain text and sentences are not graded — the evidence
  // map is not final and the last sentence would jump between states.
  // Once complete, crossfade to the full document with chips.
  if (streaming) {
    const plain: CiteRenderer = (n, key) => <span key={key} className="font-mono text-[0.86em] text-ink-3">[{n}]</span>
    return (
      <div className="space-y-4">
        <Blocks text={text} cite={plain} streaming />
      </div>
    )
  }
  const chip: CiteRenderer = (n, key) => {
    const chunkId = numberToChunk[n]
    const ev = chunkId ? evidenceByChunk[chunkId] : undefined
    return <CitationChip key={key} n={n} evidence={ev} />
  }
  return (
    <motion.div
      key="doc"
      initial={{ opacity: 0, filter: "blur(2px)" }} animate={{ opacity: 1, filter: "blur(0px)" }}
      transition={{ duration: 0.28, ease: EASE }}
      className="space-y-4"
    >
      <Blocks text={text} cite={chip} streaming={false} />
    </motion.div>
  )
}

function CitationChip({ n, evidence }: { n: number; evidence?: Evidence }) {
  const jumpTo = useAtlas((s) => s.jumpTo)
  const chip = (
    <motion.button
      type="button"
      initial={{ opacity: 0, scale: 0.85 }} animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.18, ease: EASE, delay: 0.12 }}
      onClick={() => evidence && jumpTo(evidence.chunk_id)}
      className={cn(
        "press relative -top-px ml-0.5 inline-flex h-[15px] min-w-[15px] items-center justify-center rounded-[3px] px-1 align-super font-mono text-[10px] font-medium leading-none text-card transition-colors",
        evidence ? "bg-blue hover:bg-blue/85" : "bg-ink-3 cursor-default",
      )}
      title={evidence ? `Reference ${n}` : `Reference ${n} not in evidence`}
    >
      {n}
    </motion.button>
  )
  if (!evidence) return chip
  return (
    <HoverCard openDelay={250} closeDelay={80}>
      <HoverCardTrigger asChild>{chip}</HoverCardTrigger>
      <HoverCardContent side="top" align="start" className="w-80 space-y-2 p-3">
        <div className="flex items-center gap-2 font-mono text-[12px]">
          <span className="inline-flex h-[15px] min-w-[15px] items-center justify-center rounded-[3px] bg-blue px-1 text-[10px] font-medium text-card">{n}</span>
          <span className="min-w-0 flex-1 truncate">{evidence.source}</span>
          <span className="text-ink-3">ref {evidence.chunk_index}</span>
        </div>
        <p className="line-clamp-4 text-[13px] leading-snug text-ink-2">{evidence.excerpt}</p>
        <div className="label flex flex-wrap gap-x-3 gap-y-1 normal-case tracking-normal tabular">
          {(["dense", "bm25", "rrf", "rerank"] as const).filter((k) => evidence.scores[k] != null).map((k) => (
            <span key={k}><b className="font-medium text-ink-2">{k}</b> {fmtScore(k, evidence.scores[k]!)}</span>
          ))}
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

/* ── Strength badge ────────────────────────────────────────────────────── */

const KIND: Record<Strength["kind"], string> = {
  good: "border-good bg-good-soft text-good",
  warn: "border-warn bg-warn-soft text-warn",
  bad: "border-bad bg-bad-soft text-bad",
  none: "border-border text-ink-3",
}

function StrengthBadge({ s }: { s: Strength }) {
  const set = useAtlas((st) => st.set)
  return (
    <motion.button
      type="button"
      initial={{ opacity: 0, scale: 0.94, y: 4 }} animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: 0.22, ease: EASE }}
      onClick={() => set({ evidenceOpen: true })}
      className={cn("press mt-5 inline-flex items-center gap-2 rounded-[3px] border px-2 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.06em]", KIND[s.kind], s.pending && "animate-pulse-soft")}
      role="status"
      aria-busy={s.pending || undefined}
    >
      {s.label}{s.note && <span className="opacity-80">· {s.note}</span>}
    </motion.button>
  )
}

/* ── Signposts ─────────────────────────────────────────────────────────── */

/*
 * The two things a stalled reader needs, in the two places they stall: the
 * blank box and a refusal. Shared so the subject of the sheet is worded the
 * same in both, and so neither can quietly lose it.
 */

function Holds({ covers, className }: { covers: string; className?: string }) {
  return (
    <p className={className}>
      {ASK.holds} <span className="font-medium text-foreground">{covers}</span>.
    </p>
  )
}

function Opener({ question, onAsk }: { question: string; onAsk: (q: string) => void }) {
  return (
    <div className="mt-4">
      <div className="label mb-1.5">{ASK.tryHint}</div>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onAsk(question)}
        className="press h-auto max-w-full justify-start gap-2 whitespace-normal py-1.5 text-left font-sans text-[14px] font-normal leading-snug"
      >
        <span className="min-w-0">{question}</span>
        <ArrowRight className="size-3.5 shrink-0 text-ink-3" />
      </Button>
    </div>
  )
}

/* ── Pane ──────────────────────────────────────────────────────────────── */

export function AnswerPane() {
  const { run, sheet, sheetCovers, ask, tourOpen } = useAtlas()
  const [q, setQ] = useState("")
  const [topK, setTopK] = useState(5)
  const [stream, setStream] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const evidenceByChunk = useMemo(() => Object.fromEntries(run.evidence.map((e) => [e.chunk_id, e])), [run.evidence])

  // Follow the stream, but only while it is running.
  useEffect(() => {
    if (run.streaming && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [run.answer, run.streaming])

  // Global "/" focuses the ask box.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault(); taRef.current?.focus()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const submit = () => {
    const text = q.trim()
    if (!text || run.phase === "running") return
    void ask(text, { top_k: topK, stream })
  }

  // A signpost question runs with the same options as a typed one, and lands
  // in the box too, so the reader can see what was asked and edit it rather
  // than facing an answer to a question they never wrote down.
  const opener = openerFor(sheet)
  const askOpener = (text: string) => {
    if (run.phase === "running") return
    setQ(text)
    void ask(text, { top_k: topK, stream })
  }

  return (
    <section className="flex min-w-0 flex-1 flex-col bg-card">
      <div ref={scrollRef} className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-4 md:px-8">
        <div className="label inline-flex items-center gap-1.5">Answer<WhatIsThis pane="answer" /></div>
        <div className="mt-3 max-w-[68ch] text-[18px] leading-[1.6]">
          <AnimatePresence mode="wait" initial={false}>
            {run.phase === "idle" ? (
              <motion.div key="idle" exit={{ opacity: 0 }}>
                {/* First visit gets the orientation card; everyone after it
                    gets the one line, because by then the layout is known
                    and a repeated explanation is just something to scroll
                    past. */}
                {tourOpen ? (
                  <Orientation />
                ) : (
                  <div className="max-w-[52ch]">
                    <Compass className="mb-3 size-5 text-ink-3" strokeWidth={1.5} />
                    <div className="label normal-case leading-relaxed tracking-normal">
                      <p>{ASK.empty}</p>
                      {sheetCovers && <Holds covers={sheetCovers} className="mt-2" />}
                    </div>
                    {opener && <Opener question={opener} onAsk={askOpener} />}
                  </div>
                )}
              </motion.div>
            ) : (
              <motion.div key={run.startedAt} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, ease: EASE }}>
                <h2 className="mb-4 font-display text-[22px] font-semibold leading-[1.15] text-balance">
                  <span className="label mb-1.5 block font-normal">Question</span>
                  {run.question}
                </h2>

                {run.phase === "refused" ? (
                  <div>
                    <h3 className="mb-2 font-display text-[22px] font-semibold">Routed out of scope.</h3>
                    {/* Not "this sheet has no references covering it": the router
                        decides before anything is retrieved, so nothing has looked
                        at the sheet when this renders. A corpus uploaded from the
                        console was refused here on 2026-10-13 while holding exactly
                        the references the old copy said it lacked. */}
                    <p className="text-ink-2">The question was judged outside what <b className="font-semibold text-foreground">{sheet}</b> covers, before any reference was read.</p>
                    {/* The description is printed rather than described: it is
                        the exact sentence the classifier was given, so a reader
                        who thinks the refusal is wrong can see what was claimed
                        and say which half is at fault. Without it, the advice
                        below asks them to audit a rule they cannot read. */}
                    {sheetCovers && <Holds covers={sheetCovers} className="mt-2 text-ink-2" />}
                    <p className="mt-2 text-ink-2">Try another sheet — or, if this sheet does cover it, the corpus description the router was given is wrong.</p>
                  </div>
                ) : run.phase === "failed" && run.failure ? (
                  <div className="max-w-[68ch] rounded-[3px] border-l-[3px] border-bad bg-bad-soft px-4 py-3 font-mono text-[13px] leading-relaxed">
                    <b className="block font-medium text-bad">{run.failure.what}</b>
                    <span className="block text-ink-2">{run.failure.why}</span>
                    <span className="block text-ink-2">{run.failure.next}</span>
                  </div>
                ) : (
                  <AnswerDoc text={run.answer} evidenceByChunk={evidenceByChunk} numberToChunk={run.numberToChunk} streaming={run.phase === "running"} />
                )}

                {run.strength && <StrengthBadge s={run.strength} />}

                {/* Below the badge, not above it: DESIGN §6 puts the strength
                    badge directly under the answer, and a refusal is still an
                    answer. The way out comes after the verdict, not inside it. */}
                {run.phase === "refused" && opener && run.question !== opener && (
                  <Opener question={opener} onAsk={askOpener} />
                )}

                {run.claims.length > 0 && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }} className="mt-4 text-[14px] text-ink-2">
                    <div className="label mb-1">Unsupported claims</div>
                    <ul className="list-disc space-y-0.5 pl-5">{run.claims.map((c, i) => <li key={i}>{c}</li>)}</ul>
                  </motion.div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); submit() }}
        className="shrink-0 border-t bg-card px-6 py-3 md:px-8"
      >
        <div className="relative">
          <Textarea
            ref={taRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit() } }}
            placeholder="Ask the sheet…"
            rows={2}
            aria-label="Question"
            className="min-h-14 resize-none bg-well pr-12 font-sans text-[17px] leading-[1.45] focus-visible:ring-1 focus-visible:ring-ring"
          />
          <Button
            type="submit" size="icon-sm" disabled={!q.trim() || run.phase === "running"}
            className="press absolute bottom-2 right-2 rounded-[4px]"
            aria-label="Ask"
          >
            <ArrowUp className="size-4" />
          </Button>
        </div>
        <div className="label mt-2 flex items-center gap-4 normal-case tracking-[0.04em]">
          <label className="inline-flex items-center gap-1.5">top_k
            <input type="number" min={1} max={50} value={topK} onChange={(e) => setTopK(Math.max(1, Math.min(50, Number(e.target.value) || 5)))}
              className="h-6 w-12 rounded-[3px] border bg-well px-1.5 text-center font-mono text-[12px] tabular text-foreground focus:border-blue focus:outline-none" />
          </label>
          <label className="inline-flex items-center gap-1.5">
            <Switch checked={stream} onCheckedChange={setStream} className="scale-90" /> stream
          </label>
          <span className="ml-auto hidden items-center gap-1 sm:inline-flex"><Kbd>/</Kbd> focus · <Kbd>↵</Kbd> ask</span>
        </div>
      </form>
    </section>
  )
}


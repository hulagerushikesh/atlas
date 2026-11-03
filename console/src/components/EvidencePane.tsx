import { useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { Download, Layers, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { Evidence } from "@/lib/api"
import { exportRun } from "@/lib/export"
import { fmt, fmtScore, useAtlas } from "@/lib/store"
import { scoreLabel, scoreNote, type ScoreKey } from "@/lib/glossary"
import { WhatIsThis } from "@/components/WhatIsThis"
import { cn } from "@/lib/utils"

const EASE = [0.23, 1, 0.32, 1] as const
const ORDER = ["dense", "bm25", "rrf", "rerank", "score"] as const

function topScore(e: Evidence) { return e.scores.rerank ?? e.scores.rrf ?? e.scores.score ?? 0 }

/*
 * A score with its name in plain words, and the jargon one hover away.
 *
 * These printed as `dense 0.82  bm25 4.71  rrf 0.031  rerank 0.94` until
 * 2026-11-03. Every number was honest and none of them were legible: the
 * first outside reader could not tell which one the cut was made on, and
 * read the tiny `rrf` as a bad result when a small number is all that score
 * can ever be. The label is now the plain word; the technical name, what
 * produced the number and how to read its scale live in the tooltip.
 *
 * Focusable on purpose -- a tooltip hung on a bare span is unreachable
 * without a mouse. The click is swallowed so reading a score does not also
 * expand the card underneath it.
 */
function ScoreChip({ k, v }: { k: ScoreKey; v: number }) {
  const note = scoreNote(k)
  const body = (
    <span className="cursor-help">
      <b className="font-medium text-ink-2">{scoreLabel(k)}</b> {fmtScore(k, v)}
    </span>
  )
  if (!note) return body
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="rounded-[2px] outline-none focus-visible:ring-2 focus-visible:ring-blue" onClick={(ev) => ev.stopPropagation()}>
          {body}
        </span>
      </TooltipTrigger>
      {/* One child: TooltipContent is an `inline-flex` row, so three
          siblings become three squeezed columns. */}
      <TooltipContent className="max-w-[34ch]">
        <span className="block space-y-1.5 text-pretty">
          <span className="block font-medium">{note.technical}</span>
          <span className="block">{note.what}</span>
          <span className="block opacity-80">{note.read}</span>
        </span>
      </TooltipContent>
    </Tooltip>
  )
}

function RefCard({ e, max, index }: { e: Evidence; max: number; index: number }) {
  const flash = useAtlas((s) => s.flashChunk === e.chunk_id)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLElement>(null)
  const n = e.citation
  const pct = Math.max(2, Math.round((100 * topScore(e)) / max))

  useEffect(() => {
    if (flash) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [flash])

  return (
    <motion.article
      ref={ref}
      layout="position"
      initial={{ opacity: 0, y: 8 }}
      animate={{
        opacity: e.selected ? 1 : 0.62,
        y: 0,
        boxShadow: flash ? "0 0 0 3px var(--blue-soft), 0 0 0 1px var(--blue)" : "0 0 0 0px transparent",
      }}
      transition={{ duration: 0.26, ease: EASE, delay: Math.min(index, 8) * 0.04, boxShadow: { duration: 0.2 } }}
      onClick={() => setOpen((v) => !v)}
      className={cn(
        "cursor-pointer rounded-md border bg-card p-3 transition-[border-color,transform] duration-150 ease-[var(--ease-out-strong)] hover:-translate-y-px",
        n ? "border-blue" : "border-border hover:border-ink-3",
      )}
    >
      <div className="flex items-center gap-2 font-mono text-[12px]">
        {n && <span className="inline-flex h-[15px] min-w-[15px] items-center justify-center rounded-[3px] bg-blue px-1 text-[10px] font-medium text-card">{n}</span>}
        <span className="min-w-0 flex-1 truncate" title={e.source}>{e.source}</span>
        <span className="shrink-0 text-ink-3">ref {e.chunk_index}</span>
      </div>
      <div className="label mt-1 normal-case tracking-normal tabular">
        chars {fmt(e.start_char)}–{fmt(e.end_char)}{e.page_number != null && ` · p.${e.page_number}`}
      </div>
      <p className={cn("mt-1.5 text-[13.5px] leading-snug text-ink-2", !open && "line-clamp-2")}>{e.excerpt}</p>
      <div className="label mt-2 flex flex-wrap gap-x-3 gap-y-1 normal-case tracking-normal tabular">
        {ORDER.filter((k) => e.scores[k] != null).map((k) => (
          <ScoreChip key={k} k={k} v={e.scores[k]!} />
        ))}
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-[1px] bg-well">
        <motion.i
          className={cn("block h-full", e.selected ? "bg-blue" : "bg-ink-3")}
          initial={{ width: 0 }} animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5, ease: EASE, delay: 0.15 + Math.min(index, 8) * 0.04 }}
        />
      </div>
      {!e.selected && <div className="label mt-1.5 normal-case tracking-normal">cut at rerank · not sent to the generator</div>}
    </motion.article>
  )
}

export function EvidenceList() {
  const { run } = useAtlas()
  const ev = run.evidence
  const max = Math.max(...ev.map(topScore), 1e-9)

  if (run.phase === "running" && ev.length === 0) {
    return (
      <div className="mt-3 space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="rounded-md border p-3">
            <Skeleton className="h-3 w-[75%]" /><Skeleton className="mt-2 h-2.5 w-[40%]" />
            <Skeleton className="mt-3 h-3 w-full" /><Skeleton className="mt-1 h-3 w-[85%]" />
            <Skeleton className="mt-3 h-1 w-full" />
          </div>
        ))}
      </div>
    )
  }
  if (ev.length === 0) {
    return (
      <div className="label mt-3 normal-case leading-relaxed tracking-normal">
        {run.phase === "refused" ? "Nothing was retrieved — the router stopped before the survey." : "References appear here as they are found."}
      </div>
    )
  }
  return (
    <div className="mt-3 flex flex-col gap-2">
      <AnimatePresence initial={true}>
        {ev.map((e, i) => <RefCard key={e.chunk_id} e={e} max={max} index={i} />)}
      </AnimatePresence>
    </div>
  )
}

function Header() {
  const { run, evidenceOpen, set } = useAtlas()
  const n = run.evidence.length
  return (
    <div className="flex h-10 shrink-0 items-center justify-between gap-1 border-b px-4">
      <span className="label inline-flex min-w-0 items-center gap-2"><Layers className="size-3.5" />Evidence · {n} ref{n === 1 ? "" : "s"}<WhatIsThis pane="evidence" /></span>
      <div className="flex shrink-0 items-center">
        <ExportButton />
        {evidenceOpen && (
          <Button variant="ghost" size="icon-sm" className="press xl:hidden" onClick={() => set({ evidenceOpen: false })} aria-label="Close evidence">
            <X className="size-4" />
          </Button>
        )}
      </div>
    </div>
  )
}

/**
 * Offered on any finished run, including a refusal and a failure. Those two
 * export an empty evidence list, which is the point: the record says Atlas
 * was asked and retrieved nothing, and the stages say how far it got. A
 * button that only appeared on the happy path would make the awkward runs
 * the ones you cannot keep.
 */
export function ExportButton() {
  const run = useAtlas((s) => s.run)
  const ready = run.phase !== "idle" && run.phase !== "running"
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost" size="icon-sm" className="press" disabled={!ready}
          aria-label="Export this run as JSON"
          onClick={() => exportRun(run)}
        >
          <Download className="size-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{ready ? "Export this run as JSON" : "Export — run a query first"}</TooltipContent>
    </Tooltip>
  )
}

/** Docked at ≥ xl; a slide-over drawer below that. */
export function EvidencePane() {
  const { evidenceOpen, set } = useAtlas()
  return (
    <>
      <aside className="hidden h-full w-[300px] shrink-0 flex-col border-l bg-sidebar xl:flex">
        <Header />
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 pb-4"><EvidenceList /></div>
      </aside>

      <AnimatePresence>
        {evidenceOpen && (
          <>
            <motion.div
              key="scrim" className="fixed inset-0 z-30 bg-foreground/20 xl:hidden"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}
              onClick={() => set({ evidenceOpen: false })}
            />
            <motion.aside
              key="drawer"
              className="fixed inset-y-0 right-0 z-40 flex w-[min(340px,92vw)] flex-col border-l bg-sidebar shadow-lg xl:hidden"
              initial={{ transform: "translateX(100%)" }} animate={{ transform: "translateX(0%)" }} exit={{ transform: "translateX(100%)" }}
              transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
            >
              <Header />
              <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 pb-4"><EvidenceList /></div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

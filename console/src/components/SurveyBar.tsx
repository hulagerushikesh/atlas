import { AnimatePresence, motion } from "motion/react"
import { ChevronUp, Route } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { STAGES, fmt, useAtlas, type Stage, type StageStatus } from "@/lib/store"
import { cn } from "@/lib/utils"

const EASE = [0.23, 1, 0.32, 1] as const

function Figs() {
  const { run } = useAtlas()
  if (run.phase === "idle") return <>no query yet</>
  if (run.phase === "running") return <span className="animate-pulse-soft">running</span>
  if (run.phase === "failed") return <span className="text-bad">failed</span>
  const done = Object.values(run.stages).filter((s) => s.status === "done").length
  return (
    <>
      {done} stage{done === 1 ? "" : "s"} · {fmt(Math.round(run.totalMs ?? 0))} ms
      {run.tokens && <> · {fmt(run.tokens.total_tokens)} tok · ${run.tokens.estimated_cost_usd.toFixed(4)}</>}
      {run.cached && <> · cached</>}
    </>
  )
}

function Segment({ label, kind, s, total, alt }: { label: string; kind: "ret" | "llm"; s: Stage; total: number; alt: boolean }) {
  const colour = kind === "ret" ? "bg-blue" : "bg-ochre"
  const base = "relative flex h-3 min-w-[3px] items-center overflow-hidden whitespace-nowrap px-1 font-mono text-[8px] uppercase tracking-[0.06em] text-card"
  if (s.status === "pending") return null
  if (s.status === "skipped")
    return <div className={cn(base, "shrink-0 border border-ink-3 text-ink-3 line-through")} style={{ flex: "0 0 auto" }}>{label}</div>
  if (s.status === "failed")
    return <div className={cn(base, "bg-bad")} style={{ flex: "1 1 0%" }}>{label}</div>
  if (s.status === "running")
    return <div className={cn(base, colour, "animate-pulse-soft")} style={{ flex: "1 1 0%" }}>{label}</div>
  const grow = Math.max(s.ms ?? 0, total * 0.015)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <motion.div layout className={cn(base, colour, alt && "opacity-80")} style={{ flex: `${grow} 1 0%` }} transition={{ duration: 0.3, ease: EASE }}>
          {label}
        </motion.div>
      </TooltipTrigger>
      <TooltipContent className="font-mono text-[11px]">{label} · {fmt(Math.round(s.ms ?? 0))} ms</TooltipContent>
    </Tooltip>
  )
}

const MARK: Record<StageStatus | "ret" | "llm", string> = {
  ret: "bg-blue", llm: "bg-ochre",
  pending: "", done: "", running: "bg-ochre animate-pulse-soft", skipped: "border border-ink-3", failed: "bg-bad",
}

export function SurveyBar() {
  const { run, surveyOpen, set } = useAtlas()
  const rows = STAGES.map((s) => ({ ...s, ...run.stages[s.name] }))
  const total = rows.reduce((a, r) => a + (r.status === "done" ? r.ms ?? 0 : 0), 0)
  const anyRun = rows.some((r) => r.status !== "pending")

  let last = ""
  return (
    <footer className="shrink-0 border-t bg-card">
      <div className="flex h-8 items-center gap-4 px-4">
        <span className="label inline-flex items-center gap-2"><Route className="size-3.5" />Survey</span>
        <span className="label min-w-0 truncate normal-case tracking-[0.06em] tabular text-ink-2"><Figs /></span>
        <Button variant="ghost" size="sm" className="press ml-auto h-6 gap-1 px-2 font-mono text-[11px] uppercase tracking-wider" onClick={() => set({ surveyOpen: !surveyOpen })} aria-expanded={surveyOpen}>
          {surveyOpen ? "Collapse" : "Expand"}
          <ChevronUp className={cn("size-3.5 transition-transform duration-200 ease-[var(--ease-out-strong)]", surveyOpen && "rotate-180")} />
        </Button>
      </div>

      <div className="mx-4 mb-2 flex h-3 gap-0.5">
        {!anyRun
          ? rows.map((r) => <div key={r.name} className="label flex h-3 flex-1 items-center border border-dashed px-1 text-[8px] leading-none">{r.label}</div>)
          : rows.map((r) => {
              const alt = r.status === "done" && r.kind === last
              last = alt ? "" : r.status === "done" ? r.kind : last
              return <Segment key={r.name} label={r.label} kind={r.kind} s={r} total={total} alt={alt} />
            })}
      </div>

      <AnimatePresence initial={false}>
        {surveyOpen && (
          <motion.div
            key="table"
            initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ height: { duration: 0.26, ease: EASE }, opacity: { duration: 0.16 } }}
            className="overflow-hidden border-t border-border/60"
          >
            <div className="max-h-[38vh] overflow-auto px-4 py-2">
              <table className="w-full border-collapse font-mono text-[13px] tabular">
                <thead>
                  <tr className="label text-left">
                    <th className="border-b py-1 pr-3 font-medium">Stage</th>
                    <th className="border-b py-1 pr-3 font-medium">ms</th>
                    <th className="border-b py-1 font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.filter((r) => r.status !== "pending").map((r, i) => (
                    <motion.tr key={r.name} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.03 }} className="border-b border-border/60 align-top text-ink-2">
                      <td className="whitespace-nowrap py-1.5 pr-3 text-foreground">
                        <i className={cn("mr-2 inline-block size-[9px] align-[-1px]", r.status === "done" ? MARK[r.kind] : MARK[r.status])} />
                        {r.status === "skipped" ? <s>{r.label}</s> : r.label}
                      </td>
                      <td className="py-1.5 pr-3">{r.ms != null ? fmt(Math.round(r.ms)) : r.status === "skipped" ? "—" : "…"}</td>
                      <td className="py-1.5">
                        {(r.detail ?? (r.status === "skipped" ? "not reached" : "")).split(/(↻ \d+)/).map((part, k) =>
                          /^↻ \d+$/.test(part) ? <span key={k} className="text-warn">{part}</span> : <span key={k}>{part}</span>)}
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </footer>
  )
}

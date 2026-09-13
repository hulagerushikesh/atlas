import { useEffect, useState } from "react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import { cn } from "@/lib/utils"

/**
 * The hero is a survey, not a tagline: a real question runs through the
 * pipeline on a loop — stages land, references arrive, the answer streams
 * with its citations, the strength badge settles. Everything shown is the
 * shape of a real /query response.
 */

const EASE = [0.23, 1, 0.32, 1] as const

const QUESTION = "How do path parameters get validated?"

const STAGES = [
  { name: "route", kind: "llm", ms: 41, detail: "simple" },
  { name: "retrieve", kind: "ret", ms: 286, detail: "5 selected of 12" },
  { name: "grade", kind: "llm", ms: 198, detail: "score 0.91" },
  { name: "generate", kind: "llm", ms: 940, detail: "1,412 in · 96 out" },
  { name: "check", kind: "llm", ms: 412, detail: "score 0.96" },
] as const

const REFS = [
  { n: 1, src: "tutorial/path-params.md", ref: 3, scores: "bm25 11.2 · rerank .95", w: 95, cited: true },
  { n: 2, src: "tutorial/path-params.md", ref: 5, scores: "bm25 8.6 · rerank .88", w: 88, cited: true },
  { n: 0, src: "reference/exceptions.md", ref: 1, scores: "dense .61 · rerank .52", w: 52, cited: false },
] as const

const ANSWER: { t: string; c?: number }[] = [
  { t: "Path parameters are declared with curly braces in the route and received as function arguments" },
  { t: ".", c: 1 },
  { t: " Declaring a type — " },
  { t: "item_id: int" },
  { t: " — makes FastAPI parse and validate the value, and a non-integer is rejected with a structured error" },
  { t: ".", c: 2 },
]

type Phase = "idle" | "route" | "retrieve" | "grade" | "generate" | "check" | "done"
const ORDER: Phase[] = ["idle", "route", "retrieve", "grade", "generate", "check", "done"]
const idx = (p: Phase) => ORDER.indexOf(p)

export function HeroSurvey() {
  const reduce = useReducedMotion()
  const [phase, setPhase] = useState<Phase>(reduce ? "done" : "idle")
  const [typed, setTyped] = useState(reduce ? ANSWER.length : 0)

  // Timeline. Durations are display pacing, not the ms figures shown.
  useEffect(() => {
    if (reduce) return
    const t: number[] = []
    const at = (ms: number, fn: () => void) => t.push(window.setTimeout(fn, ms))
    const loop = () => {
      setPhase("idle"); setTyped(0)
      at(600, () => setPhase("route"))
      at(1100, () => setPhase("retrieve"))
      at(2100, () => setPhase("grade"))
      at(2700, () => setPhase("generate"))
      ANSWER.forEach((_, i) => at(2800 + i * 260, () => setTyped(i + 1)))
      at(2800 + ANSWER.length * 260 + 200, () => setPhase("check"))
      at(2800 + ANSWER.length * 260 + 900, () => setPhase("done"))
      at(2800 + ANSWER.length * 260 + 6500, loop)
    }
    loop()
    return () => t.forEach(clearTimeout)
  }, [reduce])

  const p = idx(phase)
  const stageState = (i: number) => (p > i + 1 ? "done" : p === i + 1 ? "running" : "pending")
  const total = STAGES.reduce((a, s) => a + s.ms, 0)

  return (
    <div className="relative rounded-lg border bg-card shadow-[0_1px_2px_rgba(0,0,0,.05)]">
      {/* header */}
      <div className="label flex h-9 items-center gap-2 overflow-hidden whitespace-nowrap border-b px-4">
        <span className="text-foreground">Atlas</span><span>·</span><span>sheet</span><b className="font-medium text-foreground">fastapi</b>
        <span className="hidden sm:inline">· 121 sources</span>
        <span className="ml-auto inline-flex items-center gap-1.5"><i className="size-1.5 rounded-[1px] bg-good" /> ok</span>
      </div>

      <div className="grid gap-0 md:grid-cols-[1fr_240px]">
        {/* answer */}
        <div className="min-h-[300px] p-5">
          <div className="label mb-1.5">Question</div>
          <div className="font-display text-[20px] font-semibold leading-tight">{QUESTION}</div>
          <div className="mt-4 min-h-[128px] text-[15.5px] leading-[1.6]">
            {p >= idx("generate") ? (
              <p className={cn(phase === "generate" && "caret")}>
                {ANSWER.slice(0, typed).map((seg, i) => (
                  <span key={i}>
                    {seg.t === "item_id: int" ? <code className="rounded-sm border bg-well px-1 font-mono text-[13px]">{seg.t}</code> : seg.t}
                    {seg.c && p >= idx("check") && (
                      <motion.span initial={{ opacity: 0, scale: 0.85 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.18, ease: EASE }}
                        className="relative -top-px ml-0.5 inline-flex h-[14px] min-w-[14px] items-center justify-center rounded-[3px] bg-blue px-1 align-super font-mono text-[9px] font-medium leading-none text-card">
                        {seg.c}
                      </motion.span>
                    )}
                  </span>
                ))}
              </p>
            ) : (
              <p className="label normal-case tracking-normal">
                {phase === "idle" ? "Surveying…" : phase === "route" ? "Routing the question…" : phase === "retrieve" ? "Retrieving references…" : "Grading the context…"}
              </p>
            )}
          </div>
          <AnimatePresence>
            {phase === "done" && (
              <motion.span
                initial={{ opacity: 0, scale: 0.94, y: 4 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.22, ease: EASE }}
                className="mt-3 inline-flex items-center gap-2 rounded-[3px] border border-good bg-good-soft px-2 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-good"
              >
                Supported <span className="opacity-80">· 0.96</span>
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        {/* evidence */}
        <div className="border-t bg-sidebar p-3 md:border-l md:border-t-0">
          <div className="label mb-2">Evidence · {p >= idx("retrieve") + 1 ? REFS.length : 0} refs</div>
          <div className="flex flex-col gap-2">
            <AnimatePresence>
              {p >= idx("retrieve") + 1 && REFS.map((r, i) => (
                <motion.div
                  key={r.src + r.ref}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: r.cited ? 1 : 0.6, y: 0 }} exit={{ opacity: 0 }}
                  transition={{ duration: 0.26, ease: EASE, delay: i * 0.06 }}
                  className={cn("rounded-md border bg-card p-2.5 font-mono text-[11px]", r.cited && p >= idx("check") ? "border-blue" : "border-border")}
                >
                  <div className="flex items-center gap-1.5">
                    {r.cited && p >= idx("check") && <span className="inline-flex h-[13px] min-w-[13px] items-center justify-center rounded-[2px] bg-blue px-1 text-[9px] font-medium text-card">{r.n}</span>}
                    <span className="min-w-0 flex-1 truncate">{r.src}</span>
                    <span className="text-ink-3">ref {r.ref}</span>
                  </div>
                  <div className="mt-1 text-[10px] text-ink-3 tabular">{r.scores}</div>
                  <div className="mt-1.5 h-[3px] overflow-hidden rounded-[1px] bg-well">
                    <motion.i className={cn("block h-full", r.cited ? "bg-blue" : "bg-ink-3")} initial={{ width: 0 }} animate={{ width: `${r.w}%` }} transition={{ duration: 0.5, ease: EASE, delay: 0.2 + i * 0.06 }} />
                  </div>
                  {!r.cited && <div className="mt-1 text-[10px] text-ink-3">cut at rerank</div>}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* survey */}
      <div className="border-t px-4 py-2">
        <div className="label flex items-center gap-3 tabular">
          Survey
          <span className="text-ink-2 normal-case tracking-[0.06em]">
            {phase === "done" ? `5 stages · ${total.toLocaleString()} ms · 1,508 tok · $0.0004` : phase === "idle" ? "no query yet" : "running"}
          </span>
        </div>
        <div className="mt-1.5 flex h-2.5 gap-0.5">
          {STAGES.map((s, i) => {
            const st = stageState(i)
            const colour = s.kind === "ret" ? "bg-blue" : "bg-ochre"
            if (st === "pending") return <div key={s.name} className="label flex h-2.5 flex-1 items-center border border-dashed px-1 text-[7px] leading-none">{s.name}</div>
            return (
              <motion.div
                key={s.name} layout
                className={cn("flex h-2.5 items-center overflow-hidden whitespace-nowrap px-1 font-mono text-[7px] uppercase tracking-[0.06em] text-card", colour, st === "running" && "animate-pulse-soft", i % 2 === 1 && st === "done" && "opacity-80")}
                style={{ flex: st === "running" ? "1 1 0%" : `${s.ms} 1 0%` }}
                transition={{ duration: 0.3, ease: EASE }}
                title={`${s.name} · ${s.ms} ms`}
              >
                {s.name}
              </motion.div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

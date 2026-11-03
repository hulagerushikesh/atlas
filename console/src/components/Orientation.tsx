import { motion } from "motion/react"
import { ArrowRight, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { openerFor, TOUR, WHERE_CLASS } from "@/lib/glossary"
import { useAtlas } from "@/lib/store"

const EASE = [0.23, 1, 0.32, 1] as const

/*
 * What a first-time reader sees instead of an empty answer pane.
 *
 * The product's claim is that it shows its work, and the first outside
 * reader (2026-10-25) proved that showing is not the same as explaining: he
 * ran queries, read four panes of real output, and came away unable to say
 * what two of them were. The gap was never the data. It was that nothing in
 * the product ever introduced itself.
 *
 * Deliberately not a spotlight tour. Below `xl` the evidence pane is a
 * drawer and the corpus pane is gone entirely, so anything that points at
 * fixed screen regions is lying on half the devices that load it. A card in
 * the one pane that is always present says the same thing and cannot
 * mis-aim.
 *
 * The opening question matters as much as the labels: a reader who
 * understands the layout and still faces a blank box has only moved the
 * stall. One click runs a real query whose answer the reader can check
 * against any other assistant.
 */
export function Orientation() {
  const { sheet, setTour, ask } = useAtlas()
  const opener = openerFor(sheet)

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.26, ease: EASE }}
      className="max-w-[58ch] rounded-md border bg-background p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-[19px] font-semibold leading-tight">Four places, one query.</h2>
          <p className="label mt-1 normal-case tracking-normal">Atlas shows where an answer came from. Here is what each part is.</p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          className="press -mr-1 -mt-1 shrink-0"
          aria-label="Dismiss orientation"
          onClick={() => setTour(false)}
        >
          <X className="size-4" />
        </Button>
      </div>

      <ol className="mt-3.5 flex flex-col gap-2.5">
        {TOUR.map((step) => (
          <li key={step.n} className="flex gap-2.5">
            <span className="mt-px inline-flex size-[18px] shrink-0 items-center justify-center rounded-[3px] bg-well font-mono text-[11px] text-ink-2">
              {step.n}
            </span>
            <p className="text-[14px] leading-snug text-ink-2">
              <b className="font-semibold text-foreground">
                {step.name}
                <span className={WHERE_CLASS[step.whereAt]}>, {step.where}</span>.
              </b>{" "}
              {step.what}
            </p>
          </li>
        ))}
      </ol>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-3.5">
        {opener && (
          <Button
            size="sm"
            className="press gap-1.5"
            onClick={() => {
              setTour(false)
              void ask(opener, { top_k: 5, stream: true })
            }}
          >
            Try it <ArrowRight className="size-3.5" />
          </Button>
        )}
        <Button variant="ghost" size="sm" className="press" onClick={() => setTour(false)}>
          I'll explore
        </Button>
        {opener && <p className="label min-w-0 basis-full normal-case tracking-normal">“{opener}”</p>}
      </div>
    </motion.div>
  )
}

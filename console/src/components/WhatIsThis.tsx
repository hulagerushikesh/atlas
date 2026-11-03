import { HelpCircle } from "lucide-react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { PANES } from "@/lib/glossary"

/*
 * The "what am I looking at" mark that sits in every pane header.
 *
 * Atlas renders a pipeline rather than a chat, which is the point of it and
 * also the reason a newcomer stalls: four regions appear at once and none of
 * them says what it is for. The first outside reader (2026-10-25) drove the
 * console successfully and still could not say what the right-hand column
 * was. One mark per header, same shape in all four, so the habit transfers
 * after the first use.
 *
 * A button, not a decorated span: this has to be reachable by keyboard, and
 * on a touch screen there is no hover, so it has to be tappable. `type` is
 * set because CorpusPane's header sits inside a form.
 */
export function WhatIsThis({ pane }: { pane: keyof typeof PANES }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`What is the ${pane} pane?`}
          className="press -m-1 inline-flex shrink-0 rounded-[3px] p-1 text-ink-3 outline-none transition-colors duration-150 hover:text-ink-2 focus-visible:ring-2 focus-visible:ring-blue"
        >
          <HelpCircle className="size-3.5" strokeWidth={1.75} />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-[40ch] text-pretty">{PANES[pane].what}</TooltipContent>
    </Tooltip>
  )
}

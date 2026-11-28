import { useEffect, useState } from "react"
import { ThumbsDown, ThumbsUp } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { messageOf, postFeedback, type FeedbackReason } from "@/lib/api"
import { cn } from "@/lib/utils"

const REASONS: [FeedbackReason, string][] = [
  ["wrong_answer", "Wrong answer"], ["wrong_source", "Wrong source"], ["no_answer", "Didn't answer"], ["other", "Other"],
]

/**
 * One click on whether an answer helped (E6.1). A thumbs-down asks why, in
 * one more click; the comment is optional. It goes to the organisation's
 * admins, in Members → Unanswered questions.
 */
export function FeedbackBar({ sheet, question, sources, startedAt }: {
  sheet: string; question: string; sources: string[]; startedAt: number
}) {
  const [state, setState] = useState<"ask" | "why" | "sent">("ask")
  const [reason, setReason] = useState<FeedbackReason | null>(null)
  const [comment, setComment] = useState("")
  useEffect(() => { setState("ask"); setReason(null); setComment("") }, [startedAt])

  const send = async (rating: "up" | "down", why?: FeedbackReason) => {
    try {
      await postFeedback({ sheet, question, rating, reason: why, comment: comment.trim() || undefined, sources })
      setState("sent")
    } catch (e) { toast.error("Feedback not sent", { description: messageOf(e) }) }
  }

  if (state === "sent") return <p className="label mt-4 normal-case tracking-normal">Thanks. Your admins can see this.</p>
  return (
    <div className="mt-4 space-y-2">
      <div className="label flex items-center gap-1 normal-case tracking-normal">
        Did this help?
        <Button variant="ghost" size="icon-sm" className="press size-7" aria-label="Helpful" onClick={() => void send("up")}>
          <ThumbsUp className="size-3.5" />
        </Button>
        <Button variant="ghost" size="icon-sm" className={cn("press size-7", state === "why" && "bg-well")} aria-label="Not helpful"
          aria-expanded={state === "why"} onClick={() => setState(state === "why" ? "ask" : "why")}>
          <ThumbsDown className="size-3.5" />
        </Button>
      </div>
      {state === "why" && (
        <div className="max-w-[60ch] space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {REASONS.map(([r, label]) => (
              <button key={r} type="button" aria-pressed={reason === r} onClick={() => setReason(r)}
                className={cn("press rounded-[3px] border px-2 py-1 font-mono text-[12px]",
                  reason === r ? "border-blue bg-blue-soft text-foreground" : "text-ink-2 hover:border-ink-3")}>
                {label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500}
              placeholder="What was wrong or missing? (optional)" className="text-[13px]" aria-label="Comment" />
            <Button size="sm" className="press" disabled={!reason} onClick={() => void send("down", reason ?? undefined)}>Send</Button>
          </div>
        </div>
      )}
    </div>
  )
}

import { useEffect, useState } from "react"
import { Trash2, Users } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import {
  getDocumentAccess, messageOf, removeDocument, setDocumentAccess, type DocumentAccess,
} from "@/lib/api"
import { fmt, useAtlas } from "@/lib/store"
import { cn } from "@/lib/utils"

/**
 * Who may read one source, and taking it out of the sheet (E2.3).
 *
 * Opened from a source row in the corpus pane, for editors only; the server
 * checks that on every call. It reads the source's readers first, so what is
 * offered is what the server holds, and re-reads the source list after any
 * change so a removed source leaves the pane at once.
 */
export function DocumentDialog() {
  const { documentOpen: source, sheet, set, loadSources } = useAtlas()
  const [view, setView] = useState<DocumentAccess | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [everyone, setEveryone] = useState(true)
  const [groups, setGroups] = useState<string[]>([])
  const [people, setPeople] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!source) return
    setView(null); setFailed(null)
    getDocumentAccess(sheet, source).then((v) => {
      setView(v); setEveryone(v.everyone); setGroups(v.groups); setPeople(v.people.join("\n"))
    }).catch((e) => setFailed(messageOf(e)))
  }, [source, sheet])

  const close = () => set({ documentOpen: null })
  const emails = people.split(/[\s,;]+/).map((e) => e.trim()).filter(Boolean)
  const nobody = !everyone && groups.length === 0 && emails.length === 0

  const save = async () => {
    if (!source || nobody) return
    setBusy(true)
    try {
      const r = await setDocumentAccess(sheet, source, everyone, everyone ? [] : groups, everyone ? [] : emails)
      toast.success(`Readers saved for ${source}`, { description: describe(r) })
      void loadSources()
      close()
    } catch (e) {
      toast.error("Readers not saved.", { description: messageOf(e) })
    } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!source || !confirm(`Remove ${source} from ${sheet}? Answers stop using it from the next question.`)) return
    setBusy(true)
    try {
      const r = await removeDocument(sheet, source)
      toast.success(`Removed ${source}`, { description: `${fmt(r.passages_removed)} refs taken out of ${sheet}` })
      void loadSources()
      close()
    } catch (e) {
      toast.error("Source not removed.", { description: messageOf(e) })
    } finally { setBusy(false) }
  }

  return (
    <Dialog open={source !== null} onOpenChange={(o) => { if (!o) close() }}>
      <DialogContent className="max-h-[90dvh] grid-cols-[minmax(0,1fr)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-display text-[22px] font-semibold">Who can read this source</DialogTitle>
          <DialogDescription className="truncate font-mono text-[13px]" title={source ?? ""}>{source}</DialogDescription>
        </DialogHeader>

        {failed ? (
          <p role="alert" className="border-l-[3px] border-bad bg-bad-soft px-3 py-2 font-mono text-[13px]">{failed}</p>
        ) : !view ? (
          <p className="label normal-case tracking-normal">Reading who can see it…</p>
        ) : (
          <div className="space-y-6">
            <section className="space-y-3">
              <div role="radiogroup" aria-label="Readers" className="grid gap-1.5">
                <Choice on={everyone} onPick={() => setEveryone(true)} title="Everyone on this sheet"
                  hint="Anyone with a role on the sheet can get answers from it." />
                <Choice on={!everyone} onPick={() => setEveryone(false)} title="Only the groups and people below"
                  hint="Everyone else gets answers as if this source were not here." />
              </div>

              {!everyone && (
                <div className="space-y-3 rounded-md border bg-card p-3">
                  <div className="space-y-1.5">
                    <div className="label">Groups</div>
                    {view.choices.length === 0 ? (
                      <p className="font-mono text-[12px] text-ink-3">No groups yet. An organisation admin adds them under Members.</p>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {view.choices.map((g) => (
                          <GroupToggle key={g} name={g} on={groups.includes(g)}
                            onToggle={() => setGroups(groups.includes(g) ? groups.filter((x) => x !== g) : [...groups, g])} />
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <label className="label" htmlFor="doc-people">People</label>
                    <Textarea id="doc-people" value={people} onChange={(e) => setPeople(e.target.value)} rows={2}
                      placeholder="name@company.com" spellCheck={false} autoComplete="off"
                      className="min-h-0 font-mono text-[13px]" />
                    <p className="font-mono text-[11px] text-ink-3">Email addresses in your organisation, one per line.</p>
                  </div>
                  {view.others > 0 && (
                    <p className="border-l-[3px] border-warn bg-warn-soft px-2.5 py-1.5 font-mono text-[12px] text-ink-2">
                      {view.others === 1 ? "One reader no longer exists" : `${view.others} readers no longer exist`} (a deleted group, or someone who left).
                      Saving drops {view.others === 1 ? "it" : "them"}.
                    </p>
                  )}
                </div>
              )}

              <div className="flex items-center justify-end gap-3">
                {nobody && <span className="font-mono text-[11px] text-ink-3">Choose at least one group or person.</span>}
                <Button className="press" disabled={busy || nobody} onClick={() => void save()}>Save readers</Button>
              </div>
            </section>

            <section className="space-y-2">
              <h3 className="label border-b pb-1">Remove from sheet</h3>
              <div className="flex items-start gap-3">
                <p className="min-w-0 flex-1 text-[14px] leading-snug text-ink-2">
                  Takes its {fmt(view.passages)} refs out of the sheet. Answers stop using it from the next question;
                  upload it again to bring it back.
                </p>
                <Button variant="outline" className="press shrink-0 gap-1.5 border-bad text-bad hover:bg-bad-soft hover:text-bad"
                  disabled={busy} onClick={() => void remove()}>
                  <Trash2 className="size-3.5" /> Remove
                </Button>
              </div>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function describe(r: DocumentAccess): string {
  if (r.everyone) return "Everyone on the sheet"
  const who = [...r.groups.map((g) => `group ${g}`), ...r.people]
  return `Only ${who.join(", ")}`
}

function Choice({ on, onPick, title, hint }: { on: boolean; onPick: () => void; title: string; hint: string }) {
  return (
    <button type="button" role="radio" aria-checked={on} onClick={onPick}
      className={cn(
        "press flex items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors",
        on ? "border-blue bg-blue-soft" : "border-border hover:border-ink-3",
      )}>
      <span className={cn("mt-[3px] grid size-3.5 shrink-0 place-items-center rounded-full border",
        on ? "border-blue" : "border-ink-3")}>
        {on && <span className="size-1.5 rounded-full bg-blue" />}
      </span>
      <span className="min-w-0">
        <span className="block font-mono text-[13px]">{title}</span>
        <span className="block text-[13px] leading-snug text-ink-2">{hint}</span>
      </span>
    </button>
  )
}

/** A group, pressed in or out. Also used on the Members page. */
export function GroupToggle({ name, on, onToggle }: { name: string; on: boolean; onToggle: () => void }) {
  return (
    <button type="button" aria-pressed={on} onClick={onToggle}
      className={cn(
        "press inline-flex items-center gap-1 rounded-[3px] border px-2 py-1 font-mono text-[12px] transition-colors",
        on ? "border-blue bg-blue-soft text-blue" : "border-border text-ink-2 hover:border-ink-3",
      )}>
      <Users className="size-3" />{name}
    </button>
  )
}

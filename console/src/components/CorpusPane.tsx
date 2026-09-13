import { useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { FileText, FolderInput, PanelLeftClose, PanelLeftOpen } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { postIngest } from "@/lib/api"
import { fmt, useAtlas } from "@/lib/store"
import { cn } from "@/lib/utils"

const EASE = [0.23, 1, 0.32, 1] as const

export function CorpusPane({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { sheet, sheets, sources, sourcesLoading, setSheet, loadSources } = useAtlas()
  const [path, setPath] = useState("")
  const [busy, setBusy] = useState(false)

  const ingest = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!path.trim() || busy) return
    setBusy(true)
    const id = toast.loading(`Indexing ${path}…`)
    try {
      const r = await postIngest(path.trim(), sheet)
      toast.success(`Indexed ${fmt(r.documents_processed)} sources, ${fmt(r.chunks_indexed)} refs`, {
        id, description: `${fmt(r.documents_skipped)} unchanged · ${r.duration_seconds.toFixed(1)} s`,
      })
      void loadSources()
    } catch (err) {
      toast.error("Ingest failed", { id, description: err instanceof Error ? err.message : String(err) })
    } finally { setBusy(false) }
  }

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 48 : 256 }}
      transition={{ duration: 0.26, ease: EASE }}
      className="relative flex h-full shrink-0 flex-col overflow-hidden border-r bg-sidebar"
    >
      <div className={cn("flex h-10 shrink-0 items-center border-b px-2", collapsed ? "justify-center" : "justify-between pl-4")}>
        {!collapsed && <span className="label">Corpus</span>}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="press" onClick={onToggle} aria-label={collapsed ? "Expand corpus" : "Collapse corpus"}>
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">{collapsed ? "Show corpus" : "Hide corpus"} <kbd className="ml-1 font-mono text-[10px]">[</kbd></TooltipContent>
        </Tooltip>
      </div>

      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            key="body"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.16 }}
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="space-y-1.5 px-4 pt-3">
              <label className="label" htmlFor="sheet">Sheet</label>
              <Select value={sheet} onValueChange={setSheet}>
                <SelectTrigger id="sheet" className="w-full font-mono text-[13px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {sheets.map((s) => <SelectItem key={s} value={s} className="font-mono text-[13px]">{s}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4">
              <ul className="mt-3 flex flex-col">
                {sourcesLoading ? (
                  Array.from({ length: 6 }).map((_, i) => (
                    <li key={i} className="flex items-center justify-between gap-2 border-b border-border/60 py-2">
                      <Skeleton className="h-3 w-[70%]" /><Skeleton className="h-3 w-6" />
                    </li>
                  ))
                ) : sources.length === 0 ? (
                  <li className="label mt-2 normal-case tracking-normal leading-relaxed">
                    No sources on this sheet.<br />
                    <code className="mt-1 inline-block rounded-sm border bg-well px-1.5 py-0.5 text-[11px]">make ingest</code>
                  </li>
                ) : (
                  sources.map((s, i) => (
                    <motion.li
                      key={s.source}
                      initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.22, ease: EASE, delay: Math.min(i, 12) * 0.025 }}
                      className="group flex items-center gap-2 border-b border-border/60 py-1.5 font-mono text-[12px] text-ink-2"
                      title={s.source}
                    >
                      <FileText className="size-3 shrink-0 text-ink-3 transition-colors group-hover:text-blue" />
                      <span className="min-w-0 flex-1 truncate">{s.source}</span>
                      <span className="tabular text-ink-3">{fmt(s.chunks)}</span>
                    </motion.li>
                  ))
                )}
              </ul>
            </div>

            <form onSubmit={ingest} className="border-t px-4 py-3">
              <div className="label mb-2">Ingest</div>
              <div className="flex gap-1.5">
                <Input value={path} onChange={(e) => setPath(e.target.value)} placeholder="data/corpus/fastapi" className="font-mono text-[12px]" aria-label="Path to ingest" />
                <Button type="submit" size="sm" variant="outline" disabled={busy || !path.trim()} className="press font-mono text-[11px] uppercase tracking-wider">
                  <FolderInput className="size-3.5" />
                </Button>
              </div>
              <div className="relative mt-3 h-1 overflow-hidden rounded-[1px] bg-well">
                {busy && <i className="absolute inset-y-0 w-1/3 bg-good animate-sweep" />}
              </div>
            </form>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.aside>
  )
}

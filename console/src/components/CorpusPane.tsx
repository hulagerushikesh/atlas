import { useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import { FileText, FolderInput, PanelLeftClose, PanelLeftOpen, Plus, TriangleAlert, Upload } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { postIngest, postUpload } from "@/lib/api"
import { fmt, useAtlas } from "@/lib/store"
import { cn } from "@/lib/utils"

const EASE = [0.23, 1, 0.32, 1] as const

export function CorpusPane({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { sheet, sheets, sources, sourcesLoading, indexWarning, setSheet, addSheet, loadSources } = useAtlas()
  const [path, setPath] = useState("")
  const [busy, setBusy] = useState(false)
  const [newSheet, setNewSheet] = useState("")
  const [naming, setNaming] = useState(false)
  const [dragging, setDragging] = useState(false)
  const picker = useRef<HTMLInputElement>(null)

  const create = (e: React.FormEvent) => {
    e.preventDefault()
    const name = newSheet.trim()
    if (!name) return
    addSheet(name)
    setNewSheet("")
    setNaming(false)
    toast.success(`Corpus "${name}" selected`, {
      description: "It exists once you add the first document.",
    })
  }

  const upload = async (files: File[]) => {
    if (!files.length || busy) return
    setBusy(true)
    const id = toast.loading(`Uploading ${files.length} file${files.length > 1 ? "s" : ""} to ${sheet}…`)
    try {
      const r = await postUpload(files, sheet)
      // Both halves, always. A toast that reports only the successes is how a
      // corpus ends up quietly short of what you thought you gave it.
      const refused = r.rejected.length
        ? ` · ${r.rejected.length} refused: ${r.rejected.map((x) => `${x.filename} (${x.reason})`).join(", ")}`
        : ""
      const show = refused ? toast.warning : toast.success
      show(`Indexed ${fmt(r.documents_processed)} of ${fmt(files.length)} into ${r.namespace}`, {
        id,
        description: `${fmt(r.chunks_indexed)} refs · ${r.duration_seconds.toFixed(1)} s${refused}`,
        duration: refused ? 12000 : 5000,
      })
      void loadSources()
    } catch (err) {
      toast.error("Upload failed", { id, description: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
      if (picker.current) picker.current.value = ""
    }
  }

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
              <div className="flex items-center justify-between">
                <label className="label" htmlFor="sheet">Sheet</label>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon-sm" className="press -mr-1 size-6" onClick={() => setNaming((v) => !v)} aria-label="New corpus">
                      <Plus className="size-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="right">New corpus</TooltipContent>
                </Tooltip>
              </div>
              <Select value={sheet} onValueChange={setSheet}>
                <SelectTrigger id="sheet" className="w-full font-mono text-[13px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {sheets.map((s) => <SelectItem key={s} value={s} className="font-mono text-[13px]">{s}</SelectItem>)}
                </SelectContent>
              </Select>
              <AnimatePresence initial={false}>
                {naming && (
                  <motion.form
                    key="new-sheet"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.18, ease: EASE }}
                    onSubmit={create}
                    className="overflow-hidden"
                  >
                    <div className="flex gap-1.5 pt-1.5">
                      <Input
                        value={newSheet}
                        onChange={(e) => setNewSheet(e.target.value)}
                        placeholder="my-notes"
                        autoFocus
                        className="font-mono text-[12px]"
                        aria-label="New corpus name"
                      />
                      <Button type="submit" size="sm" variant="outline" disabled={!newSheet.trim()} className="press font-mono text-[11px]">
                        Add
                      </Button>
                    </div>
                  </motion.form>
                )}
              </AnimatePresence>
            </div>

            <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4">
              {/* The list is the keyword index's. When it disagrees with the
                  vector store, say so here rather than letting these rows
                  read as documents a query can reach. */}
              {!sourcesLoading && indexWarning && (
                <div className="mt-3 flex gap-2 rounded-sm border border-warn bg-warn-soft px-2.5 py-2 text-[11px] leading-relaxed text-ink-2">
                  <TriangleAlert className="mt-px size-3 shrink-0 text-warn" />
                  <span>{indexWarning}</span>
                </div>
              )}
              <ul className="mt-3 flex flex-col">
                {sourcesLoading ? (
                  Array.from({ length: 6 }).map((_, i) => (
                    <li key={i} className="flex items-center justify-between gap-2 border-b border-border/60 py-2">
                      <Skeleton className="h-3 w-[70%]" /><Skeleton className="h-3 w-6" />
                    </li>
                  ))
                ) : sources.length === 0 ? (
                  <li className="label mt-2 normal-case tracking-normal leading-relaxed">
                    No documents on this sheet yet.<br />
                    <span className="text-ink-3">Add some below.</span>
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

            <div className="border-t px-4 py-3">
              <div className="label mb-2">Add documents</div>

              <input
                ref={picker}
                type="file"
                multiple
                className="sr-only"
                aria-label="Choose documents to upload"
                onChange={(e) => void upload(Array.from(e.target.files ?? []))}
              />

              <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragging(false)
                  void upload(Array.from(e.dataTransfer.files))
                }}
                onClick={() => picker.current?.click()}
                className={cn(
                  "flex cursor-pointer flex-col items-center gap-1 rounded-sm border border-dashed px-3 py-4 text-center transition-colors",
                  dragging ? "border-blue bg-blue/5" : "border-border hover:border-ink-3",
                  busy && "pointer-events-none opacity-60",
                )}
              >
                <Upload className="size-4 text-ink-3" />
                <span className="label normal-case tracking-normal text-[11px] leading-snug">
                  Drop files or click to choose
                </span>
                <span className="font-mono text-[10px] text-ink-3">md · txt · pdf · html</span>
              </div>

              <details className="mt-3">
                <summary className="label cursor-pointer select-none text-[10px]">Server path</summary>
                <form onSubmit={ingest} className="mt-2">
                  <div className="flex gap-1.5">
                    <Input value={path} onChange={(e) => setPath(e.target.value)} placeholder="data/corpus/fastapi" className="font-mono text-[12px]" aria-label="Path to ingest" />
                    <Button type="submit" size="sm" variant="outline" disabled={busy || !path.trim()} className="press font-mono text-[11px] uppercase tracking-wider">
                      <FolderInput className="size-3.5" />
                    </Button>
                  </div>
                  <p className="label mt-1.5 normal-case tracking-normal text-[10px] leading-snug text-ink-3">
                    A path on the machine running the API, under its ingest root — not on this computer.
                  </p>
                </form>
              </details>

              <div className="relative mt-3 h-1 overflow-hidden rounded-[1px] bg-well">
                {busy && <i className="absolute inset-y-0 w-1/3 bg-good animate-sweep" />}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.aside>
  )
}

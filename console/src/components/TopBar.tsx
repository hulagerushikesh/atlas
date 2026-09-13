import { Command, Map, Settings2, SunMoon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useAtlas, fmt } from "@/lib/store"
import { cn } from "@/lib/utils"

const HEALTH: Record<string, { dot: string; label: string }> = {
  ok: { dot: "bg-good", label: "ok" },
  degraded: { dot: "bg-warn", label: "degraded" },
  down: { dot: "bg-bad", label: "down" },
  unreachable: { dot: "bg-bad", label: "unreachable" },
  checking: { dot: "bg-ink-3 animate-pulse-soft", label: "checking" },
}

export function TopBar() {
  const { sheet, totals, health, keyOpen, theme, set, setTheme } = useAtlas()
  const h = HEALTH[health] ?? HEALTH.checking
  const cycleTheme = () => setTheme(theme === "" ? "dark" : theme === "dark" ? "light" : "")

  return (
    <header className="flex h-11 shrink-0 items-center gap-4 border-b bg-card px-4">
      <div className="font-display text-xl font-bold uppercase tracking-[0.06em]">Atlas</div>

      <div className="label hidden min-w-0 truncate tabular sm:block">
        Sheet <b className="font-medium text-foreground">{sheet}</b>
        {totals && <> · <b className="font-medium text-foreground">{fmt(totals.sources)}</b> sources · <b className="font-medium text-foreground">{fmt(totals.chunks)}</b> refs</>}
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="label mr-1 inline-flex items-center gap-2 tabular">
              <i className={cn("inline-block size-2 rounded-[2px]", h.dot)} />
              <span className="hidden sm:inline">{h.label}</span>
            </span>
          </TooltipTrigger>
          <TooltipContent>API health: {h.label}</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="sm" className="press gap-1.5 font-mono text-[11px] uppercase tracking-wider" onClick={() => set({ paletteOpen: true })}>
              <Command className="size-3.5" /> <span className="hidden md:inline">Palette</span> <Kbd className="hidden md:inline-flex">⌘K</Kbd>
            </Button>
          </TooltipTrigger>
          <TooltipContent>Command palette</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant={keyOpen ? "secondary" : "ghost"} size="icon-sm" className="press" aria-pressed={keyOpen} onClick={() => set({ keyOpen: !keyOpen })}>
              <Map className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Key — what each colour means</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="press" onClick={cycleTheme}>
              <SunMoon className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Theme: {theme || "system"}</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="press" onClick={() => set({ settingsOpen: true })}>
              <Settings2 className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Settings</TooltipContent>
        </Tooltip>
      </div>
    </header>
  )
}

export function KeyStrip() {
  const open = useAtlas((s) => s.keyOpen)
  return (
    <div
      className="grid shrink-0 overflow-hidden border-b bg-card transition-[grid-template-rows] duration-200 ease-[var(--ease-out-strong)]"
      style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      aria-hidden={!open}
    >
      <div className="min-h-0">
        <div className="label flex flex-wrap gap-x-6 gap-y-1 px-4 py-2 text-ink-2">
          <Sw c="bg-blue" t="retrieval" />
          <Sw c="bg-ochre" t="language model" />
          <Sw c="bg-good" t="supported" />
          <Sw c="bg-warn" t="mixed / weak" />
          <Sw c="bg-bad" t="unsupported" />
          <Sw c="border border-dashed border-ink-3" t="not reached" />
        </div>
      </div>
    </div>
  )
}

function Sw({ c, t }: { c: string; t: string }) {
  return <span className="inline-flex items-center gap-2"><i className={cn("inline-block size-2.5 rounded-[2px]", c)} />{t}</span>
}

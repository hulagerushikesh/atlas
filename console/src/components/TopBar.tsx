import { Bot, Command, KeyRound, Layers, LogIn, LogOut, Map, Settings2, SunMoon, TriangleAlert, UserRound, Users } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { signOut } from "@/lib/api"
import { useAtlas, fmt } from "@/lib/store"
import { SCORES } from "@/lib/glossary"
import { cn } from "@/lib/utils"

const HEALTH: Record<string, { dot: string; label: string }> = {
  ok: { dot: "bg-good", label: "ok" },
  degraded: { dot: "bg-warn", label: "degraded" },
  down: { dot: "bg-bad", label: "down" },
  unreachable: { dot: "bg-bad", label: "unreachable" },
  checking: { dot: "bg-ink-3 animate-pulse-soft", label: "checking" },
}

export function TopBar() {
  const { sheet, totals, indexWarning, health, keyOpen, evidenceOpen, theme, set, setTheme } = useAtlas()
  const h = HEALTH[health] ?? HEALTH.checking
  const cycleTheme = () => setTheme(theme === "" ? "dark" : theme === "dark" ? "light" : "")

  return (
    <header className="flex h-11 shrink-0 items-center gap-4 border-b bg-card px-4">
      <div className="font-display text-xl font-bold uppercase tracking-[0.06em]">Atlas</div>

      <div className="label hidden min-w-0 truncate tabular sm:block">
        Sheet <b className="font-medium text-foreground">{sheet}</b>
        {totals && <> · <b className="font-medium text-foreground">{fmt(totals.sources)}</b> sources · <b className="font-medium text-foreground">{fmt(totals.chunks)}</b> refs</>}
        {indexWarning && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="ml-1.5 inline-flex align-[-2px] text-warn" aria-label="Index mismatch">
                <TriangleAlert className="size-3" />
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">{indexWarning}</TooltipContent>
          </Tooltip>
        )}
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

        {/*
          Below xl the evidence pane is a drawer, and until now the only ways
          in were tapping the strength badge or the ⌘K palette — the first is
          a button that does not look like one, and the second needs a
          keyboard. A failed run has no badge at all, so on a phone its
          references, and the export button that sits with them, could not be
          reached. Hidden at xl, where the pane is already docked.
        */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant={evidenceOpen ? "secondary" : "ghost"} size="icon-sm" className="press xl:hidden" aria-pressed={evidenceOpen} aria-label="Evidence" onClick={() => set({ evidenceOpen: !evidenceOpen })}>
              <Layers className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Evidence — the references behind the answer</TooltipContent>
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

        <Account />

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="press" aria-label="API keys" onClick={() => set({ accessOpen: true })}>
              <KeyRound className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>API keys — who can query this Atlas</TooltipContent>
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

/**
 * Who is signed in, or the way to sign in. Text, not an avatar (DESIGN §9):
 * the address is what tells a person which account they are using.
 */
function Account() {
  const { me, authConfig, set, boot } = useAtlas()
  if (!me?.user) {
    if (!authConfig?.enabled) return null
    return (
      <Button variant="ghost" size="sm" className="press gap-1.5 font-mono text-[11px] uppercase tracking-wider" onClick={() => set({ signInOpen: true })}>
        <LogIn className="size-3.5" /> <span className="hidden sm:inline">Sign in</span>
      </Button>
    )
  }
  const leave = async () => {
    try { await signOut() } catch { /* the cookie is cleared server-side or already gone */ }
    set({ me: null })
    toast.success("Signed out")
    void boot()
  }
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="press max-w-56 gap-1.5 font-mono text-[11px] normal-case" aria-label={`Signed in as ${me.user.email}`}>
          <UserRound className="size-3.5 shrink-0" /> <span className="hidden truncate lg:inline">{me.user.email}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 space-y-3 p-3">
        <div className="space-y-0.5 font-mono text-[13px]">
          <div className="truncate">{me.user.email}</div>
          <div className="label normal-case tracking-normal">
            {me.org?.name}{me.org_admin ? " · organisation admin" : ` · ${me.workspaces.length} sheet${me.workspaces.length === 1 ? "" : "s"}`}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          {me.org_admin && (
            <Button variant="ghost" size="sm" className="press justify-start gap-2" onClick={() => set({ membersOpen: true })}>
              <Users className="size-3.5" /> Members
            </Button>
          )}
          <Button variant="ghost" size="sm" className="press justify-start gap-2" onClick={() => set({ assistantsOpen: true })}>
            <Bot className="size-3.5" /> AI assistants
          </Button>
          <Button variant="ghost" size="sm" className="press justify-start gap-2" onClick={() => void leave()}>
            <LogOut className="size-3.5" /> Sign out
          </Button>
        </div>
      </PopoverContent>
    </Popover>
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
        <div className="px-4 py-2">
          <div className="label flex flex-wrap gap-x-6 gap-y-1 text-ink-2">
            <Sw c="bg-blue" t="retrieval" />
            <Sw c="bg-ochre" t="language model" />
            <Sw c="bg-good" t="supported" />
            <Sw c="bg-warn" t="mixed / weak" />
            <Sw c="bg-bad" t="unsupported" />
            <Sw c="border border-dashed border-ink-3" t="not reached" />
          </div>
          {/*
            The second half of the key. The colours were explained here from
            the start; the four numbers on every evidence card never were,
            and they are the part a reader actually stops on. Short gloss
            only — the full note is in each card's own tooltip.
          */}
          <div className="label mt-1.5 flex flex-wrap gap-x-5 gap-y-1 border-t pt-1.5 normal-case tracking-normal text-ink-3">
            <span className="uppercase tracking-wider">Elevation</span>
            {(["dense", "bm25", "rrf", "rerank"] as const).map((k) => (
              <span key={k}>
                <b className="font-medium text-ink-2">{SCORES[k].label}</b> — {SCORES[k].technical.toLowerCase()}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function Sw({ c, t }: { c: string; t: string }) {
  return <span className="inline-flex items-center gap-2"><i className={cn("inline-block size-2.5 rounded-[2px]", c)} />{t}</span>
}

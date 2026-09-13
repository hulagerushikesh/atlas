import { useEffect } from "react"
import { Layers, Map, Moon, PanelLeft, Route, Settings2, Sun, SunMoon, TableProperties } from "lucide-react"
import {
  Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator, CommandShortcut,
} from "@/components/ui/command"
import { useAtlas } from "@/lib/store"

/**
 * ⌘K palette. Opened by keyboard hundreds of times a day, so it does not
 * animate — Raycast's rule. The dialog's default open transition is
 * suppressed via data-[state] overrides below.
 */
export function CommandMenu({ onToggleCorpus }: { onToggleCorpus: () => void }) {
  const { paletteOpen, set, sheets, sheet, setSheet, setTheme, surveyOpen, keyOpen } = useAtlas()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); set({ paletteOpen: !paletteOpen }) }
      else if (e.key === "[" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) onToggleCorpus()
      else if (e.key === "Escape") set({ evidenceOpen: false })
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [paletteOpen, set, onToggleCorpus])

  const run = (fn: () => void) => () => { fn(); set({ paletteOpen: false }) }

  return (
    <CommandDialog open={paletteOpen} onOpenChange={(o) => set({ paletteOpen: o })} className="font-mono text-[13px] data-[state=closed]:animate-none data-[state=open]:animate-none">
      <Command>
      <CommandInput placeholder="Switch sheet, toggle panes, change theme…" />
      <CommandList>
        <CommandEmpty>Nothing matches.</CommandEmpty>
        <CommandGroup heading="Sheets">
          {sheets.map((s) => (
            <CommandItem key={s} value={`sheet ${s}`} onSelect={run(() => setSheet(s))}>
              <Map className="size-4" /> {s}{s === sheet && <CommandShortcut>current</CommandShortcut>}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Panes">
          <CommandItem onSelect={run(onToggleCorpus)}><PanelLeft className="size-4" /> Toggle corpus<CommandShortcut>[</CommandShortcut></CommandItem>
          <CommandItem onSelect={run(() => set({ evidenceOpen: true }))}><Layers className="size-4" /> Show evidence</CommandItem>
          <CommandItem onSelect={run(() => set({ surveyOpen: !surveyOpen }))}><TableProperties className="size-4" /> {surveyOpen ? "Collapse" : "Expand"} survey</CommandItem>
          <CommandItem onSelect={run(() => set({ keyOpen: !keyOpen }))}><Route className="size-4" /> {keyOpen ? "Hide" : "Show"} key</CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Theme">
          <CommandItem onSelect={run(() => setTheme(""))}><SunMoon className="size-4" /> System</CommandItem>
          <CommandItem onSelect={run(() => setTheme("light"))}><Sun className="size-4" /> Light</CommandItem>
          <CommandItem onSelect={run(() => setTheme("dark"))}><Moon className="size-4" /> Dark</CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Atlas">
          <CommandItem onSelect={run(() => set({ settingsOpen: true }))}><Settings2 className="size-4" /> Settings</CommandItem>
        </CommandGroup>
      </CommandList>
      </Command>
    </CommandDialog>
  )
}

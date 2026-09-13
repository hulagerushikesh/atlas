import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { store as ls } from "@/lib/api"
import { useAtlas } from "@/lib/store"

export function SettingsDialog() {
  const { settingsOpen, set, theme, setTheme, boot } = useAtlas()
  const [key, setKey] = useState("")
  const [base, setBase] = useState("")
  const [t, setT] = useState<"" | "light" | "dark">(theme)

  useEffect(() => {
    if (settingsOpen) { setKey(ls.get("atlas_api_key")); setBase(ls.get("atlas_api_base")); setT(theme) }
  }, [settingsOpen, theme])

  const save = () => {
    ls.set("atlas_api_key", key.trim())
    ls.set("atlas_api_base", base.trim())
    setTheme(t)
    set({ settingsOpen: false })
    toast.success("Settings saved")
    void boot()
  }

  return (
    <Dialog open={settingsOpen} onOpenChange={(o) => set({ settingsOpen: o })}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display text-[22px] font-semibold">Settings</DialogTitle>
          <DialogDescription>Stored in this browser only.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="label" htmlFor="api-key">API key</label>
            <Input id="api-key" value={key} onChange={(e) => setKey(e.target.value)} placeholder="atlas_…" autoComplete="off" spellCheck={false} className="font-mono text-[13px]" />
            <p className="label normal-case tracking-normal">Needed for /query and /ingest. Create one with <code className="rounded-sm border bg-well px-1">make key</code>.</p>
          </div>
          <div className="space-y-1.5">
            <label className="label" htmlFor="api-base">API base</label>
            <Input id="api-base" value={base} onChange={(e) => setBase(e.target.value)} placeholder="same origin" className="font-mono text-[13px]" />
          </div>
          <div className="space-y-1.5">
            <label className="label" htmlFor="theme">Theme</label>
            <Select value={t || "system"} onValueChange={(v) => setT(v === "system" ? "" : (v as "light" | "dark"))}>
              <SelectTrigger id="theme" className="w-full font-mono text-[13px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="system">System</SelectItem>
                <SelectItem value="light">Light</SelectItem>
                <SelectItem value="dark">Dark</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" className="press" onClick={() => set({ settingsOpen: false })}>Cancel</Button>
          <Button className="press" onClick={save}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

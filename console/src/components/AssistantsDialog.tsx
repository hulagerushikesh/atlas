import { useEffect, useState } from "react"
import { Copy, KeyRound, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { createMyKey, getMyKeys, mcpUrl, messageOf, revokeMyKey, type PersonalKey } from "@/lib/api"
import { useAtlas } from "@/lib/store"

const copy = (text: string, what: string) =>
  navigator.clipboard.writeText(text).then(() => toast.success(`Copied ${what}`), () => toast.error("Copy failed"))

function Snippet({ title, text, note }: { title: string; text: string; note?: string }) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex items-center justify-between">
        <span className="label">{title}</span>
        <Button variant="ghost" size="icon-sm" className="press size-6" aria-label={`Copy ${title}`} onClick={() => void copy(text, title)}>
          <Copy className="size-3.5" />
        </Button>
      </div>
      <pre className="scrollbar-thin overflow-x-auto rounded-sm border bg-well px-2.5 py-2 font-mono text-[11px] leading-relaxed text-ink-2">{text}</pre>
      {note && <p className="label normal-case tracking-normal text-[11px] leading-snug">{note}</p>}
    </div>
  )
}

/**
 * Personal keys for AI assistants over MCP (E4). A key acts as the person who
 * made it, so an assistant finds exactly what they can read here, Drive
 * sharing included. The key is shown once, with the setup for each client.
 */
export function AssistantsDialog() {
  const { assistantsOpen, set } = useAtlas()
  const [keys, setKeys] = useState<PersonalKey[] | null>(null)
  const [name, setName] = useState("")
  const [made, setMade] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const url = mcpUrl()

  const load = () => getMyKeys().then((r) => setKeys(r.keys)).catch((e) => toast.error("Keys not loaded", { description: messageOf(e) }))
  useEffect(() => {
    if (!assistantsOpen) return
    setMade(null); setName(""); void load()
  }, [assistantsOpen])

  const make = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    try {
      const r = await createMyKey(name.trim())
      setMade(r.key); setName(""); void load()
    } catch (err) { toast.error("Key not made", { description: messageOf(err) }) } finally { setBusy(false) }
  }
  const revoke = async (k: PersonalKey) => {
    if (!confirm(`Revoke "${k.name}"? Any assistant using it stops reaching Atlas at once.`)) return
    try { await revokeMyKey(k.key_id); toast.success(`Revoked ${k.name}`); void load() } catch (err) {
      toast.error("Not revoked", { description: messageOf(err) })
    }
  }

  return (
    <Dialog open={assistantsOpen} onOpenChange={(o) => set({ assistantsOpen: o })}>
      <DialogContent className="max-h-[90vh] grid-cols-[minmax(0,1fr)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-display text-[22px] font-semibold">AI assistants</DialogTitle>
          <DialogDescription>
            Let Claude, Copilot or another assistant search the sheets you can read. It finds only what you can
            find here, Drive sharing included, and writes its answer from the passages Atlas returns.
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-4">
          <Snippet title="Server address" text={url} note="Streamable HTTP. Every assistant needs this and a key." />

          {made ? (
            <div className="space-y-3 rounded-sm border border-good bg-good-soft p-3">
              <p className="text-[13px] leading-relaxed text-ink-1">
                Your key is below. Copy it now: Atlas shows it only once. Anyone holding it can search what you can read.
              </p>
              <Snippet title="Key" text={made} />
              <Snippet title="Claude Code" text={`claude mcp add --transport http atlas ${url} --header "Authorization: Bearer ${made}"`} />
              <Snippet title="Cursor, VS Code and other JSON settings" text={JSON.stringify({ mcpServers: { atlas: { url, headers: { Authorization: `Bearer ${made}` } } } }, null, 2)} />
              <Snippet title="Copilot Studio" text={`Server URL: ${url}\nAuthentication: API key · Header · X-API-Key\nKey: ${made}`}
                note="In your agent: Tools → Add a tool → Model Context Protocol." />
            </div>
          ) : (
            <form onSubmit={make} className="space-y-1.5">
              <label className="label" htmlFor="key-name">New key</label>
              <div className="flex gap-2">
                <Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Where it will live, e.g. Claude Code on my laptop"
                  autoComplete="off" className="text-[13px]" />
                <Button type="submit" className="press" disabled={busy || !name.trim()}><KeyRound className="size-3.5" />Make key</Button>
              </div>
            </form>
          )}

          <div className="space-y-1.5">
            <div className="label">Your keys · {keys?.length ?? "…"}</div>
            {keys?.length === 0 && <p className="label normal-case tracking-normal text-[12px]">None yet.</p>}
            <ul className="flex flex-col">
              {keys?.map((k) => (
                <li key={k.key_id} className="flex items-center gap-2 border-b border-border/60 py-1.5 font-mono text-[12px] text-ink-2">
                  <span className="min-w-0 flex-1 truncate">{k.name}</span>
                  <span className="text-ink-3">{k.created_at ? new Date(k.created_at * 1000).toLocaleDateString() : ""}</span>
                  <Button variant="ghost" size="sm" className="press h-6 gap-1 px-1.5 text-[11px] text-bad" onClick={() => void revoke(k)}>
                    <Trash2 className="size-3" />Revoke
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

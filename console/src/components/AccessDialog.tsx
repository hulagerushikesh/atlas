import { useCallback, useEffect, useState } from "react"
import { ShieldCheck, ShieldOff } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { getKeys, setKeyActive, type KeyRecord } from "@/lib/api"
import { ApiError } from "@/lib/api"
import { failureFrom, useAtlas } from "@/lib/store"
import { cn } from "@/lib/utils"

/**
 * The API-key listing: who can query this Atlas, how much they have, and the
 * switch that stops one.
 *
 * A dialog rather than a fifth pane. DESIGN §5 fixes the console at four
 * places and this is an occasional administrative act, not a working
 * surface — the same reason Settings is a dialog.
 *
 * The admin secret is typed here and kept in the store for the tab. It is
 * deliberately not in localStorage, where the API key lives: an API key can
 * spend this Atlas's budget, the admin secret can revoke every key there is.
 */
export function AccessDialog() {
  const { accessOpen, adminSecret, set } = useAtlas()
  const [secret, setSecret] = useState("")
  const [keys, setKeys] = useState<KeyRecord[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async (withSecret: string) => {
    try {
      setKeys(await getKeys(withSecret))
      set({ adminSecret: withSecret })
    } catch (e) {
      // A wrong secret must not sit in the store looking unlocked.
      set({ adminSecret: "" })
      setKeys(null)
      const f = describe(e)
      toast.error(f.what, { description: f.why })
    }
  }, [set])

  useEffect(() => {
    if (!accessOpen) return
    setSecret("")
    if (adminSecret) void load(adminSecret)
    else setKeys(null)
  }, [accessOpen, adminSecret, load])

  const toggle = async (k: KeyRecord) => {
    setBusy(String(k.key_id))
    try {
      const next = await setKeyActive(k.key_id, !k.is_active, adminSecret)
      setKeys((cur) => cur?.map((c) => (c.key_id === next.key_id ? next : c)) ?? null)
      toast.success(next.is_active ? `Restored ${next.name}` : `Revoked ${next.name}`, {
        description: next.is_active
          ? "The key answers again from the next request."
          : "The key is refused from the next request.",
      })
    } catch (e) {
      const f = describe(e)
      toast.error(f.what, { description: f.why })
    } finally {
      setBusy(null)
    }
  }

  return (
    <Dialog open={accessOpen} onOpenChange={(o) => set({ accessOpen: o })}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="font-display text-[22px] font-semibold">API keys</DialogTitle>
          <DialogDescription>
            Who can query this Atlas, and what each key has spent. Revoking takes effect on the next request.
          </DialogDescription>
        </DialogHeader>

        {!adminSecret ? (
          <form
            className="space-y-1.5"
            onSubmit={(e) => { e.preventDefault(); if (secret.trim()) void load(secret.trim()) }}
          >
            <label className="label" htmlFor="admin-secret">Admin secret</label>
            <div className="flex gap-2">
              <Input
                id="admin-secret" type="password" value={secret} autoFocus
                onChange={(e) => setSecret(e.target.value)}
                autoComplete="off" spellCheck={false} className="font-mono text-[13px]"
              />
              <Button type="submit" className="press" disabled={!secret.trim()}>Unlock</Button>
            </div>
            <p className="label normal-case tracking-normal">
              Held in this tab only, never stored. It is <code className="rounded-sm border bg-well px-1">ADMIN_SECRET</code> on the server.
            </p>
          </form>
        ) : keys === null ? (
          <p className="label normal-case tracking-normal">Reading keys…</p>
        ) : keys.length === 0 ? (
          <p className="label normal-case tracking-normal">
            {/*
              Was `make key`, which is wrong twice: the target is
              `create-key`, and it writes to the local SQLite store, which a
              deployed server reading Firestore never looks at. This dialog is
              mostly opened against production, so it names the route that
              works wherever the server happens to be.
            */}
            No keys yet. Create one with <code className="rounded-sm border bg-well px-1">POST /keys</code>, using this same secret.
          </p>
        ) : (
          <div className="max-h-[60vh] overflow-auto">
            <table className="w-full border-collapse font-mono text-[13px] tabular">
              <thead>
                <tr className="label border-b text-left">
                  <th className="py-2 pr-3 font-normal">Name</th>
                  <th className="py-2 pr-3 font-normal">State</th>
                  <th className="hidden py-2 pr-3 text-right font-normal sm:table-cell">Rpm</th>
                  <th className="py-2 pr-3 text-right font-normal">Queries</th>
                  <th className="hidden py-2 pr-3 font-normal sm:table-cell">Last query</th>
                  <th className="py-2 font-normal" />
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={String(k.key_id)} className={cn("border-b last:border-0", !k.is_active && "opacity-60")}>
                    <td className="py-2 pr-3">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="cursor-default">{k.name || "unnamed"}</span>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-sm break-all font-mono text-[11px]">
                          {String(k.key_id)}
                        </TooltipContent>
                      </Tooltip>
                      {k.email && <div className="label normal-case tracking-normal">{k.email}</div>}
                    </td>
                    <td className="py-2 pr-3">
                      <span className={cn(
                        "inline-flex items-center rounded-[2px] border px-1.5 py-0.5 font-mono text-[11px] uppercase tracking-wider",
                        k.is_active
                          ? "border-good bg-good-soft text-good"
                          : "border-bad bg-bad-soft text-bad",
                      )}>
                        {k.is_active ? "active" : "revoked"}
                      </span>
                    </td>
                    <td className="hidden py-2 pr-3 text-right sm:table-cell">{k.rate_limit_rpm}</td>
                    <td className="py-2 pr-3 text-right">{k.total_queries}</td>
                    <td className="hidden py-2 pr-3 sm:table-cell">{when(k.last_query_at)}</td>
                    <td className="py-2 text-right">
                      <Button
                        variant="ghost" size="sm" className="press gap-1.5"
                        disabled={busy === String(k.key_id)}
                        aria-label={`${k.is_active ? "Revoke" : "Restore"} ${k.name || "unnamed key"}`}
                        onClick={() => void toggle(k)}
                      >
                        {k.is_active
                          ? <><ShieldOff className="size-3.5" /> <span className="hidden sm:inline">Revoke</span></>
                          : <><ShieldCheck className="size-3.5" /> <span className="hidden sm:inline">Restore</span></>}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

/**
 * `failureFrom` answers for the query path, where a 403 means the sheet
 * wanted an API key. Here it means the admin secret was refused, and a 404
 * means someone else revoked or removed the key since this list was read —
 * saying "add a key under Settings" for either would send the reader the
 * wrong way. Everything else it still answers for.
 */
function describe(e: unknown): { what: string; why: string } {
  if (e instanceof ApiError && e.status === 403)
    return { what: "Admin secret not accepted.", why: "It must match ADMIN_SECRET on the server." }
  if (e instanceof ApiError && e.status === 404)
    return { what: "That key is gone.", why: "It was removed from the store since this list was read." }
  const f = failureFrom(e)
  return { what: f.what, why: f.why }
}

/** Epoch seconds as the reader's local date, or "never". */
function when(ts: number | null): string {
  if (!ts) return "never"
  return new Date(ts * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
  })
}

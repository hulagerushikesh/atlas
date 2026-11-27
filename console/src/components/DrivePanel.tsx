import { useCallback, useEffect, useRef, useState } from "react"
import { FolderSync, RefreshCw, TriangleAlert, Unplug } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  ApiError, disconnectDrive, driveConnectUrl, getDrive, messageOf, setDriveFolder, syncDrive,
  type DriveStatus,
} from "@/lib/api"
import { fmt, useAtlas } from "@/lib/store"

const OUTCOME: Record<string, () => void> = {
  connected: () => toast.success("Google Drive connected", { description: "Paste a folder link to choose what this sheet keeps in step with." }),
  declined: () => toast.warning("Google Drive not connected", { description: "Consent was declined on Google's page." }),
  failed: () => toast.error("Google Drive not connected", { description: "Google did not confirm the connection. Try again." }),
}

function ago(ts: number | null | undefined): string {
  if (!ts) return "never"
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts))
  if (s < 60) return "just now"
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

/**
 * One sheet's Google Drive folder (E3): connect, choose the folder, see what
 * the last sync did, sync now, disconnect. Editors only; hidden entirely when
 * the server has Drive switched off. Readers of each synced source follow
 * Drive's sharing, re-read on every sync.
 */
export function DrivePanel() {
  const { sheet, loadSources } = useAtlas()
  const [status, setStatus] = useState<DriveStatus | null>(null)
  const [off, setOff] = useState(false)
  const [folder, setFolder] = useState("")
  const [busy, setBusy] = useState(false)
  const wasSyncing = useRef(false)

  const load = useCallback(() => getDrive(sheet).then((s) => { setStatus(s); setOff(false) }).catch((e) => {
    setStatus(null)
    setOff(e instanceof ApiError && (e.status === 503 || e.status === 404 || e.status === 403))
  }), [sheet])

  useEffect(() => { setStatus(null); void load() }, [load])

  // A sync runs in the background on the server: poll until it finishes,
  // then re-read the source list so new and removed sources show at once.
  useEffect(() => {
    if (!status?.syncing) return
    const t = setInterval(() => void load(), 3000)
    return () => clearInterval(t)
  }, [status?.syncing, load])
  useEffect(() => {
    if (wasSyncing.current && !status?.syncing) void loadSources()
    wasSyncing.current = Boolean(status?.syncing)
  }, [status?.syncing, loadSources])

  // Back from Google's consent page.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const outcome = params.get("drive")
    if (!outcome) return
    OUTCOME[outcome]?.()
    params.delete("drive"); params.delete("namespace")
    const rest = params.toString()
    window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`)
  }, [])

  if (off) return null

  const act = async (fn: () => Promise<unknown>, failure: string) => {
    setBusy(true)
    try { await fn() } catch (e) { toast.error(failure, { description: messageOf(e) }) } finally { setBusy(false) }
  }
  const choose = (e: React.FormEvent) => {
    e.preventDefault()
    if (!folder.trim()) return
    void act(async () => { setStatus(await setDriveFolder(sheet, folder.trim())); setFolder("") }, "Folder not saved.")
  }
  const sync = () => void act(async () => setStatus(await syncDrive(sheet)), "Sync not started.")
  const disconnect = () => {
    if (!confirm(`Disconnect Google Drive from ${sheet}? Every source it brought in is removed from the sheet.`)) return
    void act(async () => {
      const r = await disconnectDrive(sheet)
      toast.success("Google Drive disconnected", { description: `${fmt(r.removed)} sources removed from ${sheet}` })
      void loadSources(); void load()
    }, "Not disconnected.")
  }

  const r = status?.report ?? {}
  const notes = [
    r.skipped?.length ? { n: r.skipped.length, what: "skipped (not a Doc, PDF or text, or too big)", names: r.skipped } : null,
    r.closed?.length ? { n: r.closed.length, what: "left out: sharing hidden from you", names: r.closed } : null,
    r.failed?.length ? { n: r.failed.length, what: "could not be read; retried next sync", names: r.failed } : null,
  ].filter((x): x is { n: number; what: string; names: string[] } => x !== null)

  return (
    <section className="mt-3 border-t border-border/60 pt-3" aria-label="Google Drive">
      <div className="label mb-2 flex items-center justify-between">
        <span>Google Drive</span>
        {status?.connected && status.folder_id && (
          <span className="font-mono text-[10px] normal-case tracking-normal text-ink-3">
            {status.syncing ? "syncing…" : `checked ${ago(status.last_check ?? status.last_sync)}`}
          </span>
        )}
      </div>

      {status === null ? null : !status.connected ? (
        <>
          <Button asChild size="sm" variant="outline" className="press w-full font-mono text-[11px]">
            <a href={driveConnectUrl(sheet)}><FolderSync className="size-3.5" />Connect Google Drive</a>
          </Button>
          <p className="label mt-1.5 normal-case tracking-normal text-[10px] leading-snug text-ink-3">
            Read-only. Each source stays readable only by the people Drive shares it with.
          </p>
        </>
      ) : (
        <div className="space-y-2">
          {status.folder_id ? (
            <div className="font-mono text-[11px] leading-relaxed text-ink-2">
              <a className="text-blue underline-offset-2 hover:underline" target="_blank" rel="noreferrer"
                href={`https://drive.google.com/drive/folders/${encodeURIComponent(status.folder_id)}`}>
                {fmt(status.files)} sources from the folder
              </a>
              <span className="text-ink-3"> · synced {ago(status.last_sync)}</span>
              {status.connected_by && <div className="truncate text-ink-3" title={status.connected_by}>as {status.connected_by}</div>}
            </div>
          ) : (
            <p className="label normal-case tracking-normal text-[11px] leading-snug">
              Connected as {status.connected_by}. Choose the folder this sheet keeps in step with.
            </p>
          )}

          <form onSubmit={choose} className="flex gap-1.5">
            <Input value={folder} onChange={(e) => setFolder(e.target.value)}
              placeholder={status.folder_id ? "Another folder link" : "Drive folder link"}
              className="font-mono text-[12px]" aria-label="Google Drive folder link" />
            <Button type="submit" size="sm" variant="outline" disabled={busy || !folder.trim()} className="press font-mono text-[11px]">
              Use
            </Button>
          </form>

          {status.error && (
            <div className="flex gap-2 rounded-sm border border-warn bg-warn-soft px-2.5 py-2 text-[11px] leading-relaxed text-ink-2">
              <TriangleAlert className="mt-px size-3 shrink-0 text-warn" />
              <span>
                {/reconnect/i.test(status.error) ? (
                  <>
                    {status.error.replace(/[;.]?\s*reconnect drive\.?$/i, ".")}{" "}
                    <a className="text-blue underline underline-offset-2" href={driveConnectUrl(sheet)}>Reconnect Drive</a>
                  </>
                ) : status.error}
              </span>
            </div>
          )}
          {notes.map((x) => (
            <p key={x.what} className="font-mono text-[10px] leading-snug text-ink-3" title={x.names.join("\n")}>
              {fmt(x.n)} {x.what}
            </p>
          ))}

          <div className="flex gap-1.5">
            {status.folder_id && (
              <Button size="sm" variant="outline" className="press flex-1 font-mono text-[11px]" disabled={busy || status.syncing} onClick={sync}>
                <RefreshCw className="size-3.5" />Sync now
              </Button>
            )}
            <Button size="sm" variant="outline" className="press flex-1 border-bad font-mono text-[11px] text-bad" disabled={busy} onClick={disconnect}>
              <Unplug className="size-3.5" />Disconnect
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}

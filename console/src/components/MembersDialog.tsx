import { useCallback, useEffect, useState } from "react"
import { Copy, Pencil, ShieldOff, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import {
  createGroup, createServiceAccount, createSheet, deleteGroup, getAudit, getOrg, getSpending, getUnanswered, invite, messageOf, removeMember,
  revokeServiceAccount, setAuditRetention, setSheetLimit, updateMember, withdrawInvitation, type AuditEntry, type Grants, type Spending,
  type Unanswered, type Org, type Role,
} from "@/lib/api"
import { GroupToggle } from "@/components/DocumentDialog"
import { useAtlas } from "@/lib/store"
import { cn } from "@/lib/utils"

/**
 * One organisation's people, invitations, sheets and service accounts.
 *
 * For an organisation admin only; the server checks that on every call, this
 * dialog only hides the way in. A dialog, not a fifth pane (DESIGN §5), like
 * the key listing it sits beside. Every change re-reads the organisation, so
 * what is on screen is what the server holds.
 */
export function MembersDialog() {
  const { membersOpen, me, set, boot } = useAtlas()
  const [org, setOrg] = useState<Org | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  const load = useCallback(async () => {
    try { setOrg(await getOrg()); setFailed(null) } catch (e) { setFailed(messageOf(e)) }
  }, [])

  useEffect(() => { if (membersOpen) { setOrg(null); void load() } }, [membersOpen, load])

  /** Run one change, say what happened, and re-read. */
  const act = useCallback(async (done: string, fn: () => Promise<unknown>, description?: string) => {
    try {
      await fn()
      toast.success(done, description ? { description } : undefined)
      await load()
      return true
    } catch (e) {
      toast.error("Change not saved.", { description: messageOf(e) })
      return false
    }
  }, [load])

  const sheets = org?.workspaces.map((w) => w.name) ?? []

  return (
    <Dialog open={membersOpen} onOpenChange={(o) => { set({ membersOpen: o }); if (!o) void boot() }}>
      {/* minmax(0,1fr): a grid track otherwise grows to its widest row, and
          on a phone the invite row pushed the whole dialog off the right edge. */}
      <DialogContent className="max-h-[90dvh] grid-cols-[minmax(0,1fr)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="font-display text-[22px] font-semibold">Members</DialogTitle>
          <DialogDescription>
            Who can open {me?.org?.name ?? "your organisation"}'s sheets, and what each person may do there.
            Changes apply from their next request.
          </DialogDescription>
        </DialogHeader>

        {failed ? (
          <p role="alert" className="border-l-[3px] border-bad bg-bad-soft px-3 py-2 font-mono text-[13px]">{failed}</p>
        ) : !org ? (
          <p className="label normal-case tracking-normal">Reading members…</p>
        ) : (
          <div className="space-y-6">
            <People org={org} sheets={sheets} act={act} />
            <Groups org={org} act={act} />
            <Invited org={org} act={act} />
            <Invite sheets={sheets} act={act} domain={org.domain} />
            <Sheets org={org} act={act} />
            <SpendingLimits />
            <Machines org={org} sheets={sheets} act={act} />
            <UnansweredList />
            <Activity />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

type Act = (done: string, fn: () => Promise<unknown>, description?: string) => Promise<boolean>

const ROLE_HELP: Record<Role, string> = {
  reader: "asks questions",
  editor: "also adds sources",
  admin: "also manages the sheet",
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="label border-b pb-1">{title}</h3>
      {children}
    </section>
  )
}

function Access({ admin, roles }: { admin: boolean; roles: Grants }) {
  if (admin) return <Badge tone="blue">org admin · every sheet</Badge>
  const entries = Object.entries(roles)
  if (!entries.length) return <span className="text-ink-3">no sheets yet</span>
  return <span className="text-ink-2">{entries.map(([s, r]) => `${s}: ${r}`).join(" · ")}</span>
}

function Badge({ tone, children }: { tone: "blue" | "good" | "bad"; children: React.ReactNode }) {
  return (
    <span className={cn(
      "inline-flex items-center rounded-[2px] border px-1.5 py-0.5 font-mono text-[11px] uppercase tracking-wider",
      tone === "blue" && "border-blue bg-blue-soft text-blue",
      tone === "good" && "border-good bg-good-soft text-good",
      tone === "bad" && "border-bad bg-bad-soft text-bad",
    )}>{children}</span>
  )
}

/** A role per sheet, and optionally the organisation-admin switch. */
function GrantsEditor({ sheets, roles, onRoles, admin, onAdmin }: {
  sheets: string[]; roles: Grants; onRoles: (g: Grants) => void
  admin?: boolean; onAdmin?: (v: boolean) => void
}) {
  return (
    <div className="space-y-2">
      {onAdmin && (
        <label className="flex items-center gap-2 font-mono text-[13px]">
          <Switch checked={admin} onCheckedChange={onAdmin} />
          Organisation admin <span className="text-ink-3">— every sheet, and this page</span>
        </label>
      )}
      {!admin && (sheets.length === 0 ? (
        <p className="label normal-case tracking-normal">No sheets yet. Add one under Sheets first.</p>
      ) : (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {sheets.map((s) => (
            <div key={s} className="flex items-center gap-2 font-mono text-[13px]">
              <span className="min-w-0 flex-1 truncate">{s}</span>
              <Select
                value={roles[s] ?? "none"}
                onValueChange={(v) => {
                  const next = { ...roles }
                  if (v === "none") delete next[s]; else next[s] = v as Role
                  onRoles(next)
                }}
              >
                <SelectTrigger size="sm" className="w-32 font-mono text-[12px]" aria-label={`Role on ${s}`}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">no access</SelectItem>
                  {(["reader", "editor", "admin"] as Role[]).map((r) => (
                    <SelectItem key={r} value={r}>{r} <span className="text-ink-3">— {ROLE_HELP[r]}</span></SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function People({ org, sheets, act }: { org: Org; sheets: string[]; act: Act }) {
  const [editing, setEditing] = useState<string | null>(null)
  const [admin, setAdmin] = useState(false)
  const [roles, setRoles] = useState<Grants>({})
  const [groups, setGroups] = useState<string[]>([])

  return (
    <Section title={`People · ${org.members.length}`}>
      <ul className="divide-y font-mono text-[13px]">
        {org.members.map((m) => (
          <li key={m.id} className="py-2">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate">{m.email}{m.you && <span className="text-ink-3"> · you</span>}</div>
                <div className="text-[12px]"><Access admin={m.org_admin} roles={m.roles} /></div>
                {m.groups.length > 0 && <div className="truncate text-[12px] text-ink-3">groups: {m.groups.join(" · ")}</div>}
              </div>
              <Button variant="ghost" size="sm" className="press gap-1.5" aria-label={`Change access for ${m.email}`}
                onClick={() => { setEditing(editing === m.id ? null : m.id); setAdmin(m.org_admin); setRoles(m.roles); setGroups(m.groups) }}>
                {editing === m.id ? <X className="size-3.5" /> : <Pencil className="size-3.5" />}
                <span className="hidden sm:inline">{editing === m.id ? "Close" : "Change"}</span>
              </Button>
              {!m.you && (
                <Button variant="ghost" size="sm" className="press gap-1.5 text-bad" aria-label={`Remove ${m.email}`}
                  onClick={() => { if (confirm(`Remove ${m.email}? They lose access on their next request.`)) void act(`Removed ${m.email}`, () => removeMember(m.id)) }}>
                  <Trash2 className="size-3.5" /> <span className="hidden sm:inline">Remove</span>
                </Button>
              )}
            </div>
            {editing === m.id && (
              <div className="mt-2 space-y-2 rounded-md border bg-card p-3">
                <GrantsEditor sheets={sheets} roles={roles} onRoles={setRoles} admin={admin}
                  onAdmin={m.you ? undefined : setAdmin} />
                {org.groups.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="label">Groups <span className="normal-case tracking-normal">— decide which restricted sources they can read</span></div>
                    <div className="flex flex-wrap gap-1.5">
                      {org.groups.map((g) => (
                        <GroupToggle key={g.id} name={g.name} on={groups.includes(g.name)}
                          onToggle={() => setGroups(groups.includes(g.name) ? groups.filter((x) => x !== g.name) : [...groups, g.name])} />
                      ))}
                    </div>
                  </div>
                )}
                <div className="flex justify-end">
                  <Button size="sm" className="press" onClick={async () => {
                    if (await act(`Updated ${m.email}`, () => updateMember(m.id, admin, admin ? {} : roles, groups))) setEditing(null)
                  }}>Save access</Button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Section>
  )
}

/**
 * The organisation's groups. A group is what a restricted source is shared
 * with; who is in it is set on each person above, so this list only names
 * them, counts them, and adds or deletes one.
 */
function Groups({ org, act }: { org: Org; act: Act }) {
  const [name, setName] = useState("")
  const count = (g: string) => org.members.filter((m) => m.groups.includes(g)).length
  return (
    <Section title={`Groups · ${org.groups.length}`}>
      <p className="label normal-case tracking-normal">
        Share a source with a group from its row in the corpus pane. Add people to a group with Change, above.
        Organisation admins read only what their own groups allow.
      </p>
      {org.groups.length > 0 && (
        <ul className="divide-y font-mono text-[13px]">
          {org.groups.map((g) => (
            <li key={g.id} className="flex items-center gap-3 py-2">
              <div className="min-w-0 flex-1 truncate">{g.name} <span className="tabular text-ink-3">· {count(g.name)} {count(g.name) === 1 ? "person" : "people"}</span></div>
              <Button variant="ghost" size="sm" className="press gap-1.5 text-bad" aria-label={`Delete group ${g.name}`}
                onClick={() => {
                  if (confirm(`Delete group ${g.name}? Sources shared only with it become readable by nobody until an editor shares them again.`))
                    void act(`Deleted group ${g.name}`, () => deleteGroup(g.id))
                }}>
                <Trash2 className="size-3.5" /> <span className="hidden sm:inline">Delete</span>
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form className="flex gap-2" onSubmit={async (e) => {
        e.preventDefault()
        const n = name.trim()
        if (n && await act(`Added group ${n}`, () => createGroup(n), "Add people to it with Change, then share sources with it.")) setName("")
      }}>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="new group, e.g. Legal" aria-label="New group name"
          autoComplete="off" spellCheck={false} className="font-mono text-[13px]" />
        <Button type="submit" variant="secondary" className="press" disabled={!name.trim()}>Add group</Button>
      </form>
    </Section>
  )
}

function Invite({ sheets, act, domain }: { sheets: string[]; act: Act; domain: string }) {
  const [email, setEmail] = useState("")
  const [admin, setAdmin] = useState(false)
  const [roles, setRoles] = useState<Grants>({})
  const send = async () => {
    const to = email.trim()
    if (!to) return
    if (await act(`Invited ${to}`, () => invite(to, admin, admin ? {} : roles),
      "They sign in with Google at this address; the invitation is used up then.")) {
      setEmail(""); setAdmin(false); setRoles({})
    }
  }
  return (
    <Section title="Invite">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void send() }}>
        <div className="flex gap-2">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com"
            aria-label="Email address to invite" autoComplete="off" spellCheck={false} className="font-mono text-[13px]" />
          <Button type="submit" className="press" disabled={!email.trim()}>Invite</Button>
        </div>
        <GrantsEditor sheets={sheets} roles={roles} onRoles={setRoles} admin={admin} onAdmin={setAdmin} />
        {domain && (
          <p className="label normal-case tracking-normal">
            Anyone with a Google Workspace account at <b className="font-medium text-foreground">{domain}</b> can also sign in without an invitation, with no sheets until you give some.
          </p>
        )}
      </form>
    </Section>
  )
}

function Invited({ org, act }: { org: Org; act: Act }) {
  if (!org.invitations.length) return null
  return (
    <Section title={`Invited · ${org.invitations.length}`}>
    <ul className="divide-y font-mono text-[13px]">
      {org.invitations.map((i) => (
        <li key={i.email} className="flex items-center gap-3 py-2">
          <div className="min-w-0 flex-1">
            <div className="truncate">{i.email} <span className="text-ink-3">· not signed in yet</span></div>
            <div className="text-[12px]"><Access admin={i.org_admin} roles={i.roles} /></div>
          </div>
          <Button variant="ghost" size="sm" className="press gap-1.5" aria-label={`Withdraw the invitation to ${i.email}`}
            onClick={() => void act(`Withdrew ${i.email}'s invitation`, () => withdrawInvitation(i.email))}>
            <X className="size-3.5" /> <span className="hidden sm:inline">Withdraw</span>
          </Button>
        </li>
      ))}
    </ul>
    </Section>
  )
}

function Sheets({ org, act }: { org: Org; act: Act }) {
  const [name, setName] = useState("")
  return (
      <Section title={`Sheets · ${org.workspaces.length}`}>
        <p className="font-mono text-[13px] text-ink-2">{org.workspaces.map((w) => w.name).join(" · ") || "None yet."}</p>
        <form className="flex gap-2" onSubmit={async (e) => {
          e.preventDefault()
          const n = name.trim()
          if (n && await act(`Added sheet ${n}`, () => createSheet(n), "Give people a role on it, then add sources to it.")) setName("")
        }}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="new-sheet-name" aria-label="New sheet name"
            autoComplete="off" spellCheck={false} className="font-mono text-[13px]" />
          <Button type="submit" variant="secondary" className="press" disabled={!name.trim()}>Add sheet</Button>
        </form>
      </Section>
  )
}

function Machines({ org, sheets, act }: { org: Org; sheets: string[]; act: Act }) {
  const [name, setName] = useState("")
  const [roles, setRoles] = useState<Grants>({})
  const [fresh, setFresh] = useState<{ name: string; key: string } | null>(null)
  return (
    <Section title={`Service accounts · ${org.service_accounts.length}`}>
      <p className="label normal-case tracking-normal">API keys for scripts and other systems. People should sign in instead.</p>
      {org.service_accounts.length > 0 && (
        <ul className="divide-y font-mono text-[13px]">
          {org.service_accounts.map((s) => (
            <li key={String(s.key_id)} className={cn("flex items-center gap-3 py-2", !s.is_active && "opacity-60")}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 truncate">{s.name} <Badge tone={s.is_active ? "good" : "bad"}>{s.is_active ? "active" : "revoked"}</Badge></div>
                <div className="text-[12px]"><Access admin={false} roles={s.roles} /> <span className="text-ink-3 tabular">· {s.total_queries} queries</span></div>
              </div>
              {s.is_active && (
                <Button variant="ghost" size="sm" className="press gap-1.5" aria-label={`Revoke ${s.name}`}
                  onClick={() => void act(`Revoked ${s.name}`, () => revokeServiceAccount(s.key_id), "The key is refused from its next request.")}>
                  <ShieldOff className="size-3.5" /> <span className="hidden sm:inline">Revoke</span>
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {fresh && (
        <div className="space-y-1 rounded-md border border-blue bg-blue-soft p-3 font-mono text-[13px]">
          <div>Key for {fresh.name} — shown once, copy it now.</div>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 break-all rounded-sm border bg-well px-1.5 py-1">{fresh.key}</code>
            <Button variant="ghost" size="icon-sm" className="press" aria-label="Copy key"
              onClick={() => { void navigator.clipboard.writeText(fresh.key); toast.success("Key copied") }}>
              <Copy className="size-3.5" />
            </Button>
          </div>
        </div>
      )}
      <form className="space-y-3" onSubmit={async (e) => {
        e.preventDefault()
        const n = name.trim()
        if (!n) return
        let made: { key: string } | null = null
        if (await act(`Created ${n}`, async () => { made = await createServiceAccount(n, roles) })) {
          if (made) setFresh({ name: n, key: (made as { key: string }).key })
          setName(""); setRoles({})
        }
      }}>
        <div className="flex gap-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="nightly-sync" aria-label="Service account name"
            autoComplete="off" spellCheck={false} className="font-mono text-[13px]" />
          <Button type="submit" variant="secondary" className="press" disabled={!name.trim()}>Create key</Button>
        </div>
        <GrantsEditor sheets={sheets} roles={roles} onRoles={setRoles} />
      </form>
    </Section>
  )
}

const DOING: Record<string, string> = {
  query: "asked", "mcp.search": "searched through an assistant", "mcp.list_sheets": "listed sheets through an assistant",
  "mcp.list_sources": "listed sources through an assistant", sign_in: "signed in", upload: "uploaded",
  ingest: "indexed a server path", "document.access": "changed readers of", "document.remove": "removed",
  "audit.retention": "changed how long this record is kept",
  "sheet.limit": "changed a sheet's daily spending limit",
  feedback: "gave feedback on an answer", unanswered: "got no answer",
  "POST /org/groups": "made a group", "DELETE /org/groups/{group_id}": "deleted a group",
  "POST /org/invitations": "invited someone", "DELETE /org/invitations/{email}": "withdrew an invitation",
  "PUT /org/members/{user_id}": "changed a member's access", "DELETE /org/members/{user_id}": "removed a member",
  "POST /org/workspaces": "added a sheet", "POST /org/service-accounts": "made a service account key",
  "DELETE /org/service-accounts/{key_id}": "revoked a service account key",
  "POST /me/keys": "made a personal key", "DELETE /me/keys/{key_id}": "revoked a personal key",
  "PUT /namespaces/{namespace}/connectors/drive": "chose a Drive folder for",
  "POST /namespaces/{namespace}/connectors/drive/sync": "synced Drive for",
  "DELETE /namespaces/{namespace}/connectors/drive": "disconnected Drive from",
  "drive.connect": "connected Drive to",
}
const KEEP = [30, 90, 365, 730, 2555]

/**
 * The organisation's audit record (E4.1): newest first, questions included,
 * readable only by organisation admins. Entries leave by age alone.
 */
function Activity() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null)
  const [days, setDays] = useState<number | null>(null)
  const [more, setMore] = useState(true)
  const load = useCallback(async (before?: number) => {
    try {
      const r = await getAudit(before)
      setEntries((old) => (before && old ? [...old, ...r.entries] : r.entries))
      setDays(r.retention_days); setMore(r.entries.length === 50)
    } catch (e) { toast.error("Activity not loaded", { description: messageOf(e) }) }
  }, [])
  useEffect(() => { void load() }, [load])

  const keep = async (v: string) => {
    try { await setAuditRetention(Number(v)); setDays(Number(v)); toast.success(`New entries kept ${v} days`) } catch (e) {
      toast.error("Not saved", { description: messageOf(e) })
    }
  }

  return (
    <Section title="Activity">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="label normal-case tracking-normal text-[12px] leading-snug">
          Who asked what, and who changed what, on every sheet. Only organisation admins see this.
        </p>
        {days !== null && (
          <Select value={String(days)} onValueChange={(v) => void keep(v)}>
            <SelectTrigger className="h-8 w-auto gap-2 font-mono text-[12px]" aria-label="Keep entries for"><SelectValue /></SelectTrigger>
            <SelectContent>
              {(KEEP.includes(days) ? KEEP : [...KEEP, days].sort((a, b) => a - b)).map((d) => (
                <SelectItem key={d} value={String(d)} className="font-mono text-[12px]">keep {d} days</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
      {entries === null ? <p className="label normal-case tracking-normal">Reading activity…</p> : entries.length === 0 ? (
        <p className="label normal-case tracking-normal">Nothing yet.</p>
      ) : (
        <ul className="flex flex-col">
          {entries.map((e) => (
            <li key={e.id} className="border-b border-border/60 py-1.5 font-mono text-[12px] leading-relaxed text-ink-2">
              <span className="text-ink-3">{new Date(e.ts * 1000).toLocaleString()}</span>{" · "}
              <span className="text-ink-1">{e.actor.email ?? e.actor.key_name ?? e.actor.kind}</span>
              {e.actor.key_name && e.actor.email && <span className="text-ink-3"> (key: {e.actor.key_name})</span>}{" "}
              {DOING[e.action] ?? e.action}
              {e.detail?.source && <> <span className="text-ink-1">{e.detail.source}</span></>}
              {e.sheet && <> on <span className="text-ink-1">{e.sheet}</span></>}
              {e.status >= 400 && <span className="text-bad"> · refused ({e.status})</span>}
              {e.detail?.question && <div className="truncate pl-3 text-ink-3" title={e.detail.question}>“{e.detail.question}”</div>}
            </li>
          ))}
        </ul>
      )}
      {entries && more && (
        <Button variant="ghost" size="sm" className="press" onClick={() => void load(entries[entries.length - 1]?.ts)}>Older</Button>
      )}
    </Section>
  )
}

const WHY: Record<string, string> = {
  not_covered: "not in the documents", out_of_scope: "judged off-topic", wrong_answer: "marked wrong",
  wrong_source: "wrong source", no_answer: "marked unanswered", other: "marked down", "marked down": "marked down",
}

/**
 * What the sheets could not answer, or answered badly (E6.2), most asked
 * first. The list a knowledge owner works from: each row is a document
 * someone should write, fix or add to a sheet.
 */
const rupees = (n: number) => `₹${n < 10 ? n.toFixed(2) : Math.round(n).toLocaleString("en-IN")}`

/** E4.3: what each sheet spent today, and a daily limit of its own. */
function SpendingLimits() {
  const [data, setData] = useState<Spending | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const load = useCallback(() => {
    getSpending().then((d) => { setData(d); setDraft({}) })
      .catch((e) => toast.error("Spending not loaded", { description: messageOf(e) }))
  }, [])
  useEffect(load, [load])

  const save = async (sheet: string) => {
    const text = (draft[sheet] ?? "").trim()
    const value = text === "" ? 0 : Number(text)
    if (!Number.isFinite(value) || value < 0) { toast.error("Enter rupees a day, or leave it empty for no limit."); return }
    try {
      await setSheetLimit(sheet, value)
      toast.success(value ? `${sheet}: ${rupees(value)} a day` : `${sheet}: no limit of its own`,
        { description: "Applies within a minute." })
      load()
    } catch (e) { toast.error("Limit not saved.", { description: messageOf(e) }) }
  }

  const o = data?.overall
  return (
    <Section title="Spending today">
      <p className="label normal-case tracking-normal text-[12px] leading-snug">
        A sheet that reaches its limit stops answering new questions and adding documents until midnight UTC (5:30 am in India).
        {o && o.daily_inr > 0 && <> All sheets together: {rupees(o.spent_today_inr)} of {rupees(o.daily_inr)}.</>}
      </p>
      {data === null ? <p className="label normal-case tracking-normal">Reading…</p> : (
        <ul className="divide-y font-mono text-[13px]">
          {data.sheets.map((s) => {
            const full = s.daily_inr > 0 && s.spent_today_inr >= s.daily_inr
            const dirty = draft[s.sheet] !== undefined
            return (
              <li key={s.sheet} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <span className="min-w-0 flex-1 truncate">{s.sheet}</span>
                <span className={cn("tabular text-[12px]", full ? "text-bad" : "text-ink-3")}>
                  {rupees(s.spent_today_inr)}{s.daily_inr > 0 ? ` of ${rupees(s.daily_inr)}` : " · no limit"}
                </span>
                <form className="flex items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); void save(s.sheet) }}>
                  <span className="text-ink-3">₹</span>
                  <Input inputMode="decimal" className="h-8 w-20 font-mono text-[13px]" aria-label={`Daily limit for ${s.sheet} in rupees`}
                    placeholder="none" value={draft[s.sheet] ?? (s.daily_inr ? String(s.daily_inr) : "")}
                    onChange={(e) => setDraft((d) => ({ ...d, [s.sheet]: e.target.value }))} />
                  <Button type="submit" size="sm" variant="secondary" className="press" disabled={!dirty}>Set</Button>
                </form>
              </li>
            )
          })}
        </ul>
      )}
    </Section>
  )
}

function UnansweredList() {
  const [rows, setRows] = useState<Unanswered[] | null>(null)
  useEffect(() => {
    getUnanswered(30).then((r) => setRows(r.questions)).catch((e) => toast.error("Unanswered questions not loaded", { description: messageOf(e) }))
  }, [])
  return (
    <Section title={`Unanswered questions · last 30 days${rows ? ` · ${rows.length}` : ""}`}>
      <p className="label normal-case tracking-normal text-[12px] leading-snug">
        Questions a sheet could not answer, or whose answer someone marked down. Most asked first.
      </p>
      {rows === null ? <p className="label normal-case tracking-normal">Reading…</p> : rows.length === 0 ? (
        <p className="label normal-case tracking-normal">None. Every question found an answer.</p>
      ) : (
        <ul className="flex flex-col">
          {rows.map((r) => (
            <li key={`${r.sheet}:${r.question}`} className="border-b border-border/60 py-1.5 text-[13px] leading-relaxed">
              <div className="text-ink-1">{r.question}</div>
              <div className="font-mono text-[11px] text-ink-3">
                {r.sheet} · asked {r.times}× by {r.people} {r.people === 1 ? "person" : "people"} ·{" "}
                {Object.entries(r.why).map(([k, n]) => `${WHY[k] ?? k}${n > 1 ? ` ×${n}` : ""}`).join(", ")}
              </div>
              {r.comments.map((c, i) => <div key={i} className="pl-3 text-[12px] text-ink-2">“{c}”</div>)}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

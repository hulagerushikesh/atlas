import { useCallback, useEffect, useState } from "react"
import { Copy, Pencil, ShieldOff, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import {
  createServiceAccount, createSheet, getOrg, invite, messageOf, removeMember, revokeServiceAccount,
  updateMember, withdrawInvitation, type Grants, type Org, type Role,
} from "@/lib/api"
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
            <Invited org={org} act={act} />
            <Invite sheets={sheets} act={act} domain={org.domain} />
            <Sheets org={org} act={act} />
            <Machines org={org} sheets={sheets} act={act} />
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

  return (
    <Section title={`People · ${org.members.length}`}>
      <ul className="divide-y font-mono text-[13px]">
        {org.members.map((m) => (
          <li key={m.id} className="py-2">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate">{m.email}{m.you && <span className="text-ink-3"> · you</span>}</div>
                <div className="text-[12px]"><Access admin={m.org_admin} roles={m.roles} /></div>
              </div>
              <Button variant="ghost" size="sm" className="press gap-1.5" aria-label={`Change access for ${m.email}`}
                onClick={() => { setEditing(editing === m.id ? null : m.id); setAdmin(m.org_admin); setRoles(m.roles) }}>
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
                <div className="flex justify-end">
                  <Button size="sm" className="press" onClick={async () => {
                    if (await act(`Updated ${m.email}`, () => updateMember(m.id, admin, admin ? {} : roles))) setEditing(null)
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

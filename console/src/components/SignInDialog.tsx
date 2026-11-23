import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ApiError, messageOf, signInWithGoogle } from "@/lib/api"
import { useAtlas } from "@/lib/store"

/**
 * Sign in with Google. Google draws its own button (Google Identity
 * Services); this dialog hosts it and posts the token it returns to
 * /auth/google, which sets the session cookie. Atlas never sees a password.
 *
 * A dialog for the same reason the key listing is one: an occasional act,
 * not a fifth place in the console (DESIGN §5).
 */

interface GoogleId {
  initialize(o: { client_id: string; callback: (r: { credential: string }) => void; ux_mode: "popup"; auto_select: boolean; use_fedcm_for_prompt?: boolean }): void
  renderButton(el: HTMLElement, o: Record<string, string | number>): void
  disableAutoSelect(): void
}
declare global { interface Window { google?: { accounts: { id: GoogleId } } } }

const GIS = "https://accounts.google.com/gsi/client"
let loading: Promise<GoogleId> | null = null

function loadGoogle(): Promise<GoogleId> {
  if (window.google?.accounts?.id) return Promise.resolve(window.google.accounts.id)
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement("script")
    s.src = GIS; s.async = true; s.defer = true
    s.onload = () => (window.google?.accounts?.id ? resolve(window.google.accounts.id) : reject(new Error("Google sign-in did not load")))
    s.onerror = () => { loading = null; reject(new Error("Google sign-in could not be reached")) }
    document.head.appendChild(s)
  })
  return loading
}

interface Problem { what: string; why: string; next: string }

function problemFrom(e: unknown): Problem {
  const code = e instanceof ApiError ? (e.detail as { code?: unknown } | undefined)?.code : undefined
  if (code === "not_invited")
    return { what: "Not invited yet.", why: messageOf(e), next: "An admin of your organisation adds you under Members; then sign in again." }
  if (code === "invalid_token")
    return { what: "Google did not confirm this sign-in.", why: "The token was expired, or not made for this Atlas.", next: "Try again." }
  return { what: "Sign-in failed.", why: messageOf(e), next: "Try again shortly." }
}

export function SignInDialog() {
  const { signInOpen, authConfig, set, boot } = useAtlas()
  const [slot, setSlot] = useState<HTMLDivElement | null>(null)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [busy, setBusy] = useState(false)
  const clientId = authConfig?.google_client_id ?? ""

  useEffect(() => { if (signInOpen) setProblem(null) }, [signInOpen])

  useEffect(() => {
    if (!signInOpen || !slot || !clientId) return
    let gone = false
    loadGoogle().then((id) => {
      if (gone) return
      id.initialize({
        client_id: clientId, ux_mode: "popup", auto_select: false,
        callback: async ({ credential }) => {
          setBusy(true); setProblem(null)
          try {
            const me = await signInWithGoogle(credential)
            set({ signInOpen: false })
            toast.success("Signed in", { description: `${me.user?.email ?? ""} · ${me.org?.name ?? ""}` })
            void boot()
          } catch (e) {
            setProblem(problemFrom(e))
          } finally {
            setBusy(false)
          }
        },
      })
      const dark = document.documentElement.classList.contains("dark")
      slot.replaceChildren()
      id.renderButton(slot, {
        type: "standard", theme: dark ? "filled_black" : "outline", size: "large",
        text: "signin_with", shape: "rectangular", logo_alignment: "left", width: 280,
      })
    }).catch((e: unknown) => {
      if (!gone) setProblem({ what: "Google sign-in could not load.", why: messageOf(e), next: "Check the connection, or that a blocker is not stopping accounts.google.com." })
    })
    return () => { gone = true }
  }, [signInOpen, slot, clientId, set, boot])

  return (
    <Dialog open={signInOpen} onOpenChange={(o) => set({ signInOpen: o })}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display text-[22px] font-semibold">Sign in</DialogTitle>
          <DialogDescription>
            With the Google account your organisation invited. You see your organisation's sheets, and nothing else.
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-11 items-center" aria-busy={busy}>
          <div ref={setSlot} className={busy ? "pointer-events-none opacity-60" : undefined} />
        </div>
        {problem && (
          <div role="alert" className="border-l-[3px] border-bad bg-bad-soft px-3 py-2 font-mono text-[13px]">
            <div>{problem.what}</div>
            <div className="text-ink-2">{problem.why}</div>
            <div className="text-ink-2">{problem.next}</div>
          </div>
        )}
        <p className="label normal-case tracking-normal">
          Atlas keeps your name and email address only. <a className="underline underline-offset-2" href="/privacy" target="_blank" rel="noreferrer">Privacy</a>
        </p>
      </DialogContent>
    </Dialog>
  )
}

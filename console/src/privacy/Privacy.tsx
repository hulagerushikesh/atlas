import { TooltipProvider } from "@/components/ui/tooltip"
import { Footer, GITHUB, Nav } from "@/landing/Sections"

/**
 * What Atlas keeps about the people who use it. Linked from Google's sign-in
 * screen, which will not let the app out of testing without one, and from the
 * console's sign-in dialog. Every sentence here is checked against the code
 * (atlas.api.sessions, tenancy, routes/query.py); change them together.
 */
export default function Privacy() {
  return (
    <TooltipProvider>
      <Nav />
      <main className="mx-auto max-w-3xl px-5 pb-20 pt-14">
        <div className="label">Last updated 23 November 2026</div>
        <h1 className="mt-3 font-display text-[44px] font-bold uppercase leading-none tracking-[0.01em] text-balance sm:text-[54px]">
          Privacy
        </h1>
        <p className="mt-5 max-w-[60ch] text-[20px] leading-relaxed text-ink-2">
          Atlas answers questions from documents and shows where each answer came from. This page says what it keeps about you while it does that.
        </p>

        <Part title="If you sign in with Google">
          <p>Google tells Atlas your name and email address, and confirms Google checked the address. Atlas asks for nothing else: not your contacts, files, calendar or password.</p>
          <p>Atlas keeps your name, email address, your organisation and the sheets you may open, so it can show you those sheets and no others. It keeps them until an admin of your organisation removes you, which deletes them.</p>
          <p>Signing in sets one cookie, <code>atlas_session</code>. It holds an account number and an expiry, lasts eight hours, and cannot be read by scripts on the page. Atlas uses no advertising or tracking cookies.</p>
        </Part>

        <Part title="What you ask and add">
          <p>To write an answer, your question and the passages Atlas found are sent to the language model that writes it (Google's Gemini). The same answer may be kept for up to an hour, so asking it again is instant.</p>
          <p>Server logs record each request, including the first 80 characters of a question. Google Cloud keeps these logs for 30 days.</p>
          <p>Documents added to a sheet are stored in Atlas's search index until they are removed. Only people your organisation gives a role on that sheet can search them.</p>
        </Part>

        <Part title="Without signing in">
          <p>The public demo needs no account. Your network address is used to limit how many questions a visitor can ask in a minute. Like every request's, it also appears in the server logs above.</p>
          <p>Your browser keeps your settings here (theme, last sheet, and an API key if you type one). They never leave your browser except the key, which is sent with your requests.</p>
        </Part>

        <Part title="Who sees it">
          <p>Atlas runs on Google Cloud. Nothing about you is sold or shared for advertising. People in other organisations on the same Atlas cannot see your sheets, questions or account.</p>
          <p>Questions about this page, or a request to delete your data: <a className="underline underline-offset-2" href={`${GITHUB}/issues`} target="_blank" rel="noreferrer">open an issue</a>, or ask your organisation's admin.</p>
        </Part>
      </main>
      <Footer />
    </TooltipProvider>
  )
}

function Part({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-12">
      <h2 className="border-t-2 border-foreground pt-3 font-display text-[30px] font-semibold uppercase text-balance">{title}</h2>
      <div className="mt-4 max-w-[72ch] space-y-4 text-[17px] leading-[1.55] [&_code]:rounded-sm [&_code]:border [&_code]:bg-well [&_code]:px-1 [&_code]:font-mono [&_code]:text-[.86em]">
        {children}
      </div>
    </section>
  )
}

import { ArrowRight, Code2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { TooltipProvider } from "@/components/ui/tooltip"
import { HeroSurvey } from "./HeroSurvey"
import { FieldNotes, Footer, GITHUB, Measured, Nav, Pipeline, Principles, QuickStart } from "./Sections"

// Hero entrance is CSS (animate-rise), not Motion: it must render even if
// requestAnimationFrame is throttled, and CSS animations run off-thread.
const rise = (ms: number) => ({ animationDelay: `${ms}ms` })

export default function Landing() {
  return (
    <TooltipProvider delayDuration={300} skipDelayDuration={400}>
      <Nav />

      <section className="mx-auto grid max-w-6xl items-center gap-12 px-5 pb-20 pt-16 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:pt-24">
        <div>
          <div className="label animate-rise" style={rise(0)}>
            Agentic RAG · self-hosted
          </div>
          <h1
            style={rise(60)}
            className="animate-rise mt-3 font-display text-[52px] font-bold uppercase leading-[0.98] tracking-[0.01em] text-balance sm:text-[68px]"
          >
            Every answer, with the survey that found it.
          </h1>
          <p
            style={rise(120)}
            className="animate-rise mt-5 max-w-[48ch] text-[19px] leading-relaxed text-ink-2"
          >
            Atlas answers questions from your own documents and shows its work: which references it found, how each one scored, what it cut, and whether the answer holds up against the evidence.
          </p>
          <div style={rise(200)} className="animate-rise mt-8 flex flex-wrap items-center gap-3">
            <Button asChild size="lg" className="press font-mono text-[12px] uppercase tracking-wider">
              <a href="/app">Open the console <ArrowRight className="size-4" /></a>
            </Button>
            <Button asChild variant="outline" size="lg" className="press font-mono text-[12px] uppercase tracking-wider">
              <a href={GITHUB} target="_blank" rel="noreferrer"><Code2 className="size-4" /> Source</a>
            </Button>
          </div>
          <div style={rise(320)} className="animate-rise label mt-10 flex flex-wrap gap-x-6 gap-y-1 tabular">
            <span><b className="font-medium text-foreground">270</b> tests</span>
            <span><b className="font-medium text-foreground">86%</b> coverage</span>
            <span><b className="font-medium text-foreground">6</b> stages</span>
            <span><b className="font-medium text-foreground">&lt;1 ms</b> cache hit</span>
          </div>
        </div>
        <div style={rise(160)} className="animate-rise">
          <HeroSurvey />
        </div>
      </section>

      <Principles />
      <Pipeline />
      <Measured />
      <FieldNotes />
      <QuickStart />
      <Footer />
    </TooltipProvider>
  )
}

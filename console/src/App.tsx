import { useCallback, useEffect, useState } from "react"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { AnswerPane } from "@/components/AnswerPane"
import { CommandMenu } from "@/components/CommandMenu"
import { CorpusPane } from "@/components/CorpusPane"
import { EvidencePane } from "@/components/EvidencePane"
import { SettingsDialog } from "@/components/SettingsDialog"
import { SurveyBar } from "@/components/SurveyBar"
import { KeyStrip, TopBar } from "@/components/TopBar"
import { applyTheme, useAtlas } from "@/lib/store"
import { store as ls } from "@/lib/api"

export default function App() {
  const boot = useAtlas((s) => s.boot)
  const [corpusCollapsed, setCorpusCollapsed] = useState(() => ls.get("atlas_corpus") === "collapsed")
  const toggleCorpus = useCallback(() => {
    setCorpusCollapsed((v) => { ls.set("atlas_corpus", v ? "" : "collapsed"); return !v })
  }, [])

  useEffect(() => {
    applyTheme(useAtlas.getState().theme)
    void boot()
    // Follow the OS while in system mode.
    const mq = matchMedia("(prefers-color-scheme: dark)")
    const onChange = () => { if (!useAtlas.getState().theme) applyTheme("") }
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [boot])

  return (
    <TooltipProvider delayDuration={300} skipDelayDuration={400}>
      <div className="flex h-dvh flex-col overflow-hidden">
        <TopBar />
        <KeyStrip />
        <main className="flex min-h-0 flex-1">
          <div className="hidden h-full md:block">
            <CorpusPane collapsed={corpusCollapsed} onToggle={toggleCorpus} />
          </div>
          <AnswerPane />
          <EvidencePane />
        </main>
        <SurveyBar />
      </div>
      <CommandMenu onToggleCorpus={toggleCorpus} />
      <SettingsDialog />
      <Toaster position="bottom-left" toastOptions={{ className: "font-mono text-[13px]" }} />
    </TooltipProvider>
  )
}

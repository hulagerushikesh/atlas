/*
 * Every word the console uses to explain itself, in one place.
 *
 * The first outside reader of Atlas (2026-10-25) could drive the console but
 * could not read it: the evidence cards printed `dense 0.82  bm25 4.71
 * rrf 0.031  rerank 0.94` with nothing saying what any of those were, and
 * nothing said what the four panes were for. The pipeline was legible to its
 * author and opaque to everyone else, which for a product whose whole claim
 * is "shows its work" is the defect, not a polish item.
 *
 * Copy lives here rather than inline so the same sentence appears in the
 * card, the pane header and the legend without three chances to drift.
 * DESIGN.md §8 bans "namespace", "chunk" and "vector" from user-facing copy;
 * the score rows are mono data rows, where §8 allows the technical name — so
 * the jargon is kept as the *secondary* line, never as the only label.
 */

/** A score trail key as the API emits it (see `_collect_evidence`). */
export type ScoreKey = "dense" | "bm25" | "rrf" | "rerank" | "score"

export interface ScoreNote {
  /** What the card shows. Plain, lowercase, fits a mono row. */
  label: string
  /** The name in the literature, kept so the jargon stays searchable. */
  technical: string
  /** One sentence: what produced this number. */
  what: string
  /** One sentence: how to read it. The part people actually get wrong. */
  read: string
}

export const SCORES: Record<ScoreKey, ScoreNote> = {
  dense: {
    label: "meaning",
    technical: "Dense vector similarity",
    what: "How close this passage is to your question in meaning, even when it shares none of the same words.",
    read: "0 to 1, higher is closer.",
  },
  bm25: {
    label: "wording",
    technical: "BM25 keyword score",
    what: "How many of your exact words appear here, weighted so rare words count for more than common ones.",
    read: "No upper bound — only comparable against the other references in this same run.",
  },
  rrf: {
    label: "combined",
    technical: "Reciprocal rank fusion",
    what: "Merges the two rankings above into one order, using each passage's position rather than its raw score.",
    read: "Always a small number. A high one is impossible by design; compare it only to its neighbours.",
  },
  rerank: {
    label: "final",
    technical: "Cross-encoder rerank",
    what: "A model reads your question and this passage together — not separately — and scores the pair.",
    read: "This is the number the cut is made on. Everything below the line was dropped before the answer was written.",
  },
  score: {
    label: "score",
    technical: "Retriever score",
    what: "The only score this run produced, because it used a single retriever rather than the hybrid pipeline.",
    read: "Higher is better; the scale depends on the retriever.",
  },
}

/** Unknown retrievers keep their own name, so this has to degrade. */
export function scoreNote(key: string): ScoreNote | undefined {
  return SCORES[key as ScoreKey]
}

export function scoreLabel(key: string): string {
  return scoreNote(key)?.label ?? key
}

export interface PaneNote {
  /** Imperative, present tense, says what the reader is looking at. */
  what: string
}

export const PANES: Record<"corpus" | "answer" | "evidence" | "survey", PaneNote> = {
  corpus: {
    what: "The sheet you are asking, and every source indexed into it. Switch sheets to ask a different body of documents.",
  },
  answer: {
    what: "The answer, written only from the references found. Each numbered chip links to the reference that claim came from; a dashed underline means no reference supports that sentence.",
  },
  evidence: {
    what: "Every reference the survey retrieved, strongest first. Dimmed cards were cut before the answer was written — they are shown so you can see what was rejected, not just what was used.",
  },
  survey: {
    what: "The route your question took: every stage, how long each took, and what it cost. Expand it to see what went in and out of each one.",
  },
}

/*
 * The four lines of the first-visit card, in reading order. Deliberately the
 * same sentences as the pane headers: a reader who dismisses the card and
 * later hovers a header should meet the text they already read, not a
 * second, subtly different explanation of the same thing.
 *
 * `whereAt` is the breakpoint at which the position is actually true, and
 * it is load-bearing. The console is four docked panes only on a wide
 * screen: below `xl` the evidence pane is a drawer, below `md` the corpus
 * pane is gone and the sheet moves into the header. The first draft of this
 * card said "on the left" and "on the right" unconditionally, which on a
 * phone pointed at two things that were not there -- the exact failure that
 * ruled out a spotlight tour, reintroduced in prose. Below its breakpoint
 * each line gives the name alone, which stays true everywhere.
 */
export const TOUR = [
  { n: 1, name: "Corpus", where: "on the left", whereAt: "md", what: PANES.corpus.what },
  { n: 2, name: "Answer", where: "in the middle", whereAt: "xl", what: PANES.answer.what },
  { n: 3, name: "Evidence", where: "on the right", whereAt: "xl", what: PANES.evidence.what },
  { n: 4, name: "Survey", where: "along the bottom", whereAt: "always", what: PANES.survey.what },
] as const

/** Tailwind needs whole class names, so these cannot be built by template. */
export const WHERE_CLASS: Record<string, string> = {
  md: "hidden md:inline",
  xl: "hidden xl:inline",
  always: "",
}

/*
 * One opening question per sheet, so a first visit does not begin at a blank
 * box. `duckdb` gets the question the corpus was chosen for: DuckDB 2.0 ships
 * behaviour that reversed, so a model answering from memory gets it wrong and
 * the reader can check that for themselves in one paste.
 */
export const OPENERS: Record<string, string> = {
  duckdb: "What type does the literal X'CAFE' produce in DuckDB?",
  default: "How do I declare a path parameter in FastAPI?",
}

export function openerFor(sheet: string): string | undefined {
  return OPENERS[sheet]
}

/*
 * What the reader is told at the empty box, and when the router refuses.
 *
 * The first two outside users (2026-11-03) both stalled at exactly these two
 * states. One typed "heyy", was correctly routed out of scope, and never came
 * back -- a refusal is the whole of their experience of Atlas. The other
 * asked one real question of the corpus and then submitted the identical
 * string three more times in three minutes. Neither had seen the first-visit
 * card, which shipped that evening; but the card alone would not have saved
 * them, because dismissing it (or returning a second time) dropped them back
 * to a single line that named no subject and offered nothing to click.
 *
 * So both states now say what this sheet holds and offer one question that
 * is known to land. `holds` is rendered in front of the server's own
 * ROUTER_DOMAIN sentence -- the one the classifier actually judged against --
 * so the console quotes the rule rather than paraphrasing it, and a reader
 * who disagrees with a refusal can see precisely what was claimed.
 */
export const ASK = {
  empty:
    "Ask the sheet. The answer appears here as a document with a reference on every claim; the references themselves appear on the right.",
  holds: "This sheet holds",
  tryHint: "One question this sheet can answer",
} as const

/*
 * What the composer says once the question it is holding has already been
 * asked, and what a replayed answer says about itself.
 *
 * The second outside user (2026-11-03) asked one real question of the corpus
 * and then submitted the identical string three more times, 22 and 27 seconds
 * apart. Those gaps rule out both readings that were first assumed: too long
 * to be an impatient second Enter -- the send button is disabled while a run
 * is in flight anyway -- and too short to be a new thought. Each run finished
 * before the next began. They read an answer, then asked for the same one
 * again, three times.
 *
 * The mechanism is the composer. The box keeps the text after a submit, which
 * is right -- a reader should be able to edit a question and ask it again --
 * but nothing in it separates "not sent yet" from "sent, answered, and the
 * answer is the thing you are scrolling". A question still sitting in the box
 * under a live send button reads as unsent, and re-asking it costs one
 * keypress.
 *
 * So the row beneath the box says the question has been asked, and the Enter
 * hint names what pressing it would now do. Nothing is blocked: asking twice
 * to find out whether the answer is stable is a fair thing to want, and
 * `sameAnswer` is the honest reply to it.
 */
export const AGAIN = {
  /** Shown beneath the box. Lower case: it is a state, not a heading. */
  asked: "asked already",
  /** Replaces "ask" in the Enter hint, so the key names its own outcome. */
  again: "ask again",
  /*
   * Printed only when the server marks the response as a cache hit. The key
   * is the question and the sheet, so this is literally the stored answer
   * being replayed rather than a fresh run that happened to agree -- which
   * is exactly the question four identical submissions were asking. It is
   * not shown otherwise: the cache holds entries for an hour and only in
   * the process that wrote them, so a second ask can genuinely re-run, and
   * claiming otherwise would be the one false reading available here.
   */
  sameAnswer: "The stored answer to this same question — nothing was re-run.",
} as const

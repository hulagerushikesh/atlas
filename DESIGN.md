# Atlas Design System — Cartographic

This file is the visual contract for every Atlas UI surface (console, landing,
docs widget, eval reports). Read it before touching any HTML/CSS. Where this
file and an existing stylesheet disagree, this file wins and the stylesheet
is the bug.

Rationale and the field survey behind these choices:
https://claude.ai/code/artifact/887a2fe4-ded5-4488-aba4-c724e2072bc4

---

## 1. Thesis

Atlas is a retrieval system that shows its work. Every competitor hides the
pipeline and renders a chat bubble. Atlas renders the *locating* of an answer:
which documents were searched, which chunks were found, how they scored, what
was rejected, and how faithful the result is to the evidence.

The name gives the vernacular. An atlas is a bound set of maps with a legend,
grid references, a scale, and a key. So:

| Concept          | Atlas term        | Where it shows up                              |
|------------------|-------------------|------------------------------------------------|
| Namespace        | **Sheet**         | Corpus pane header, `/namespaces`              |
| Document         | **Source**        | Corpus list, citation chip hover               |
| Chunk            | **Reference**     | Evidence card: `dependencies.md · ref 14`      |
| Chunk position   | **Grid**          | `chars 2,140–2,610`                            |
| Retrieval score  | **Elevation**     | Score bars in evidence cards                   |
| Pipeline stages  | **Survey**        | The trace bar: "Survey · 7 stages · 1,842 ms"  |
| Legend           | **Key**           | Any explanatory strip mapping colour → meaning |

The metaphor lives in **structure and vocabulary only**. No contour-line
backgrounds, no compass roses, no parchment textures, no map illustrations.
The moment it becomes decoration it becomes slop.

---

## 2. Colour

Light-first. Dark is a full second theme, not an inversion.

### Tokens

```css
:root {
  /* Ground */
  --ground:      #F2F4F1;   /* survey paper — grey-green, not cream, not white */
  --paper:       #FAFBF9;   /* raised surface: cards, answer sheet */
  --well:        #E8ECE8;   /* recessed: inputs, code, inactive tracks */

  /* Ink */
  --ink:         #1B2027;   /* chart black */
  --ink-2:       #4A5560;   /* secondary text */
  --ink-3:       #7E8891;   /* labels, captions, disabled */

  /* Rules */
  --rule:        #CBD2CD;   /* structural borders */
  --rule-soft:   #E0E5E1;   /* row dividers, subtle separation */

  /* Accents — two, because the pipeline has two kinds of work */
  --blue:        #1F5F8B;   /* retrieval: dense, sparse, RRF, rerank, links, citations */
  --blue-soft:   rgba(31,95,139,.10);
  --ochre:       #A87C3A;   /* LLM: route, decompose, grade, generate, check */
  --ochre-soft:  rgba(168,124,58,.12);

  /* Semantic — separate from accents, never used as accent */
  --good:        #2F7D4F;   /* supported, indexed, healthy */
  --warn:        #B07A1C;   /* mixed, degraded, retry */
  --bad:         #A83A2B;   /* unsupported, failed, refused */
  --good-soft:   rgba(47,125,79,.12);
  --warn-soft:   rgba(176,122,28,.12);
  --bad-soft:    rgba(168,58,43,.12);
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground:      #141A1F;
    --paper:       #1B2228;
    --well:        #0F1418;
    --ink:         #E4E8E6;
    --ink-2:       #AEB7B3;
    --ink-3:       #7C8781;
    --rule:        #33404A;
    --rule-soft:   #26313A;
    --blue:        #6FB3DC;
    --blue-soft:   rgba(111,179,220,.12);
    --ochre:       #C9A063;
    --ochre-soft:  rgba(201,160,99,.14);
    --good:        #5DBA84;
    --warn:        #D9A441;
    --bad:         #E07A6B;
    --good-soft:   rgba(93,186,132,.14);
    --warn-soft:   rgba(217,164,65,.14);
    --bad-soft:    rgba(224,122,107,.14);
  }
}
:root[data-theme="dark"] { /* identical block to the media query above */ }
```

### Rules

- `body { background: var(--ground) }` always explicit. Never transparent.
- Every colour comes from a token. No literals in component CSS.
- Blue means retrieval. Ochre means LLM. Never swap them, never use either
  for decoration. A reader should learn the key once and read every trace.
- Semantic colours carry state only. `--good` is never a CTA colour.
- Contrast floor: body text ≥ 7:1 on `--ground`, labels ≥ 4.5:1.
- No gradients. No glows. No `box-shadow` larger than `0 1px 2px rgba(0,0,0,.06)`.

---

## 3. Typography

Three faces, three jobs. All from Google Fonts; every face has a real fallback.

```css
--display: "Barlow Condensed", "Arial Narrow", "Helvetica Neue", sans-serif;
--body:    "Source Serif 4", Georgia, "Times New Roman", serif;
--mono:    "IBM Plex Mono", ui-monospace, Menlo, monospace;
```

```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&family=IBM+Plex+Mono:wght@400;500&display=swap">
```

| Role            | Face     | Size / weight        | Treatment                                  |
|-----------------|----------|----------------------|--------------------------------------------|
| Page title      | display  | 54px / 700           | uppercase, `letter-spacing: .01em`         |
| Section         | display  | 30px / 600           | uppercase, 2px top rule in `--ink`         |
| Sub-section     | display  | 22px / 600           | sentence case                              |
| Pane header     | mono     | 12px / 500           | uppercase, `letter-spacing: .14em`, ink-3  |
| Body            | body     | 17px / 400, lh 1.55  | max-width 72ch                             |
| Answer text     | body     | 18px / 400, lh 1.6   | the one place body goes larger             |
| Lede            | body     | 20px / 400           | ink-2                                      |
| Data, scores    | mono     | 13px / 400           | `font-variant-numeric: tabular-nums`       |
| Chip / badge    | mono     | 11px / 500           | uppercase, `letter-spacing: .06em`         |
| Code            | mono     | .86em                | `--well` background, 1px `--rule-soft`     |

Rules:

- Display is condensed and uppercase because that is how map labels are set.
  It is never used for running text.
- Body is a serif because the answer is a document, not a message.
- Every number that could sit in a column is mono + tabular.
- `text-wrap: balance` on all headings.
- No Inter, Geist, Space Grotesk, Instrument Serif, Fraunces, anywhere.

---

## 4. Spacing, radius, elevation

```css
--s-1: 4px;  --s-2: 8px;  --s-3: 12px;  --s-4: 16px;
--s-5: 24px; --s-6: 32px; --s-7: 48px;  --s-8: 64px;

--r-0: 0;    /* panes, tables, trace bar, stage segments */
--r-1: 2px;  /* chips, badges, inputs, evidence cards */
--r-2: 4px;  /* code blocks, popovers */
```

- Radius is **2px by default**. Nothing on the page exceeds 4px. Map sheets
  have square corners.
- Layout spacing via `gap` on flex/grid. No per-element margins between siblings.
- Elevation is expressed by **ground → paper** surface change and a 1px
  `--rule` border. Shadows are reserved for popovers (`0 1px 2px rgba(0,0,0,.06)`).
- Not everything is a card. Panes are regions separated by rules. Evidence
  references are cards. Answer text is not a card. Stats are not cards.

---

## 5. Layout — the console

Four places. Three are always present; the fourth collapses.

```
┌──────────────────────────────────────────────────────────────────┐
│ ATLAS · SHEET fastapi · 121 SOURCES · 2,140 REFS        [key] [⚙] │  header, 40px
├──────────┬──────────────────────────────────┬────────────────────┤
│ CORPUS   │ ANSWER                           │ EVIDENCE · 5 REFS  │
│          │                                  │                    │
│ sources  │ answer text with claim chips [1] │ ref card (cited)   │
│ list     │                                  │ ref card (cited)   │
│          │ ── SUPPORTED · 0.94 ──           │ ref card (rejected)│
│ ingest   │                                  │                    │
│ progress │ [ Ask the sheet…              ↵ ]│                    │
├──────────┴──────────────────────────────────┴────────────────────┤
│ SURVEY · 7 STAGES · 1,842 ms · 2,310 tok · $0.0031      [expand] │  trace bar, 48px
│ ▮route ▮▮decompose ▮▮▮▮retrieve ×2 ▮▮rerank ▮grade ▮▮▮▮generate ▮check │
└──────────────────────────────────────────────────────────────────┘
   240px           1fr (min 480px)              300px
```

- **Corpus** (left, `--ground`): sheet selector, source list, ingest state.
  Collapsible to 48px icon rail.
- **Answer** (centre, `--paper`): the answer as a document. Query input is
  pinned to the bottom of this pane, not the page.
- **Evidence** (right, `--ground`): one card per retrieved reference, cited
  ones first, rejected ones after at 60% opacity. Clicking a chip in the
  answer scrolls and highlights the matching card.
- **Survey** (bottom, `--paper`): the trace. Collapsed = one line of figures
  + the span bar. Expanded = one row per stage with inputs, outputs, ms, tokens.

Responsive:

- `< 1100px`: Evidence becomes a drawer over Answer, toggled from the strength badge.
- `< 760px`: Corpus becomes a sheet picker in the header; single column;
  Survey collapses to figures only.

---

## 6. Components

### Citation chip

Inline, at the end of the claim it supports. Never a footnote at the bottom.

```html
<sup class="cite" data-ref="chunk-uuid">1</sup>
```

- 12×14px, `--blue` fill, `--paper` numeral, `--r-1`, mono 10px.
- Hover: popover with source name, `ref N`, grid (`chars a–b`), and excerpt
  capped at 200 characters. Popover uses `--paper`, 1px `--rule`, `--r-2`.
- Click: scroll Evidence to the card, flash the card's border `--blue` once
  (300ms). Also usable from keyboard: chips are `<button>` semantics.

### Unsourced span

Any sentence the generator emitted without a citation.

- `color: var(--ink-2)`, `text-decoration: underline dashed var(--ink-3)`,
  `text-underline-offset: 3px`.
- Hover title: "No reference supports this sentence."
- Never styled identically to sourced text. This is the point.

### Strength badge

One per answer, directly under the answer text.

| Label       | Condition                                          | Colour  |
|-------------|----------------------------------------------------|---------|
| SUPPORTED   | `is_faithful` and `faithfulness_score ≥ 0.8`       | `--good`|
| MIXED       | `is_faithful` and `0.5 ≤ score < 0.8`, or retries > 0 | `--warn`|
| WEAK        | not faithful, score ≥ 0.3                          | `--warn`|
| UNSUPPORTED | not faithful, score < 0.3, or no chunks passed grader | `--bad` |
| OUT OF SCOPE| `classification == "out_of_scope"`                 | `--ink-3`|
| UNCHECKED   | streamed answer — faithfulness is skipped on the streaming path | `--ink-3`|

Rendered: mono 11px uppercase, label + `· 0.94`, `--x-soft` fill, 1px `--x`
border, `--r-1`. Label first, number second. The label is the signal; the
number is for people who want it.

### Evidence card

```
┌────────────────────────────────────────────┐
│ [1] tutorial/dependencies.md    ref 14     │  mono 12, ink; chip left
│ chars 2,140–2,610 · p.3                    │  mono 11, ink-3
│ "Excerpt of the chunk text, two lines max… │  body 14, ink-2, clamp 2
│ dense .81  bm25 12.4  rrf .032  rerank .94 │  mono 11, ink-3, tabular
│ ████████████████████████████░░░░           │  4px bar, --blue on --well
└────────────────────────────────────────────┘
```

- `--paper`, 1px `--rule`, `--r-1`, padding `--s-3`.
- Cited card: border `--blue`. Rejected card: opacity .6, border `--rule`,
  final line replaced by `rerank .41 · below grader threshold`.
- Score bar length = rerank score. That is the elevation.
- Cards are one composed object: same padding, same line positions, chip in
  the same corner. A rejected card is the same card dimmed, not a different card.

### Survey bar (trace)

Horizontal span bar, proportional to `StageTimings`. One segment per stage.

- Retrieval segments: `--blue`. LLM segments: `--ochre`. Alternate opacity
  1 / .8 between adjacent same-colour segments so boundaries read.
- Segment label inside if ≥ 40px wide, else in a hover title.
- While streaming: segments append left-to-right as stages complete. The
  active stage pulses opacity .6 → 1 at 1.2s. Nothing else animates.
- Collapsed height 48px. Expanded: rows in a table — stage, ms, tokens,
  model, input summary, output summary — mono 13, `--rule-soft` dividers.

### Stage row states (expanded survey)

| State     | Marker                                   |
|-----------|------------------------------------------|
| done      | filled square, stage colour               |
| running   | pulsing square                            |
| retried   | filled square + `↻ 2` in `--warn`         |
| skipped   | hollow square, `--ink-3`, label struck    |
| failed    | filled square `--bad`, row expands to error |

### Query input

- `--well` background, 1px `--rule`, `--r-1`, body 17px, padding `--s-3 --s-4`.
- Placeholder: "Ask the sheet…" (sheet = namespace, see §1).
- Focus: border `--blue`, no glow, no outline offset tricks.
- Options (top_k, stream) live in a mono 12px row beneath, not in a modal.

### Refusal state (out of scope)

Not a chat bubble. A designed state:

- Answer pane shows: display 22px "Not on this sheet." then body: "The
  *fastapi* sheet has no references covering this. Try another sheet or
  ingest the source." Strength badge reads OUT OF SCOPE.
- Evidence pane shows what *was* retrieved and why each was rejected, so the
  refusal is auditable.

### Error surface

Every error is three lines. What. Why. Next.

```
Retrieval failed.
Qdrant returned 503 for sheet "fastapi" after 3 attempts.
Check `make health`, or switch sheets while it recovers.
```

Mono 13. `--bad-soft` fill, 3px left border `--bad`, `--r-0`. Never "Something
went wrong."

### Empty states

- Corpus empty: "No sources on this sheet." + the exact `make ingest` line.
- Evidence before first query: "References appear here as they are found."
- Survey before first query: the bar outline with stage names at `--ink-3`,
  so the reader sees the route the query will take.

### Key (legend)

A single strip, togglable from the header, that maps colours to meanings:

```
▮ retrieval   ▮ language model   ▮ supported   ▮ mixed   ▮ unsupported
```

The key exists so no colour has to be explained twice.

---

## 7. Motion

- Default: none. Motion earns its place by conveying **sequence** or **cause**.
- Allowed: survey segments appending as stages complete (sequence); citation
  chip → evidence card border flash (cause); answer text streaming in.
- Durations: 150ms for state, 300ms for cause-effect flashes. `ease-out`.
- `prefers-reduced-motion: reduce` disables the pulse and the flash; the
  survey bar simply appears complete.
- No page-load choreography. No hover lifts. No parallax. No skeleton shimmer
  — use `--ink-3` placeholder text instead.

---

## 8. Copy

- The user manages **sheets** and **sources**; the system finds
  **references**. Never "namespace", "chunk", "vector" in user-facing copy.
  Those words are fine in the expanded survey and in mono data rows.
- Active voice, present tense. "Indexed 121 sources" not "121 sources have
  been indexed successfully".
- Buttons name the outcome: "Ingest", "Compare runs", "Copy reference".
- Never apologise. Never "Oops". Never "AI".
- Headlines must say something only Atlas can say. "Ask anything" is banned.
  "Every answer, with the map that found it" is the register.

---

## 9. Do not ship

Any one of these reads as generated and undoes the rest.

- Purple, violet, indigo, or any gradient
- Glowing borders, blurred blobs, accent-glow backgrounds
- Three cards in a row with line icons
- Dark as the default theme
- Inter, Geist, Space Grotesk, Instrument Serif, Fraunces
- Radius > 4px; the same shadow on every block
- Emoji as UI markers
- Centred everything
- Contour lines, compasses, globes, parchment, pins — the metaphor is not decoration
- Big-number stat tiles as a landing view
- Chat bubbles, avatars, "typing…" indicators
- Skeleton shimmer
- Any word from the copy ban list in §8

---

## 10. File conventions

- Tokens live once, in `src/atlas/api/static/tokens.css`, imported by every
  page. No page redefines a token.
- Component CSS is named by role: `.cite`, `.ref-card`, `.survey-bar`,
  `.strength`. No utility soup, no BEM ceremony.
- Both themes are tested before merge: system-light, system-dark, and forced
  `data-theme` in each direction.
- A new component gets a row in §6 before it gets CSS.

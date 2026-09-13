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

--radius: 6px;         /* base; shadcn derives sm/md/lg from it */
--r-chip: 3px;         /* citation chips, badges, stage markers */
--r-0: 0;              /* panes, tables, trace bar, stage segments */
```

- Radius is **6px on interactive surfaces** (cards, inputs, popovers,
  dialogs) and 3px on chips and badges. Structural regions — panes, the
  survey bar, its segments, table rows — stay square. The sheet is square;
  the instruments on it are not.
- Layout spacing via `gap` on flex/grid. No per-element margins between siblings.
- Elevation is expressed by **ground → paper** surface change and a 1px
  `--rule` border. Shadows are reserved for floating surfaces — popovers,
  hover-cards, dialogs, the evidence drawer — and stay soft. A dialog scrim
  is `foreground/20` with a light backdrop blur; nothing on the sheet itself
  casts a shadow.
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

Motion earns its place by conveying **sequence, cause, or state** — and by
making the interface feel like it heard you. Decorative motion is banned;
responsive motion is required.

Curves and durations (from `tokens`):

```css
--ease-out-strong:    cubic-bezier(0.23, 1, 0.32, 1);   /* enter, feedback */
--ease-in-out-strong: cubic-bezier(0.77, 0, 0.175, 1);  /* on-screen movement */
--ease-drawer:        cubic-bezier(0.32, 0.72, 0, 1);   /* the evidence drawer */
```

| What                              | How                                             | Time   |
|-----------------------------------|-------------------------------------------------|--------|
| Any pressable thing               | `scale(0.97)` on `:active`                      | 160ms  |
| Tooltips                          | fade + scale from 0.97, origin at trigger; instant after the first | 125ms |
| Hover-cards, popovers, selects    | fade + scale from 0.96, origin at trigger       | 180ms  |
| Dialogs, settings                 | fade + scale from 0.96, centred                 | 200ms  |
| Evidence drawer (< xl)            | translateX, `--ease-drawer`                     | 300ms  |
| Corpus pane collapse              | width, `--ease-out-strong`                      | 260ms  |
| Survey table expand / collapse    | height auto, opacity                            | 260ms  |
| Evidence cards on arrival         | rise 8px + fade, staggered 40ms, max 8 deep     | 260ms  |
| Score bars                        | width from 0, after the card lands              | 500ms  |
| Survey segments                   | flex-grow to final width as each stage lands    | 300ms  |
| Running stage / health check      | opacity pulse 0.55 → 1                           | 1.2s   |
| Citation chips                    | scale from 0.85 + fade, after the doc crossfades | 180ms |
| Streamed answer → parsed document | crossfade with 2px blur                          | 280ms  |
| Chip → card flash                 | ring in `--blue-soft`, once                      | 200ms  |
| Source list on sheet change       | rise 4px + fade, staggered 25ms                  | 220ms  |

Rules:

- **Nothing keyboard-triggered animates.** The ⌘K palette opens instantly.
- Enter faster than exit is wrong here: enters ≤ 300ms, exits shorter still.
- Never `scale(0)`. Never `ease-in`. Never `transition: all`.
- `prefers-reduced-motion: reduce` collapses every duration to ~0; opacity
  changes remain so state is still legible.
- Hover lifts are 1px and gated behind `(hover: hover) and (pointer: fine)`.
- Skeletons are allowed while a pane waits on the network; they pulse, they
  do not shimmer.

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
- Skeleton *shimmer* (a pulse is fine)
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

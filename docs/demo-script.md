# The 90-second recording

A script for one screen recording of Atlas, for the top of the README and the
landing page. Six shots, about 90 seconds, one take. Cost: one question,
about ₹0.20.

## Before you press record

1. Use a laptop-size browser window, at least **1300 pixels wide**, so the
   evidence panel is docked on the right instead of hidden in a drawer.
   Light or dark is your choice; do not switch mid-take.
2. Open https://atlas.hulage.in/app and make sure your key is saved under
   Settings (the gear, top right).
3. **Wake the site first.** Ask any throwaway question — *not* the one below —
   and wait for the answer. The first question after a quiet spell waits
   about 15 seconds; that wait must not be in the recording.
4. Reload the page so the answer panel is empty again.
5. Do not ask the recorded question beforehand. A repeat inside an hour comes
   back instantly as a stored answer, and the stages will not be seen running.
6. Hide bookmarks, other tabs and notifications. Nothing with your key on
   screen: do not open Settings during the take.

Record with macOS: **Cmd + Shift + 5** → "Record Selected Portion" → drag
around the browser window → Record. Speak the lines or leave it silent and
add captions later — the words below work as either.

## The six shots

| # | Seconds | Do this | Say or caption this |
|---|---|---|---|
| 1 | 0–10 | Start on the empty console. Rest the pointer on the line that begins "This sheet holds". | "Atlas answers questions about a set of documents — here, the DuckDB 2.0 manual, published after today's AI models were trained." |
| 2 | 10–25 | Press the suggested question button (*What type does the literal X'CAFE' produce in DuckDB?*). Let the stages along the bottom light up one by one. | "It does not just call a model. It routes the question, searches two ways, checks whether what it found is enough, writes, and then checks its own answer." |
| 3 | 25–45 | The answer appears. Move the pointer slowly over a numbered marker in the answer, then click it. | "Every sentence carries a number. Each number is the exact passage that sentence came from." |
| 4 | 45–60 | In the evidence panel on the right, scroll once. Pause on a dimmed card. | "It also shows what it found and rejected. So when an answer is wrong, you can see why." |
| 5 | 60–75 | Point at the badge under the answer (for example **Supported**). | "And it grades itself. This badge says how far the answer is backed by those passages — most systems like this say nothing and let you assume." |
| 6 | 75–90 | Open the stage bar along the bottom to show the timings and the cost. Stop recording on this view. | "Each stage timed, the whole question costed. Atlas — live at atlas.hulage.in." |

## If a take goes wrong

- The answer came back instantly with "The stored answer to this same
  question" under it — the question was asked in the last hour. Wait, or
  change one word of the question and take it again.
- The badge is not **Supported** — keep the take if it says **Mixed**; the
  badge telling the truth is the point. Retake only on an error.
- A stage sat for a long time — the site had gone quiet again. Repeat step 3.

## When it is done

Keep the file as `.mp4`. Upload it to YouTube as **Unlisted** and give Claude
the link. Do not add the video file to this repository — it would be carried
inside every deploy.

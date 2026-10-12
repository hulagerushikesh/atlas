# Atlas Corpus Data

This directory holds the raw document corpora used by Atlas.

## fastapi/

**Source:** [fastapi/fastapi](https://github.com/fastapi/fastapi) — English documentation (`docs/en/docs/`)  
**License:** [MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE)  
**How to download:**

```bash
make fetch-corpus
```

**155 files, 1.4 MB**, pinned to commit `50113da1` — the commit the shipped
eval dataset's labels were written against. The pin is a constant in
`scripts/fetch_corpus.py`, because `manifest.json` is written *inside* the
gitignored corpus directory and so cannot be the source of a pin on a clean
clone. `--ref master` fetches what upstream has now and says loudly that it
is not the pin; `--max-files` is an opt-in sample, not a default (it defaulted
to 120 until 2026-10-12, which reproduced a corpus 35 files short and left 7
of the 16 dataset rows naming documents that did not exist).

Two files are written per fetch:

- `fastapi/manifest.json` — inside the corpus, gitignored: the ref requested,
  the resolved commit, per-file byte counts.
- `fastapi.files.json` — **tracked**: the 155 names, no content. This is what
  lets `tests/unit/evaluation/test_dataset_guards.py` resolve the dataset's
  labels on a clean clone, with no corpus and no network. Label resolution
  only ever needed the names, so the documents stay unvendored while the check
  still runs in CI. Do not edit it by hand — a listing that disagrees with a
  corpus that is present fails the suite.

**Why FastAPI docs?**
- MIT license — no restrictions on use or redistribution
- 155 markdown files, 1.4 MB — realistic but indexable in under 5 minutes
- Audience is developers, which matches Atlas's target user
- Rich enough for multi-hop, negation, and out-of-scope test questions

## Adding your own corpus

```bash
python scripts/ingest.py data/corpus/your-docs/ --chunker recursive
```

Atlas treats every subdirectory of `data/corpus/` the same way — drop any
license-clean markdown, PDF, or plain-text files in there and ingest them.
Note the license of any corpus you add in this README.

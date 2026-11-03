# Atlas Corpus Data

This directory holds the raw document corpora used by Atlas.

Corpora are registered in `scripts/fetch_corpus.py` as `Corpus` entries, each
pinned to a commit. `make fetch-corpus` downloads the current demo corpus;
`python scripts/fetch_corpus.py --corpus fastapi` still fetches the retired one.

## duckdb/ — the live demo corpus

**Source:** [duckdb/duckdb-web](https://github.com/duckdb/duckdb-web) — the 2.0
SQL reference and guides (`docs/2.0/sql/`, `docs/2.0/guides/`)
**License:** [MIT](https://github.com/duckdb/duckdb-web/blob/main/LICENSE)
**How to download:**

```bash
make fetch-corpus
```

**226 files, 1.4 MB**, pinned to commit `0f7f0f4e`. Ingested into the `duckdb`
namespace, which `ROUTER_DOMAIN_NAMESPACE` names, so the router is told what it
holds and the HTTP ingest route refuses writes to it.

**Why DuckDB 2.0 docs?** Because of the release date. DuckDB 2.0 shipped on
**2026-10-21**, after the training cutoff of every model that currently serves
this system. The documentation records behaviour that *changed* — `X'CAFE'` is
a `BLOB` where it used to be the `VARCHAR` `'xCAFE'`, `B'0101'` is a
`BITSTRING`, the PEG parser is the default and `enable_peg_parser()` is gone,
`CREATE TRIGGER` exists, a `STRUCT` may be empty, the `icu` extension no longer
depends on ICU. A model answering from memory does not say it does not know; it
gives the 1.x answer with full confidence. That makes retrieval's contribution
visible in a single side-by-side question, which is the one thing the FastAPI
corpus below could never do.

Also: MIT licensed, versioned doc trees upstream so the pin is meaningful,
developer audience, and dense enough for multi-hop, negation and out-of-scope
questions.

## fastapi/ — retired 2026-11-03

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

**Why it was retired.** Every frontier model has the FastAPI documentation in
its training data, so it answers these questions correctly without retrieval.
A demo whose questions the competition already knows cannot show what the
system does; the first outside user's reaction was that Copilot answered the
same questions fine, and he was right. The corpus itself was never the problem
— MIT, developer-facing, well structured, the right size — and it stays
registered and indexed under the `default` namespace so the two can be compared
side by side. `eval_data/fastapi_dataset.json` and its reports stay too: they
are the measurement history, and the numbers in them describe this corpus and
not the DuckDB one.

## Adding your own corpus

```bash
python scripts/ingest.py data/corpus/your-docs/ \
  --namespace your-docs --chunker recursive
```

Atlas treats every subdirectory of `data/corpus/` the same way — drop any
license-clean markdown, PDF, or plain-text files in there and ingest them.
Note the license of any corpus you add in this README.

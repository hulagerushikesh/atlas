# Atlas Corpus Data

This directory holds the raw document corpora used by Atlas.

## fastapi/

**Source:** [tiangolo/fastapi](https://github.com/tiangolo/fastapi) — English documentation (`docs/en/docs/`)  
**License:** [MIT](https://github.com/tiangolo/fastapi/blob/master/LICENSE)  
**How to download:**

```bash
python scripts/fetch_corpus.py --out data/corpus/fastapi
```

This downloads the English markdown files from the official FastAPI repository.
A `manifest.json` is written alongside the docs with the commit SHA, file list,
and byte counts so the fetch is reproducible.

**Why FastAPI docs?**
- MIT license — no restrictions on use or redistribution
- ~120 markdown files, ~350 KB — realistic but indexable in under 5 minutes
- Audience is developers, which matches Atlas's target user
- Rich enough for multi-hop, negation, and out-of-scope test questions

## Adding your own corpus

```bash
python scripts/ingest.py data/corpus/your-docs/ --chunker recursive
```

Atlas treats every subdirectory of `data/corpus/` the same way — drop any
license-clean markdown, PDF, or plain-text files in there and ingest them.
Note the license of any corpus you add in this README.

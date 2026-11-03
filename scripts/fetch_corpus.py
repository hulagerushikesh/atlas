"""
Fetch a bounded, license-clean technical-docs corpus from a public GitHub repo.

Each corpus is a pinned entry in the _CORPORA registry below. Pass --corpus to
pick one; the script downloads only that corpus's doc subtree(s), saves raw .md
files under data/corpus/<name>/, and writes a manifest.json recording the commit
SHA so runs are reproducible.

Default target: `duckdb` -- the DuckDB 2.0 SQL reference and guides.

Why DuckDB 2.0 and not the FastAPI docs that shipped first?
    The FastAPI docs are in every frontier model's training data, so a model
    answers questions about them correctly from memory and retrieval adds
    nothing a demo can show. The first outside user said exactly that: Copilot
    already answered the demo questions, so why switch. DuckDB 2.0.0 was
    released 2026-10-21, months after the training cutoff of every model Atlas
    runs against, and it changed SQL-level behaviour -- so a model does not
    merely lack the answer, it confidently gives the 1.x one. That is the gap
    retrieval closes, and it is visible in a single side-by-side question.

What any replacement corpus needs:
    - a permissive license (both entries here are MIT)
    - markdown, bounded: roughly 150-250 files so a re-index stays minutes/rupees
    - a developer audience, matching who Atlas is for
    - answers that are *in the text* and checkable, so eval labels can be written
    - ideally, facts a model gets wrong rather than merely does not know

Reproducibility:
    Each corpus pins a commit as a tracked constant in this file. A pin cannot
    be read out of the corpus manifest, because manifest.json lives inside the
    gitignored corpus directory -- a clean clone has no manifest, so a pin read
    from there would be read from the file the fetch itself produces. The pin is
    therefore source, not data. Pass --ref to move it deliberately; the manifest
    records which ref was used either way.

Usage:
    python scripts/fetch_corpus.py                       # the default corpus
    python scripts/fetch_corpus.py --corpus fastapi      # the retired one
    python scripts/fetch_corpus.py --ref main            # see what upstream has now
    python scripts/fetch_corpus.py --max-files 20        # a deliberate sample
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_API_TREES = "https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
_RAW_BASE = "https://raw.githubusercontent.com/{repo}/{ref}/"


@dataclass(frozen=True)
class Corpus:
    """One pinned, license-clean doc subtree, addressable by name."""

    repo: str
    # The commit this corpus's eval labels were written against. Moving it is a
    # deliberate act: fetch with --ref, re-run the dataset guards, and update
    # this constant in the same commit that updates the labels.
    pin: str
    # Subtrees to include. More than one is allowed because a versioned docs
    # site splits a single release across sibling directories.
    include: tuple[str, ...]
    # Stripped from every downloaded path to give the on-disk layout. It must be
    # a prefix of every entry in `include`, so the relative paths of two
    # subtrees cannot collide -- `docs/2.0/sql/x.md` and `docs/2.0/guides/x.md`
    # become `sql/x.md` and `guides/x.md`, not `x.md` twice.
    strip: str
    out: str
    license: str = "MIT"
    exclude: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = (".md",)
    note: str = ""

    def __post_init__(self) -> None:
        for prefix in self.include:
            if not prefix.startswith(self.strip):
                raise ValueError(
                    f"{self.repo}: include prefix {prefix!r} is not under "
                    f"strip prefix {self.strip!r}, so downloaded paths would "
                    f"escape the corpus directory"
                )


_CORPORA: dict[str, Corpus] = {
    # The demo corpus. DuckDB 2.0.0 shipped 2026-10-21 -- after every current
    # model's training cutoff -- so these pages answer questions a model gets
    # confidently wrong from memory. 131 SQL-reference files plus 95 guides.
    "duckdb": Corpus(
        repo="duckdb/duckdb-web",
        pin="0f7f0f4e2ee07518b126eb51cdb831ac916d9d4e",
        include=("docs/2.0/sql/", "docs/2.0/guides/"),
        strip="docs/2.0/",
        out="data/corpus/duckdb",
        note="DuckDB 2.0 SQL reference + guides",
    ),
    # Retired as the demo corpus on 2026-11-03, kept fetchable: the shipped
    # fastapi eval dataset and its labels are pinned to this commit, and the
    # dataset guards still resolve against the tracked file listing.
    # At this commit the filter matches 155 files, and at master on 2026-10-12
    # it matched 156 -- file *contents* move without the count moving at all,
    # which is why the pin is a commit and not a branch.
    "fastapi": Corpus(
        repo="fastapi/fastapi",
        pin="50113da16fec53b66b80d75e80a89296de4fa5a5",
        include=("docs/en/docs/",),
        strip="docs/en/docs/",
        out="data/corpus/fastapi",
        exclude=("docs/en/docs/img/", "docs/en/docs/js/"),
        note="FastAPI documentation (retired demo corpus)",
    ),
}

_DEFAULT_CORPUS = "duckdb"


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-corpus-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _fetch_raw(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-corpus-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch(
    corpus: Corpus, out_dir: Path, max_files: int | None, ref: str | None = None
) -> None:
    ref = ref or corpus.pin
    pinned = ref == corpus.pin
    print(f"Fetching {corpus.repo} tree at {ref[:12]}{'' if pinned else ' (NOT the pin)'}…")
    tree_data = _fetch_json(_API_TREES.format(repo=corpus.repo, ref=ref))

    # GitHub resolves a ref or commit-ish here and echoes back the commit sha,
    # so this is a commit, not the tree object's own sha -- verified against
    # git/commits/<sha> on 2026-10-12, because the field is named commit_sha
    # and a mislabelled sha would make the pin unusable.
    sha = tree_data.get("sha", "unknown")
    if pinned and sha != corpus.pin:
        raise SystemExit(
            f"asked for the pinned commit {corpus.pin} but GitHub answered "
            f"{sha}; refusing to write a manifest that claims the pin"
        )

    md_paths = sorted(
        item["path"]
        for item in tree_data.get("tree", [])
        if item["type"] == "blob"
        and any(item["path"].startswith(inc) for inc in corpus.include)
        and item["path"].endswith(corpus.suffixes)
        and not any(item["path"].startswith(ex) for ex in corpus.exclude)
    )

    # No default cap. The cap used to default to 120 while the corpus the
    # dataset was labelled against holds 155 files, so `make fetch-corpus`
    # as documented reproduced a corpus 35 files short -- and the labels for
    # those 35 then resolve against nothing. A cap is a sampling knob, so it
    # is now opt-in and says so when it bites.
    found = len(md_paths)
    if max_files is not None and found > max_files:
        md_paths = md_paths[:max_files]
        print(f"Found {found} markdown files, capped at {max_files} by --max-files")
    else:
        print(f"Found {found} markdown files")

    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict] = []
    failed: list[tuple[str, str]] = []

    # Every blob comes from the resolved sha, never from `ref`: a branch can
    # move between the tree listing and the downloads, which would mix two
    # commits into one corpus and record only one of them in the manifest.
    raw_base = _RAW_BASE.format(repo=corpus.repo, ref=sha)

    for i, path in enumerate(md_paths, 1):
        rel = path.removeprefix(corpus.strip)
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        raw_url = raw_base + path
        try:
            content = _fetch_raw(raw_url)
            dest.write_bytes(content)
            downloaded.append({"path": rel, "source_url": raw_url, "bytes": len(content)})
            print(f"  [{i}/{len(md_paths)}] {rel} ({len(content):,} bytes)")
        except Exception as exc:
            # Not a skip. A corpus missing files is a corpus the dataset's
            # labels cannot resolve against, and the old code printed SKIP to
            # stderr and exited 0 -- a partial download that reported success.
            failed.append((rel, str(exc)))
            print(f"  [{i}/{len(md_paths)}] FAILED {rel}: {exc}", file=sys.stderr)

        # Stay under GitHub's unauthenticated rate limit (60 req/min)
        if i % 50 == 0:
            time.sleep(2)

    manifest = {
        "repo": corpus.repo,
        "note": corpus.note,
        "include": list(corpus.include),
        "ref_requested": ref,
        "is_pinned_commit": pinned,
        "commit_sha": sha,
        "license": corpus.license,
        "license_url": f"https://github.com/{corpus.repo}/blob/{sha}/LICENSE",
        "files_matched": found,
        "files_downloaded": len(downloaded),
        "max_files": max_files,
        "files": downloaded,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # The tracked sidecar: names only, written beside the corpus rather than
    # inside it so .gitignore's `data/corpus/*/` does not swallow it. It is
    # what lets the dataset guards resolve labels on a clean clone, with no
    # corpus and no network, so it must be regenerated by the same run that
    # changes the corpus -- a listing maintained by hand is a second source
    # of truth, and test_dataset_guards fails if the two disagree.
    listing = out_dir.with_name(out_dir.name + ".files.json")
    listing.write_text(
        json.dumps(
            {
                "_comment": (
                    "Names only, no content. The documents themselves are "
                    "third-party and gitignored (see .gitignore); this list is "
                    "what lets the eval dataset's labels be resolved on a clean "
                    "clone, with no corpus and no network. Regenerated by "
                    "scripts/fetch_corpus.py; a stale list fails "
                    "tests/unit/evaluation/test_dataset_guards.py."
                ),
                "repo": corpus.repo,
                "commit_sha": sha,
                "files": sorted(f["path"] for f in downloaded),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Listing written to {listing}")
    total_kb = sum(f["bytes"] for f in downloaded) // 1024
    print(f"\nWrote {len(downloaded)} files, {total_kb} KB → {out_dir}")
    print(f"Manifest written to {out_dir / 'manifest.json'}")

    if failed:
        # Exit non-zero with the manifest already on disk, so the partial
        # state is inspectable rather than guessed at.
        listed = "\n".join(f"  {rel}: {why}" for rel, why in failed[:10])
        more = f"\n  ... and {len(failed) - 10} more" if len(failed) > 10 else ""
        raise SystemExit(
            f"{len(failed)} of {len(md_paths)} files did not download, so this "
            f"corpus is incomplete and the dataset's labels will not resolve "
            f"against it:\n{listed}{more}"
        )
    if not pinned:
        print(
            f"\nNOTE: fetched {ref}, not the pin {corpus.pin[:12]}. The shipped "
            "dataset's labels were written against the pin; re-run the dataset "
            "guards before trusting anything measured on this corpus.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a pinned technical-docs corpus")
    parser.add_argument(
        "--corpus",
        default=_DEFAULT_CORPUS,
        choices=sorted(_CORPORA),
        help=f"Which registered corpus to fetch (default: {_DEFAULT_CORPUS})",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory; defaults to the corpus's own data/corpus/<name>",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on files to download; omit to fetch every match",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Commit, branch or tag to fetch (default: the chosen corpus's pin)",
    )
    args = parser.parse_args()

    corpus = _CORPORA[args.corpus]
    fetch(corpus, Path(args.out or corpus.out), args.max_files, args.ref)


if __name__ == "__main__":
    main()

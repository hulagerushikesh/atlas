"""
Fetch a bounded, license-clean technical-docs corpus from a public GitHub repo.

Default target: the FastAPI documentation (MIT-licensed markdown files).
The script downloads only the English docs/ subtree from the official repo,
saves raw .md files to data/corpus/fastapi/, and writes a manifest.json that
records the commit SHA so runs are reproducible.

Why FastAPI docs?
    - MIT license — clean for any use
    - ~120 markdown files, ~350 KB of text — large enough to be realistic,
      small enough to index in under 5 minutes on a laptop
    - Developer audience matches Atlas's target user (the "tired of grepping"
      developer who wants cited answers)
    - Rich enough to produce interesting multi-hop and negation questions

Reproducibility:
    The fetch is pinned to _PINNED_COMMIT, a tracked constant in this file.
    It cannot be read out of the corpus manifest, because manifest.json lives
    inside the gitignored corpus directory -- a clean clone has no manifest,
    so a pin read from there would be read from the file the fetch itself
    produces. The pin is therefore source, not data. Pass --ref to move it
    deliberately; the manifest records which ref was used either way.

Usage:
    python scripts/fetch_corpus.py [--out data/corpus/fastapi]
    python scripts/fetch_corpus.py --ref master          # see what upstream has now
    python scripts/fetch_corpus.py --max-files 20        # a deliberate sample
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

_REPO = "fastapi/fastapi"

# The commit the shipped eval dataset was labelled against (2026-09-01,
# "Update release notes"). Fetching `master` instead is not a smaller
# difference than it sounds: at this commit the filter below matches 155
# files, and at master on 2026-10-12 it matches 156 -- and file *contents*
# move without the count moving at all. Resolving labels pinned on
# 2026-09-27 against today's docs makes the dataset guards fail on somebody
# else's commit, which is worse than a gate that admits it did not run.
# To move the pin: fetch with --ref master, re-run the dataset guards, and
# update this constant in the same commit that updates the labels.
_PINNED_COMMIT = "50113da16fec53b66b80d75e80a89296de4fa5a5"

_API_TREES = "https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
_RAW_BASE = "https://raw.githubusercontent.com/{repo}/{ref}/"

# Only grab English docs to stay within a predictable size budget
_INCLUDE_PREFIX = "docs/en/docs/"
_EXCLUDE_PREFIXES = ("docs/en/docs/img/", "docs/en/docs/js/")


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-corpus-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _fetch_raw(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-corpus-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch(out_dir: Path, max_files: int | None, ref: str = _PINNED_COMMIT) -> None:
    pinned = ref == _PINNED_COMMIT
    print(f"Fetching {_REPO} tree at {ref[:12]}{'' if pinned else ' (NOT the pin)'}…")
    tree_data = _fetch_json(_API_TREES.format(repo=_REPO, ref=ref))

    # GitHub resolves a ref or commit-ish here and echoes back the commit sha,
    # so this is a commit, not the tree object's own sha -- verified against
    # git/commits/<sha> on 2026-10-12, because the field is named commit_sha
    # and a mislabelled sha would make the pin unusable.
    sha = tree_data.get("sha", "unknown")
    if pinned and sha != _PINNED_COMMIT:
        raise SystemExit(
            f"asked for the pinned commit {_PINNED_COMMIT} but GitHub answered "
            f"{sha}; refusing to write a manifest that claims the pin"
        )

    md_paths = [
        item["path"]
        for item in tree_data.get("tree", [])
        if item["type"] == "blob"
        and item["path"].startswith(_INCLUDE_PREFIX)
        and item["path"].endswith(".md")
        and not any(item["path"].startswith(ex) for ex in _EXCLUDE_PREFIXES)
    ]

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
    raw_base = _RAW_BASE.format(repo=_REPO, ref=sha)

    for i, path in enumerate(md_paths, 1):
        rel = path.removeprefix(_INCLUDE_PREFIX)
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
        "repo": _REPO,
        "ref_requested": ref,
        "is_pinned_commit": pinned,
        "commit_sha": sha,
        "license": "MIT",
        "license_url": f"https://github.com/{_REPO}/blob/{sha}/LICENSE",
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
                "repo": _REPO,
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
            f"\nNOTE: fetched {ref}, not the pin {_PINNED_COMMIT[:12]}. The shipped "
            "dataset's labels were written against the pin; re-run the dataset "
            "guards before trusting anything measured on this corpus.",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch FastAPI docs corpus")
    parser.add_argument("--out", default="data/corpus/fastapi", help="Output directory")
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Optional cap on files to download; omit to fetch every match (155 at the pin)",
    )
    parser.add_argument(
        "--ref",
        default=_PINNED_COMMIT,
        help=f"Commit, branch or tag to fetch (default: the pin {_PINNED_COMMIT[:12]})",
    )
    args = parser.parse_args()

    fetch(Path(args.out), args.max_files, args.ref)


if __name__ == "__main__":
    main()

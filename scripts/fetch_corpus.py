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

Usage:
    python scripts/fetch_corpus.py [--out data/corpus/fastapi] [--max-files 120]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

# GitHub raw content URL template
_API_TREES = "https://api.github.com/repos/tiangolo/fastapi/git/trees/master?recursive=1"
_RAW_BASE = "https://raw.githubusercontent.com/tiangolo/fastapi/master/"

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


def fetch(out_dir: Path, max_files: int) -> None:
    print("Fetching FastAPI repo tree from GitHub…")
    tree_data = _fetch_json(_API_TREES)
    sha = tree_data.get("sha", "unknown")

    md_paths = [
        item["path"]
        for item in tree_data.get("tree", [])
        if item["type"] == "blob"
        and item["path"].startswith(_INCLUDE_PREFIX)
        and item["path"].endswith(".md")
        and not any(item["path"].startswith(ex) for ex in _EXCLUDE_PREFIXES)
    ]

    md_paths = md_paths[:max_files]
    print(f"Found {len(md_paths)} markdown files (capped at {max_files})")

    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict] = []

    for i, path in enumerate(md_paths, 1):
        rel = path.removeprefix(_INCLUDE_PREFIX)
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        raw_url = _RAW_BASE + path
        try:
            content = _fetch_raw(raw_url)
            dest.write_bytes(content)
            downloaded.append({"path": rel, "source_url": raw_url, "bytes": len(content)})
            print(f"  [{i}/{len(md_paths)}] {rel} ({len(content):,} bytes)")
        except Exception as exc:
            print(f"  [{i}/{len(md_paths)}] SKIP {rel}: {exc}", file=sys.stderr)

        # Stay under GitHub's unauthenticated rate limit (60 req/min)
        if i % 50 == 0:
            time.sleep(2)

    manifest = {
        "repo": "tiangolo/fastapi",
        "branch": "master",
        "commit_sha": sha,
        "license": "MIT",
        "license_url": "https://github.com/tiangolo/fastapi/blob/master/LICENSE",
        "files_downloaded": len(downloaded),
        "files": downloaded,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    total_kb = sum(f["bytes"] for f in downloaded) // 1024
    print(f"\nDone — {len(downloaded)} files, {total_kb} KB → {out_dir}")
    print(f"Manifest written to {out_dir / 'manifest.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch FastAPI docs corpus")
    parser.add_argument("--out", default="data/corpus/fastapi", help="Output directory")
    parser.add_argument("--max-files", type=int, default=120, help="Cap on files to download")
    args = parser.parse_args()

    fetch(Path(args.out), args.max_files)


if __name__ == "__main__":
    main()

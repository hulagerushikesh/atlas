"""
scripts/fetch_corpus.py: the fetch is pinned, complete, or it fails.

Nothing under scripts/ had tests before this file. `make lint` covers the
directory, so ruff and mypy had opinions about the fetcher while no test ever
executed a line of it -- and the three defects pinned below all survived in
that gap. The network is stubbed, so these run in CI.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fetch_corpus.py"


def _load() -> Any:
    # scripts/ is not a package, so import by path rather than adding it to
    # sys.path, which would leak module names like `ingest` into the suite.
    spec = importlib.util.spec_from_file_location("atlas_fetch_corpus", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fc() -> Any:
    return _load()


@pytest.fixture
def corpus(fc: Any) -> Any:
    """The retired FastAPI entry, kept in the registry and used as the fixture.

    These tests prove properties of the fetcher, not of whichever corpus is
    currently the demo one, so they run against a fixed entry rather than
    `_DEFAULT_CORPUS`. FastAPI is the right one: `_DOCS` below is shaped like
    its `docs/en/docs/` subtree, and pinning the tests to it means swapping the
    demo corpus again cannot quietly rewrite what they assert.
    """
    return fc._CORPORA["fastapi"]


def _tree(sha: str, paths: list[str]) -> dict:
    return {"sha": sha, "tree": [{"type": "blob", "path": p} for p in paths]}


_DOCS = [f"docs/en/docs/page{i}.md" for i in range(5)]


@pytest.fixture
def stubbed(fc: Any, corpus: Any, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record every URL the fetcher asks for; serve plausible bytes."""
    calls: dict[str, list[str]] = {"json": [], "raw": []}

    def fake_json(url: str) -> dict:
        calls["json"].append(url)
        return _tree(corpus.pin, [*_DOCS, "docs/en/docs/img/logo.png", "README.md"])

    def fake_raw(url: str) -> bytes:
        calls["raw"].append(url)
        return b"# page\n"

    monkeypatch.setattr(fc, "_fetch_json", fake_json)
    monkeypatch.setattr(fc, "_fetch_raw", fake_raw)
    return calls


class TestThePin:
    def test_the_default_fetch_asks_for_the_pinned_commit_not_a_branch(
        self, fc: Any, corpus: Any, stubbed: dict, tmp_path: Path
    ) -> None:
        fc.fetch(corpus, tmp_path, None)
        assert corpus.pin in stubbed["json"][0]
        assert "/master?" not in stubbed["json"][0]

    def test_blobs_come_from_the_resolved_sha_not_the_ref_asked_for(
        self, fc: Any, corpus: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A branch can move between the tree listing and the downloads. If the
        # raw URLs carried `ref`, the corpus would mix two commits and the
        # manifest would record only one of them.
        resolved = "f" * 40
        monkeypatch.setattr(fc, "_fetch_json", lambda url: _tree(resolved, _DOCS))
        seen: list[str] = []
        monkeypatch.setattr(
            fc, "_fetch_raw", lambda url: (seen.append(url), b"# page\n")[1]
        )

        fc.fetch(corpus, tmp_path, None, ref="master")

        assert seen, "no blob was fetched"
        assert all(resolved in u for u in seen)
        assert not any("/master/" in u for u in seen)

    def test_a_pin_that_resolves_to_something_else_refuses_to_write(
        self, fc: Any, corpus: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(fc, "_fetch_json", lambda url: _tree("0" * 40, _DOCS))
        monkeypatch.setattr(fc, "_fetch_raw", lambda url: b"# page\n")

        with pytest.raises(SystemExit) as exc:
            fc.fetch(corpus, tmp_path, None)

        assert corpus.pin in str(exc.value)
        assert not (tmp_path / "manifest.json").exists()

    def test_fetching_a_branch_records_that_it_was_not_the_pin(
        self, fc: Any, corpus: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(fc, "_fetch_json", lambda url: _tree("a" * 40, _DOCS))
        monkeypatch.setattr(fc, "_fetch_raw", lambda url: b"# page\n")

        fc.fetch(corpus, tmp_path, None, ref="master")

        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["is_pinned_commit"] is False
        assert manifest["ref_requested"] == "master"
        assert manifest["commit_sha"] == "a" * 40


class TestTheCommittedListing:
    """The tracked listing must be exactly what this script would write.

    Caught by running `make fetch-corpus` in a genuine clean clone, which is
    the only place that shows it: the first committed listing was generated
    from the corpus already on my machine, whose manifest still said
    `tiangolo/fastapi`, while the script writes the canonical
    `fastapi/fastapi`. A fetch therefore dirtied the tree, which is how a
    generated file stops being trusted. The dataset guards only read `files`,
    so nothing there could notice.
    """

    def test_every_registered_corpus_listing_agrees_with_this_script(self, fc: Any) -> None:
        # Every entry, not just the current demo one: a retired corpus whose
        # listing has drifted still dirties the tree the moment anyone fetches
        # it, which is the failure this class exists for.
        root = Path(fc.__file__).resolve().parents[1]
        for name, entry in fc._CORPORA.items():
            path = root / f"{entry.out}.files.json"
            assert path.is_file(), f"{name}: no tracked listing at {path}"
            listing = json.loads(path.read_text())
            assert listing["repo"] == entry.repo, name
            assert listing["commit_sha"] == entry.pin, name


class TestCompleteness:
    def test_every_match_is_fetched_when_no_cap_is_given(
        self, fc: Any, corpus: Any, stubbed: dict, tmp_path: Path
    ) -> None:
        # The cap used to default to 120 against a 155-file corpus, so the
        # documented `make fetch-corpus` produced a corpus 35 files short and
        # 7 of the 16 dataset rows then named documents that did not exist.
        fc.fetch(corpus, tmp_path, None)
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["files_matched"] == len(_DOCS)
        assert manifest["files_downloaded"] == len(_DOCS)
        assert manifest["max_files"] is None

    def test_a_cap_applies_only_when_asked_for(
        self, fc: Any, corpus: Any, stubbed: dict, tmp_path: Path
    ) -> None:
        fc.fetch(corpus, tmp_path, 2)
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert (manifest["files_matched"], manifest["files_downloaded"]) == (len(_DOCS), 2)

    def test_a_failed_download_exits_non_zero_and_names_the_file(
        self, fc: Any, corpus: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # This used to print SKIP to stderr and exit 0: a partial corpus that
        # reported success, which the dataset's labels cannot resolve against.
        monkeypatch.setattr(fc, "_fetch_json", lambda url: _tree(corpus.pin, _DOCS))

        def flaky(url: str) -> bytes:
            if url.endswith("page3.md"):
                raise OSError("502 Bad Gateway")
            return b"# page\n"

        monkeypatch.setattr(fc, "_fetch_raw", flaky)

        with pytest.raises(SystemExit) as exc:
            fc.fetch(corpus, tmp_path, None)

        message = str(exc.value)
        assert "page3.md" in message
        assert "502 Bad Gateway" in message
        # The manifest is written before the exit so the partial state is
        # inspectable, and it must not claim the files it does not have.
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["files_downloaded"] == len(_DOCS) - 1

    def test_the_command_line_itself_defaults_to_no_cap_and_to_the_pin(
        self, fc: Any, corpus: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The regression this guards against lived in argparse, not in
        # fetch(), so every test that calls fetch() directly would have
        # stayed green while `make fetch-corpus` kept truncating at 120.
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            fc,
            "fetch",
            lambda chosen, out, max_files, ref: seen.update(
                chosen=chosen, out=out, max_files=max_files, ref=ref
            ),
        )
        monkeypatch.setattr(sys, "argv", ["fetch_corpus.py"])

        fc.main()

        assert seen["max_files"] is None
        # No --ref means None, and fetch() substitutes the chosen corpus's pin
        # -- proved by test_the_default_fetch_asks_for_the_pinned_commit. The
        # pin must not be baked in here, or --ref could never override it.
        assert seen["ref"] is None
        assert seen["chosen"] is fc._CORPORA[fc._DEFAULT_CORPUS]
        assert str(seen["out"]) == seen["chosen"].out

    def test_the_bare_command_line_fetches_the_demo_corpus(self, fc: Any) -> None:
        # The demo corpus swapped from FastAPI to DuckDB 2.0 on 2026-11-03,
        # because the FastAPI docs are in the training data of every model that
        # serves this system, so retrieval could not be shown to add anything.
        # `make fetch-corpus` must land on whatever is current without flags.
        assert fc._DEFAULT_CORPUS == "duckdb"
        assert fc._CORPORA["duckdb"].out == "data/corpus/duckdb"

    def test_images_and_files_outside_the_docs_subtree_are_not_fetched(
        self, fc: Any, corpus: Any, stubbed: dict, tmp_path: Path
    ) -> None:
        fc.fetch(corpus, tmp_path, None)
        assert not any("logo.png" in u or "README.md" in u for u in stubbed["raw"])


class TestTheRegistry:
    """A corpus entry that is wrong should fail at import, not mid-download."""

    def test_every_entry_keeps_its_downloads_inside_its_own_directory(
        self, fc: Any
    ) -> None:
        # `rel = path.removeprefix(corpus.strip)` is what places a downloaded
        # file. An include prefix that is not under the strip prefix leaves the
        # path absolute-ish or outside `out`, so files land somewhere nobody
        # looks. __post_init__ refuses it; this proves the refusal is live.
        for name, entry in fc._CORPORA.items():
            for prefix in entry.include:
                assert prefix.startswith(entry.strip), f"{name}: {prefix}"

    def test_an_include_prefix_outside_the_strip_prefix_is_rejected(
        self, fc: Any
    ) -> None:
        with pytest.raises(ValueError, match="not under"):
            fc.Corpus(
                repo="example/docs",
                pin="0" * 40,
                include=("somewhere/else/",),
                strip="docs/",
                out="data/corpus/example",
            )

    def test_the_default_corpus_is_registered(self, fc: Any) -> None:
        assert fc._DEFAULT_CORPUS in fc._CORPORA

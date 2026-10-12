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


def _tree(sha: str, paths: list[str]) -> dict:
    return {"sha": sha, "tree": [{"type": "blob", "path": p} for p in paths]}


_DOCS = [f"docs/en/docs/page{i}.md" for i in range(5)]


@pytest.fixture
def stubbed(fc: Any, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record every URL the fetcher asks for; serve plausible bytes."""
    calls: dict[str, list[str]] = {"json": [], "raw": []}

    def fake_json(url: str) -> dict:
        calls["json"].append(url)
        return _tree(fc._PINNED_COMMIT, [*_DOCS, "docs/en/docs/img/logo.png", "README.md"])

    def fake_raw(url: str) -> bytes:
        calls["raw"].append(url)
        return b"# page\n"

    monkeypatch.setattr(fc, "_fetch_json", fake_json)
    monkeypatch.setattr(fc, "_fetch_raw", fake_raw)
    return calls


class TestThePin:
    def test_the_default_fetch_asks_for_the_pinned_commit_not_a_branch(
        self, fc: Any, stubbed: dict, tmp_path: Path
    ) -> None:
        fc.fetch(tmp_path, None)
        assert fc._PINNED_COMMIT in stubbed["json"][0]
        assert "/master?" not in stubbed["json"][0]

    def test_blobs_come_from_the_resolved_sha_not_the_ref_asked_for(
        self, fc: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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

        fc.fetch(tmp_path, None, ref="master")

        assert seen, "no blob was fetched"
        assert all(resolved in u for u in seen)
        assert not any("/master/" in u for u in seen)

    def test_a_pin_that_resolves_to_something_else_refuses_to_write(
        self, fc: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(fc, "_fetch_json", lambda url: _tree("0" * 40, _DOCS))
        monkeypatch.setattr(fc, "_fetch_raw", lambda url: b"# page\n")

        with pytest.raises(SystemExit) as exc:
            fc.fetch(tmp_path, None)

        assert fc._PINNED_COMMIT in str(exc.value)
        assert not (tmp_path / "manifest.json").exists()

    def test_fetching_a_branch_records_that_it_was_not_the_pin(
        self, fc: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(fc, "_fetch_json", lambda url: _tree("a" * 40, _DOCS))
        monkeypatch.setattr(fc, "_fetch_raw", lambda url: b"# page\n")

        fc.fetch(tmp_path, None, ref="master")

        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["is_pinned_commit"] is False
        assert manifest["ref_requested"] == "master"
        assert manifest["commit_sha"] == "a" * 40


class TestCompleteness:
    def test_every_match_is_fetched_when_no_cap_is_given(
        self, fc: Any, stubbed: dict, tmp_path: Path
    ) -> None:
        # The cap used to default to 120 against a 155-file corpus, so the
        # documented `make fetch-corpus` produced a corpus 35 files short and
        # 7 of the 16 dataset rows then named documents that did not exist.
        fc.fetch(tmp_path, None)
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["files_matched"] == len(_DOCS)
        assert manifest["files_downloaded"] == len(_DOCS)
        assert manifest["max_files"] is None

    def test_a_cap_applies_only_when_asked_for(
        self, fc: Any, stubbed: dict, tmp_path: Path
    ) -> None:
        fc.fetch(tmp_path, 2)
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert (manifest["files_matched"], manifest["files_downloaded"]) == (len(_DOCS), 2)

    def test_a_failed_download_exits_non_zero_and_names_the_file(
        self, fc: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # This used to print SKIP to stderr and exit 0: a partial corpus that
        # reported success, which the dataset's labels cannot resolve against.
        monkeypatch.setattr(fc, "_fetch_json", lambda url: _tree(fc._PINNED_COMMIT, _DOCS))

        def flaky(url: str) -> bytes:
            if url.endswith("page3.md"):
                raise OSError("502 Bad Gateway")
            return b"# page\n"

        monkeypatch.setattr(fc, "_fetch_raw", flaky)

        with pytest.raises(SystemExit) as exc:
            fc.fetch(tmp_path, None)

        message = str(exc.value)
        assert "page3.md" in message
        assert "502 Bad Gateway" in message
        # The manifest is written before the exit so the partial state is
        # inspectable, and it must not claim the files it does not have.
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["files_downloaded"] == len(_DOCS) - 1

    def test_the_command_line_itself_defaults_to_no_cap_and_to_the_pin(
        self, fc: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The regression this guards against lived in argparse, not in
        # fetch(), so every test that calls fetch() directly would have
        # stayed green while `make fetch-corpus` kept truncating at 120.
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            fc,
            "fetch",
            lambda out, max_files, ref: seen.update(
                out=out, max_files=max_files, ref=ref
            ),
        )
        monkeypatch.setattr(sys, "argv", ["fetch_corpus.py"])

        fc.main()

        assert seen["max_files"] is None
        assert seen["ref"] == fc._PINNED_COMMIT
        assert str(seen["out"]) == "data/corpus/fastapi"

    def test_images_and_files_outside_the_docs_subtree_are_not_fetched(
        self, fc: Any, stubbed: dict, tmp_path: Path
    ) -> None:
        fc.fetch(tmp_path, None)
        assert not any("logo.png" in u or "README.md" in u for u in stubbed["raw"])

"""
scripts/ingest.py: say which Qdrant the money is about to be spent on.

`scripts/` is not a package, so the module is loaded by path the way
test_fetch_corpus.py does it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ingest.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("atlas_ingest", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ing() -> Any:
    return _load()


class TestTheDestinationIsNamed:
    """
    The banner printed the namespace and the file but never the cluster. A
    developer's `.env` points at the managed cluster as soon as they have
    deployed, while the README's `.env.example` points at the local container,
    so the documented quick-start ingest writes a new namespace into production
    with nothing on screen to say which Qdrant answered.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:6333",
            "http://127.0.0.1:6333",
            "http://qdrant:6333",  # the compose service name, from the api container
        ],
    )
    def test_a_local_url_is_not_flagged(self, ing: Any, url: str) -> None:
        out = ing._describe_destination(url, "atlas_chunks")
        assert "NOT local" not in out
        assert "atlas_chunks" in out

    def test_a_managed_cluster_is_flagged(self, ing: Any) -> None:
        # Shaped like a managed endpoint, with a made-up cluster id: this repo
        # is public, and the real endpoint is where a stolen key would be aimed.
        out = ing._describe_destination(
            "https://00000000-1111-2222-3333-444444444444.us-west-1-0.aws.cloud.qdrant.io:6333",
            "atlas_chunks",
        )
        assert "NOT local" in out, (
            "a cloud url must be called out; this is the line that stops a "
            "quick-start ingest landing in production"
        )

    def test_the_host_is_shown_so_two_clusters_are_distinguishable(
        self, ing: Any
    ) -> None:
        a = ing._describe_destination("https://aaa.cloud.qdrant.io:6333", "c")
        b = ing._describe_destination("https://bbb.cloud.qdrant.io:6333", "c")
        assert a != b
        assert "aaa.cloud.qdrant.io" in a

    def test_no_credential_is_printed_even_if_the_url_carries_one(
        self, ing: Any
    ) -> None:
        # urlsplit keeps userinfo in netloc, so this is worth pinning rather
        # than assuming: a url is not a secret but it can be made to hold one.
        out = ing._describe_destination(
            "https://user:sekrit@host.cloud.qdrant.io:6333", "c"
        )
        assert "sekrit" not in out

    def test_the_banner_and_the_dry_run_both_report_it(self) -> None:
        # Both call sites, because the dry run is exactly when someone is
        # checking what the command is about to do.
        source = _SCRIPT.read_text()
        assert 'print(f"Writing to: {destination}")' in source
        assert 'print(f"Would write to: {destination}")' in source

"""
Tests for deterministic context headers.

fq-012's target page was never retrieved at all: its chunks discuss `Query`
and `Annotated` without repeating what the page is about, because a reader
has the title on screen. These headers put that title back into the indexed
text.
"""

from __future__ import annotations

from atlas.ingestion.hashing import hash_text
from atlas.ingestion.headers import (
    apply_context_headers,
    context_header,
    heading_trail,
    humanise_source,
)
from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType

DOC = """# Query Parameters and String Validations

Intro prose.

## Add regular expressions

Regex prose.

### Pydantic v1

Version-specific prose.

## Required parameters

Required prose.
"""


def _chunk(source: str, start: int, content: str = "body") -> Chunk:
    return Chunk(
        content=content,
        metadata=ChunkMetadata(
            doc_id="d1", source=source, doc_type=DocumentType.MARKDOWN,
            chunk_index=0, start_char=start, end_char=start + len(content),
            content_hash=hash_text(content),
        ),
    )


class TestHumaniseSource:
    def test_path_becomes_the_words_a_question_would_use(self) -> None:
        # The sparse tokenizer splits on / and -, so these become the exact
        # tokens fq-012 asks with.
        assert (
            humanise_source("tutorial/query-params-str-validations.md")
            == "tutorial query params str validations"
        )

    def test_extension_is_dropped(self) -> None:
        # ".md" is on every chunk in the corpus, so it carries no BM25 signal
        # while still costing an embedding position.
        assert "md" not in humanise_source("async.md").split()

    def test_underscores_split_too(self) -> None:
        assert humanise_source("advanced/custom_response.md") == "advanced custom response"

    def test_bare_filename_survives(self) -> None:
        assert humanise_source("async.md") == "async"

    def test_corpus_root_is_stripped(self) -> None:
        # Without this every chunk in the corpus opened with "data corpus
        # fastapi": three tokens paid for 4,020 times that no query can
        # discriminate on.
        assert (
            humanise_source(
                "data/corpus/fastapi/tutorial/body.md", "data/corpus/fastapi"
            )
            == "tutorial body"
        )

    def test_path_outside_the_root_is_kept_whole(self) -> None:
        # A mixed-origin ingest: guessing which leading segments are noise
        # would be worse than carrying them.
        assert (
            humanise_source("other/place/body.md", "data/corpus/fastapi")
            == "other place body"
        )


class TestHeadingTrail:
    def test_trail_is_outermost_first(self) -> None:
        assert heading_trail(DOC, DOC.index("Regex prose")) == [
            "Query Parameters and String Validations",
            "Add regular expressions",
        ]

    def test_deeper_heading_extends_the_trail(self) -> None:
        assert heading_trail(DOC, DOC.index("Version-specific")) == [
            "Query Parameters and String Validations",
            "Add regular expressions",
            "Pydantic v1",
        ]

    def test_sibling_replaces_rather_than_nests(self) -> None:
        # "Required parameters" is an H2 following an H2 and an H3; neither
        # is still in force.
        assert heading_trail(DOC, DOC.index("Required prose")) == [
            "Query Parameters and String Validations",
            "Required parameters",
        ]

    def test_text_before_any_heading_has_no_trail(self) -> None:
        assert heading_trail(DOC, 0) == []

    def test_mkdocs_anchor_attributes_are_stripped(self) -> None:
        # `## Default values { #default-values }` — the brace block is the
        # heading's own words hyphenated, so keeping it pays to embed
        # everything twice and tells BM25 nothing new.
        doc = (
            "# Query Parameters { #query-parameters }\n\n"
            "## Default values { #default-values }\n\nprose"
        )
        assert heading_trail(doc, doc.index("prose")) == [
            "Query Parameters",
            "Default values",
        ]

    def test_headings_after_the_chunk_are_ignored(self) -> None:
        trail = heading_trail(DOC, DOC.index("Intro prose"))
        assert "Add regular expressions" not in trail


class TestContextHeader:
    def test_header_carries_path_and_trail(self) -> None:
        header = context_header("tutorial/body.md", DOC, DOC.index("Regex prose"))
        assert header.startswith("tutorial body\n")
        assert "Add regular expressions" in header
        assert header.endswith("\n\n")

    def test_page_title_is_not_repeated_when_it_matches_the_path(self) -> None:
        # mkdocs pages usually name themselves in their own H1, and paying to
        # embed the same words twice buys nothing.
        doc = "# Async\n\nprose here"
        header = context_header("async.md", doc, doc.index("prose"))
        assert header.lower().count("async") == 1
        assert header.strip() == "async"

    def test_deeper_headings_survive_the_title_dedupe(self) -> None:
        doc = "# Async\n\n## Concurrency and burgers\n\nprose here"
        header = context_header("async.md", doc, doc.index("prose"))
        assert "Concurrency and burgers" in header

    def test_no_source_and_no_headings_gives_nothing(self) -> None:
        assert context_header("", "plain text", 0) == ""


class TestApplyContextHeaders:
    def test_content_gains_the_header(self) -> None:
        chunks = [_chunk("tutorial/body.md", DOC.index("Regex prose"), "Regex prose.")]
        apply_context_headers(DOC, chunks)
        assert chunks[0].content.startswith("tutorial body")
        assert chunks[0].content.endswith("Regex prose.")

    def test_hash_is_recomputed(self) -> None:
        # Both indexes skip on content_hash. Leaving it alone would make the
        # re-ingest a no-op and the headers would never reach the index —
        # silently, after paying to embed nothing.
        chunks = [_chunk("tutorial/body.md", DOC.index("Regex prose"), "Regex prose.")]
        before = chunks[0].metadata.content_hash
        apply_context_headers(DOC, chunks)
        assert chunks[0].metadata.content_hash != before
        assert chunks[0].metadata.content_hash == hash_text(chunks[0].content)

    def test_returns_how_many_changed(self) -> None:
        chunks = [_chunk("a.md", 0), _chunk("b.md", 0)]
        assert apply_context_headers(DOC, chunks) == 2

    def test_a_second_call_stacks_another_header(self) -> None:
        # Documents the hazard rather than hiding it: the indexer must call
        # this exactly once per run, which is why it sits immediately after
        # chunking and before the hash comparison.
        chunks = [_chunk("tutorial/body.md", DOC.index("Regex prose"), "Regex prose.")]
        apply_context_headers(DOC, chunks)
        once = chunks[0].content
        apply_context_headers(DOC, chunks)
        # It IS applied twice — the function is unconditional by design. The
        # protection is that the indexer calls it exactly once per run, so
        # this pins the behaviour rather than pretending it is idempotent.
        assert chunks[0].content == once.split("\n\n", 1)[0] + "\n\n" + once
        assert chunks[0].content.count("Regex prose.") == 1


# FastAPI's release notes nest sections under the release for most of their
# length, but the 2023 entries put both at H2. Four chunks of the corpus fall
# in that window and `fq-002` was answered from one of them.
FLAT_CHANGELOG = (
    "# Release Notes\n\n"
    "## Latest Changes\n\n### Internal\n\nunreleased prose\n\n"
    "## 0.129.0 (2026-02-12)\n\n### Breaking Changes\n\nnested prose\n\n"
    "## 0.104.0 (2023-10-18)\n\n"
    "## Features\n\nflat feature prose\n\n"
    "## Upgrades\n\nflat upgrade prose\n\n"
    "## 0.103.2 (2023-09-29)\n\n## Fixes\n\nnext release prose\n"
)


class TestChangelogReleaseHeadings:
    def test_a_flat_section_does_not_displace_its_release(self) -> None:
        # The outline says these are siblings. They are not: the release is a
        # record boundary and the section is a field inside it.
        assert heading_trail(FLAT_CHANGELOG, FLAT_CHANGELOG.index("flat upgrade prose")) == [
            "Release Notes",
            "0.104.0 (2023-10-18)",
            "Upgrades",
        ]

    def test_a_second_flat_section_replaces_only_the_first(self) -> None:
        trail = heading_trail(FLAT_CHANGELOG, FLAT_CHANGELOG.index("flat upgrade prose"))
        assert "Features" not in trail

    def test_the_next_release_displaces_the_previous_one(self) -> None:
        # The exception is for non-version headings only, or a changelog
        # would accumulate every release it had ever seen.
        assert heading_trail(FLAT_CHANGELOG, FLAT_CHANGELOG.index("next release prose")) == [
            "Release Notes",
            "0.103.2 (2023-09-29)",
            "Fixes",
        ]

    def test_a_properly_nested_release_is_unaffected(self) -> None:
        assert heading_trail(FLAT_CHANGELOG, FLAT_CHANGELOG.index("nested prose")) == [
            "Release Notes",
            "0.129.0 (2026-02-12)",
            "Breaking Changes",
        ]

    def test_an_unreleased_section_still_has_no_release(self) -> None:
        # "Latest Changes" is not a version and must not borrow one.
        assert heading_trail(FLAT_CHANGELOG, FLAT_CHANGELOG.index("unreleased prose")) == [
            "Release Notes",
            "Latest Changes",
            "Internal",
        ]

    def test_ordinary_documents_keep_sibling_replacement(self) -> None:
        # The guard is a text test, so it must not fire on prose headings that
        # merely follow one another.
        assert heading_trail(DOC, DOC.index("Required prose")) == [
            "Query Parameters and String Validations",
            "Required parameters",
        ]

    def test_bracketed_and_v_prefixed_releases_are_recognised(self) -> None:
        # keepachangelog and `v`-prefixed tags are the two other common forms.
        for heading in ("[1.2.3] - 2024-01-01", "v1.2.3"):
            doc = f"# Changelog\n\n## {heading}\n\n## Fixed\n\nprose\n"
            assert heading_trail(doc, doc.index("prose")) == ["Changelog", heading, "Fixed"]

    def test_the_chunk_that_answered_fq_002_now_carries_its_date(self) -> None:
        # The whole point: a claim that was three years stale was indexed and
        # cited with nothing on it to say when it was true.
        header = context_header("fastapi/release-notes.md", FLAT_CHANGELOG,
                                FLAT_CHANGELOG.index("flat upgrade prose"))
        assert "0.104.0 (2023-10-18)" in header

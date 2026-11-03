"""
The console's explanations must cover everything the pipeline can emit.

Atlas prints a score trail on every evidence card. Until 2026-11-03 those
printed as bare keys -- `dense 0.82  bm25 4.71  rrf 0.031  rerank 0.94` --
which the first outside reader could see and not read. They now print a plain
word, with the technical name in a tooltip, from a single table in
`console/src/lib/glossary.ts`.

That table is in TypeScript and the keys it has to cover are decided in
Python, so nothing but this test connects the two. Add a retriever and the
console silently falls back to printing its raw internal name at a reader;
this fails instead, naming the key that has no entry.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from atlas.orchestration import pipeline

GLOSSARY = Path(__file__).resolve().parents[2] / "console" / "src" / "lib" / "glossary.ts"


def _documented_score_keys() -> set[str]:
    """The keys of the `SCORES` table, read out of the TypeScript source."""
    text = GLOSSARY.read_text(encoding="utf-8")
    body = re.search(
        r"export const SCORES: Record<ScoreKey, ScoreNote> = \{(.*?)\n\}", text, re.S
    )
    assert body, "SCORES table not found in glossary.ts -- did it get renamed?"
    return set(re.findall(r"^  (\w+): \{", body.group(1), re.M))


def _emitted_score_keys() -> set[str]:
    """Every label `_collect_evidence` can put in a score trail.

    Two sources: the retriever-name mapping, and the stage labels written as
    literals in the function body. Read from the source rather than restated
    here, so a new stage cannot pass by being forgotten in both places.
    """
    import inspect

    source = inspect.getsource(pipeline._collect_evidence)
    literals = set(re.findall(r'_record\([^,]+, "(\w+)"\)', source))
    return set(pipeline._SCORE_LABELS.values()) | literals


class TestEveryScoreTheReaderSeesHasAnExplanation:
    def test_the_glossary_covers_every_key_the_pipeline_emits(self) -> None:
        missing = _emitted_score_keys() - _documented_score_keys()
        assert not missing, (
            f"these scores reach an evidence card with no explanation: {sorted(missing)}. "
            f"Add them to SCORES in {GLOSSARY.name}."
        )

    def test_the_pipeline_still_emits_the_keys_we_think_it_does(self) -> None:
        # Guards the regexes above: if `_collect_evidence` is rewritten so the
        # labels stop being literals, the test above would pass vacuously.
        assert _emitted_score_keys() == {"dense", "bm25", "rrf", "rerank", "score"}

    def test_the_glossary_has_no_entry_for_a_score_that_cannot_happen(self) -> None:
        stale = _documented_score_keys() - _emitted_score_keys()
        assert not stale, f"explained but never emitted: {sorted(stale)}"


class TestTheExplanationsAreUsable:
    @pytest.mark.parametrize("field", ["label", "technical", "what", "read"])
    def test_every_score_fills_in_every_field(self, field: str) -> None:
        text = GLOSSARY.read_text(encoding="utf-8")
        body = re.search(
            r"export const SCORES: Record<ScoreKey, ScoreNote> = \{(.*?)\n\}", text, re.S
        )
        assert body
        entries = re.split(r"^  \w+: \{", body.group(1), flags=re.M)[1:]
        assert len(entries) == len(_documented_score_keys())
        for entry in entries:
            found = re.search(rf'{field}: "([^"]+)"', entry)
            assert found and found.group(1).strip(), f"empty {field} in {entry[:60]!r}"

    def test_the_plain_label_is_not_just_the_jargon_again(self) -> None:
        """The whole point is that the label reads without a glossary."""
        text = GLOSSARY.read_text(encoding="utf-8")
        for key, label in re.findall(r"^  (\w+): \{\n    label: \"([^\"]+)\"", text, re.M):
            if key == "score":
                continue  # already a plain word; nothing to translate.
            assert label != key, f"{key} is still labelled with its own internal name"

"""
Evidence-based reuse (E2.5, docs/company-scale.md §1b and §7).

The answer cache matches a question only by its text, so "Is my wife's
delivery covered?" and "maternity cover for spouse" are two paid answers
from the same two paragraphs. This remembers which passages each answer's
search found and serves a stored answer to a new question when all four
hold:

1. **Same evidence.** The new question's search shares at least
   `min_shared` of its top five passages with the stored one's. Overlap, not
   identity: rewording reorders the ranking, and an exact fingerprint caught
   only 1 rewording in 8 (§7).
2. **Close in meaning.** The two questions' embeddings are at least
   `min_similarity` apart by cosine.
3. **Allowed.** The asker may read every passage the stored answer was built
   from — not only the ones they retrieved now. This is the rule that lets
   people with different access share an answer (the exact cache keys on
   access and cannot) without one ever carrying a passage the other may not
   read. An entry with no lists is never served.
4. **It fits.** A short model call reads the new question and the stored
   answer and says whether the answer answers it. Passages and meaning
   alone are not safe: two questions in §7 shared three passages, read as
   similar and needed different answers.

Entries are per sheet and per sheet version, so any change to the sheet's
documents or their access (E2.3) makes every older entry unreachable, the
same as the exact cache. Only answers that passed the faithfulness check
are stored. Memory only, per server, bounded; behind `REUSE_ENABLED`.

Cost per question when on: one extra embedding (≈₹0.0001) always, and one
fit check (≈₹0.01) only when a candidate passes 1–3. A fit check that fails
is a miss, never an error.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import structlog

from atlas.access import readable
from atlas.api.cache import normalise_question
from atlas.config import ReuseConfig
from atlas.interfaces.embedder import BaseEmbedder
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.orchestration.llm import parse_json_response

logger = structlog.get_logger(__name__)

TOP = 5

_FIT_PROMPT = """\
A stored answer was written for an earlier question. Decide whether it is a \
correct and complete answer to a NEW question, as if written for it.

Say "fits": false if the new question asks for anything the answer does not \
cover, asks about a different case, version, person or condition, or would \
make any part of the answer wrong or misleading. When unsure, say false.

Do NOT judge whether the answer is true. It was already checked against the \
source documents, which may describe versions or features newer than \
anything you know. Judge only whether it answers what the new question asks.

First write what the new question asks for, then what the stored answer \
actually gives. It fits only if the answer gives that directly. An answer to \
a neighbouring question about the same feature (how to do it, when asked \
whether it works; one step, when asked about another) does not fit.

Respond with valid JSON: {"asks": "...", "gives": "...", "fits": true or false}"""


@dataclass
class _Entry:
    vector: list[float]
    top: frozenset[str]
    acl: list[list[str]]
    payload: dict[str, Any]


@dataclass
class Probe:
    """What a question's search found, before anything is generated."""

    vector: list[float]
    top: list[str]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
    return dot / norm if norm else 0.0


class EvidenceReuse:
    """Stored answers, findable by the passages a new question retrieves."""

    def __init__(self, embedder: BaseEmbedder, llm: BaseLLMProvider,
                 config: ReuseConfig | None = None) -> None:
        self._embedder = embedder
        self._llm = llm
        self._config = config or ReuseConfig()
        self._entries: OrderedDict[tuple[str, str, str], _Entry] = OrderedDict()

    async def probe(self, question: str, chunk_ids: list[str]) -> Probe:
        vector = await self._embedder.embed_query(question)
        return Probe(vector=vector, top=chunk_ids[:TOP])

    async def find(self, sheet: str, version: str, question: str, probe: Probe,
                   access: frozenset[str] | None) -> dict[str, Any] | None:
        """A stored answer this caller may be shown for *question*, or None."""
        top = set(probe.top)
        best: tuple[float, _Entry] | None = None
        for (s, v, _), entry in self._entries.items():
            if (s, v) != (sheet, version):
                continue
            if len(top & entry.top) < self._config.min_shared:
                continue
            similarity = _cosine(probe.vector, entry.vector)
            if similarity < self._config.min_similarity:
                continue
            if not all(readable(acl, access) for acl in entry.acl):
                continue
            if best is None or similarity > best[0]:
                best = (similarity, entry)
        if best is None:
            return None
        similarity, entry = best
        fits, reason = await self._fits(question, str(entry.payload.get("answer") or ""))
        logger.info("evidence_reuse_checked", fits=fits, similarity=round(similarity, 3),
                    shared=len(top & entry.top), reason=reason[:120])
        return entry.payload if fits else None

    def remember(self, sheet: str, version: str, question: str, probe: Probe,
                 acl: list[list[str]], payload: dict[str, Any]) -> None:
        """Store an answer that passed its faithfulness check."""
        if not probe.top or not acl:
            return
        key = (sheet, version, normalise_question(question))
        # A newer version of the sheet makes this sheet's older entries dead
        # weight; drop them rather than wait for them to age out.
        for stale in [k for k in self._entries if k[0] == sheet and k[1] != version]:
            del self._entries[stale]
        self._entries[key] = _Entry(vector=probe.vector, top=frozenset(probe.top),
                                    acl=[list(a) for a in acl], payload=payload)
        self._entries.move_to_end(key)
        while len(self._entries) > self._config.max_entries:
            self._entries.popitem(last=False)

    async def _fits(self, question: str, answer: str) -> tuple[bool, str]:
        if not answer:
            return False, "no answer"
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_FIT_PROMPT),
                Message(role="user",
                        content=f"New question: {question}\n\nStored answer:\n{answer}"),
            ],
            temperature=0.0,
            # Room for "asks" and "gives" before the verdict: at 160 one
            # reply in 34 was cut off mid-JSON and read as a failed check.
            max_tokens=240,
            json_mode=True,
        )
        try:
            parsed = parse_json_response((await self._llm.generate(request)).content)
        except Exception as exc:  # noqa: BLE001 -- a failed check is a miss
            logger.warning("evidence_reuse_check_failed", error=str(exc))
            return False, "check failed"
        why = f"asks: {parsed.get('asks')}; gives: {parsed.get('gives')}"
        return parsed.get("fits") is True, why

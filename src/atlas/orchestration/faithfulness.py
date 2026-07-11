"""
Faithfulness checker: verify the answer is grounded in retrieved context.

Design rationale:
    The generator is instructed to cite and not fabricate, but instruction-
    following is probabilistic. The faithfulness checker is a second LLM pass
    that independently verifies each factual claim in the answer against the
    source context — functioning as an adversarial reviewer.

    This is conceptually similar to RAGAS's faithfulness metric but applied at
    inference time rather than offline evaluation. When faithfulness_score < 0.7
    the pipeline flags the answer rather than silently returning potentially
    fabricated content. The flag is surfaced in the API response so consumers
    (e.g. a human-review workflow) can triage it.

    Claim extraction: the checker asks the LLM to enumerate discrete claims
    from the answer before verifying each. This decomposition step makes the
    verification more reliable — asking "is this entire paragraph faithful?"
    is harder for an LLM than "is THIS specific claim supported by the
    context?".

    Performance note: this adds one LLM call per query on the critical path.
    If latency is critical, move faithfulness checking to an async background
    job and return the answer immediately with a "pending verification" flag.
    We keep it synchronous here for simplicity and because it's togglable
    via FaithfulnessChecker.enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.llm import parse_json_response

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a faithfulness auditor for an AI assistant. You will be given:
1. A context: retrieved source passages
2. An answer: what the AI said

Your task:
1. List every distinct factual claim made in the answer.
2. For each claim, determine if it is SUPPORTED, UNSUPPORTED, or UNVERIFIABLE \
from the context.
3. Compute a faithfulness score: (supported_claims / total_claims).

Respond with valid JSON:
{
  "claims": [
    {"claim": "...", "verdict": "supported"|"unsupported"|"unverifiable", "evidence": "..."}
  ],
  "faithfulness_score": 0.0–1.0,
  "summary": "one-sentence overall assessment"
}

An unverifiable claim is one that is neither confirmed nor denied by the context \
(e.g. a generic statement). Count it as supported for the score calculation."""


@dataclass
class ClaimVerdict:
    claim: str
    verdict: str  # "supported" | "unsupported" | "unverifiable"
    evidence: str


@dataclass
class FaithfulnessResult:
    score: float
    is_faithful: bool
    claims: list[ClaimVerdict] = field(default_factory=list)
    summary: str = ""
    # Populated with claims whose verdict == "unsupported"
    unsupported_claims: list[str] = field(default_factory=list)


def _format_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[{i}] {c.content}" for i, c in enumerate(chunks, 1)
    )


class FaithfulnessChecker:
    """Verify that generated answer claims are grounded in retrieved context."""

    def __init__(
        self,
        llm: BaseLLMProvider,
        threshold: float = 0.7,
        enabled: bool = True,
    ) -> None:
        self._llm = llm
        self._threshold = threshold
        self.enabled = enabled

    async def check(
        self,
        answer: str,
        chunks: list[RetrievedChunk],
    ) -> FaithfulnessResult:
        if not self.enabled:
            return FaithfulnessResult(score=1.0, is_faithful=True, summary="check disabled")

        context = _format_context(chunks)
        request = GenerationRequest(
            messages=[
                Message(role="system", content=_SYSTEM_PROMPT),
                Message(
                    role="user",
                    content=f"Context:\n{context}\n\nAnswer:\n{answer}",
                ),
            ],
            temperature=0.0,
            max_tokens=512,
            json_mode=True,
        )
        response = await self._llm.generate(request)
        parsed = parse_json_response(response.content)

        raw_claims = parsed.get("claims", [])
        claims = [
            ClaimVerdict(
                claim=c.get("claim", ""),
                verdict=c.get("verdict", "unverifiable"),
                evidence=c.get("evidence", ""),
            )
            for c in raw_claims
        ]
        score = float(parsed.get("faithfulness_score", 1.0))
        unsupported = [c.claim for c in claims if c.verdict == "unsupported"]

        result = FaithfulnessResult(
            score=score,
            is_faithful=score >= self._threshold,
            claims=claims,
            summary=parsed.get("summary", ""),
            unsupported_claims=unsupported,
        )

        logger.info(
            "faithfulness_checked",
            score=score,
            is_faithful=result.is_faithful,
            unsupported_count=len(unsupported),
        )
        return result

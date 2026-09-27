"""
Deterministic context headers prepended to a chunk's indexed text.

Design rationale:
    A chunk taken from the middle of a page carries no trace of the page it
    came from. `fq-012` asks how to add string validation to a query
    parameter; the answer is on `tutorial/query-params-str-validations`, and
    that page was never retrieved at all — not ranked low, absent. Its chunks
    discuss `Query` and `Annotated` without ever repeating what the page is
    about, because a human reader has the title on screen and the prose does
    not need to.

    So each chunk is given a two-line header naming its source path and the
    heading trail above it. Both lines are ordinary words, which is the point:

      - the dense embedding gains the topic the prose assumes;
      - BM25 gains the path's tokens, and the sparse tokenizer already splits
        on `/` and `-`, so `tutorial/query-params-str-validations` indexes as
        tutorial, query, params, str, validations — the vocabulary of the
        question that could not find it.

    Deterministic on purpose. An LLM writing a sentence of context per chunk
    is the better-known version of this idea and prices at roughly ₹200 for
    this corpus against ₹6.6 for headers; the cheap version has to be shown
    not to work before the expensive one is worth running.

    The header joins `content` rather than riding alongside it because
    `content` is what both indexes consume and what `content_hash` covers.
    A separate field would have to be threaded through the embedder, the BM25
    tokenizer and both idempotency checks, and any one of them missed would
    fail silently as "the headers did nothing".
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from atlas.ingestion.hashing import hash_text
from atlas.interfaces.document import Chunk

# A markdown ATX heading: one to six hashes, a space, then the text. Setext
# headings (underlined with === or ---) are not matched; the corpus is
# mkdocs-generated and uses ATX throughout.
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.MULTILINE)

# mkdocs attribute lists: `## Default values { #default-values }`. The brace
# block is the anchor slug, which is the heading's own words hyphenated — so
# keeping it pays to embed everything twice and tells BM25 nothing new.
_ATTR_LIST = re.compile(r"\s*\{[^}]*\}\s*$")

# Separators inside a documentation path. Kept as a set of characters rather
# than a regex split so `.md` is removed by suffix handling, not by chance.
_PATH_SEPARATORS = re.compile(r"[/\\_\-]+")


def humanise_source(source: str, source_root: str | None = None) -> str:
    """`tutorial/query-params-str-validations.md` → `tutorial query params str validations`.

    The extension goes because it is the same four characters on every chunk
    in the corpus, and a token that appears everywhere carries no BM25 signal
    while still costing an embedding position. *source_root* goes for the
    same reason and is worth more: without it every chunk of this corpus
    opened with "data corpus fastapi", three tokens paid for 4,020 times that
    no query can discriminate on.
    """
    if not source:
        # A loader is free to produce a document with no source path; the
        # heading trail can still carry the header on its own.
        return ""
    path = Path(source)
    if source_root:
        # A path outside that root is a mixed-origin ingest; keep it whole
        # rather than guessing which leading segments are noise.
        with contextlib.suppress(ValueError):
            path = path.relative_to(source_root)
    stem = path.with_suffix("").as_posix()
    words = [w for w in _PATH_SEPARATORS.split(stem) if w]
    return " ".join(words)


def heading_trail(document_text: str, start_char: int) -> list[str]:
    """Headings in force at *start_char*, outermost first.

    Built by replaying every heading before the chunk and keeping a stack, so
    a level-3 heading does not inherit the level-3 sibling that preceded it.
    Anything at or below the new heading's level is dropped, which is what
    "in force" means for a document outline.
    """
    stack: list[tuple[int, str]] = []
    for match in _HEADING.finditer(document_text):
        if match.start() >= start_char:
            break
        level = len(match.group(1))
        text = _ATTR_LIST.sub("", match.group(2)).strip()
        if not text:
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
    return [text for _, text in stack]


def context_header(
    source: str, document_text: str, start_char: int, source_root: str | None = None
) -> str:
    """The header for one chunk, or "" when there is nothing to say.

    Returns a trailing blank line so the header reads as a separate block
    rather than running into the chunk's first sentence.
    """
    lines = []
    where = humanise_source(source, source_root)
    if where:
        lines.append(where)
    trail = heading_trail(document_text, start_char)
    if trail:
        # Deduplicated against the path, which for a mkdocs corpus repeats the
        # page title as its own H1 on most pages.
        if not lines or trail[0].lower() != lines[0].lower():
            lines.append(" > ".join(trail))
        elif len(trail) > 1:
            lines.append(" > ".join(trail[1:]))
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def apply_context_headers(
    document_text: str, chunks: list[Chunk], source_root: str | None = None
) -> int:
    """Prepend each chunk's header to its content, in place.

    Returns how many chunks were changed. `content_hash` is recomputed
    because both indexes decide what to skip from it: leaving it alone would
    make a re-ingest a no-op and the headers would never reach the index at
    all — silently, and after paying to embed nothing.
    """
    changed = 0
    for chunk in chunks:
        header = context_header(
            chunk.metadata.source, document_text, chunk.metadata.start_char, source_root
        )
        if not header:
            continue
        chunk.content = header + chunk.content
        chunk.metadata.content_hash = hash_text(chunk.content)
        changed += 1
    return changed

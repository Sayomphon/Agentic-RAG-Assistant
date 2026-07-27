"""Build a compact, auditable grounding context from ranked retrieval hits."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from src.config import (
    CONTEXT_DUPLICATE_THRESHOLD,
    CONTEXT_MIN_BODY_CHARS,
    MAX_CONTEXT_CHARS,
)
from src.retrievers.base import Chunk, ScoredChunk

_WHITESPACE = re.compile(r"\s+")
_TRUNCATION_MARKER = " …"
_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class BuiltContext:
    """The exact evidence selected for both UI display and generation."""

    hits: tuple[ScoredChunk, ...]
    snippets: tuple[str, ...]
    total_chars: int


def _canonical_text(text: str) -> str:
    return _WHITESPACE.sub(" ", text.casefold()).strip()


def _character_shingles(text: str, width: int = 5) -> frozenset[str]:
    """Return language-agnostic shingles for Thai/English overlap detection."""
    compact = "".join(char for char in _canonical_text(text) if char.isalnum())
    if len(compact) <= width:
        return frozenset({compact}) if compact else frozenset()
    return frozenset(
        compact[position : position + width]
        for position in range(len(compact) - width + 1)
    )


def _overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """Overlap coefficient: detects a short chunk contained in a longer one."""
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _truncate_body(text: str, limit: int) -> str:
    """Fit text at a word boundary; never exceed ``limit`` characters."""
    if len(text) <= limit:
        return text
    content_limit = limit - len(_TRUNCATION_MARKER)
    if content_limit <= 0:
        return ""
    prefix = text[:content_limit].rstrip()
    boundary = prefix.rfind(" ")
    if boundary > content_limit // 2:
        prefix = prefix[:boundary].rstrip()
    return f"{prefix}{_TRUNCATION_MARKER}" if prefix else ""


class ContextBuilder:
    """Deduplicate ranked hits and enforce a strict generator context budget."""

    def __init__(
        self,
        *,
        max_context_chars: int = MAX_CONTEXT_CHARS,
        duplicate_threshold: float = CONTEXT_DUPLICATE_THRESHOLD,
        min_body_chars: int = CONTEXT_MIN_BODY_CHARS,
    ) -> None:
        self._max_context_chars = max(0, max_context_chars)
        self._duplicate_threshold = min(
            max(0.0, duplicate_threshold),
            1.0,
        )
        self._min_body_chars = max(1, min_body_chars)

    def build(self, hits: list[ScoredChunk]) -> BuiltContext:
        selected_hits: list[ScoredChunk] = []
        snippets: list[str] = []
        canonical_bodies: set[str] = set()
        fingerprints: list[frozenset[str]] = []
        used_chars = 0

        for hit in hits:
            canonical = _canonical_text(hit.text)
            if not canonical:
                continue
            fingerprint = _character_shingles(canonical)
            if canonical in canonical_bodies:
                continue
            if any(
                _overlap(fingerprint, previous) >= self._duplicate_threshold
                for previous in fingerprints
            ):
                continue

            separator_chars = len(_SEPARATOR) if snippets else 0
            available = self._max_context_chars - used_chars - separator_chars
            header = f"[{hit.title}]\n"
            body_limit = available - len(header)
            if body_limit <= 0:
                continue

            if len(hit.text) <= body_limit:
                body = hit.text
            else:
                if body_limit < self._min_body_chars:
                    continue
                body = _truncate_body(hit.text, body_limit)
                if len(body) < self._min_body_chars:
                    continue

            selected_hit = hit
            if body != hit.text:
                selected_hit = replace(
                    hit,
                    chunk=Chunk(
                        title=hit.chunk.title,
                        text=body,
                        index=hit.chunk.index,
                        source_file=hit.chunk.source_file,
                    ),
                )
            snippet = selected_hit.as_snippet()
            selected_hits.append(selected_hit)
            snippets.append(snippet)
            canonical_bodies.add(canonical)
            fingerprints.append(fingerprint)
            used_chars += separator_chars + len(snippet)

        return BuiltContext(
            hits=tuple(selected_hits),
            snippets=tuple(snippets),
            total_chars=used_chars,
        )

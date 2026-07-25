"""Shared retrieval contracts: chunking, scored results, and the protocol.

Everything downstream (tools, evaluation, UI) depends only on the types in
this module, so retrieval strategies can be added or swapped without
touching any other layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.config import KB_PATH

_SECTION_PATTERN = re.compile(r"^--- (?P<title>.+?) ---$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    """One knowledge-base section.

    Attributes:
        title: Section title taken from the ``--- Title ---`` delimiter.
        text: Body text of the section.
        index: Position of the section within the source file.
    """

    title: str
    text: str
    index: int = 0

    def as_snippet(self) -> str:
        """Render the chunk as a self-describing snippet string."""
        return f"[{self.title}]\n{self.text}"


@dataclass(frozen=True)
class ScoredChunk:
    """A retrieval hit: the chunk plus ranking metadata.

    The metadata exists for evaluation and UI layers — ``score`` explains
    ranking decisions, ``source`` records which retriever produced the hit
    (``"bm25"``, ``"dense"``, or ``"bm25+dense"`` after hybrid fusion).
    """

    chunk: Chunk
    score: float
    source: str

    @property
    def title(self) -> str:
        """Section title (pass-through so callers need not unwrap ``chunk``)."""
        return self.chunk.title

    @property
    def text(self) -> str:
        """Section body (pass-through convenience)."""
        return self.chunk.text

    def as_snippet(self) -> str:
        """Render the underlying chunk; metadata is deliberately excluded so
        the agent-facing snippet format stays identical across retrievers."""
        return self.chunk.as_snippet()


class Retriever(Protocol):
    """Contract for every retrieval implementation (keyword, dense, hybrid)."""

    def search(self, query: str, top_k: int) -> list[ScoredChunk]:
        """Return up to ``top_k`` relevant chunks with scores, best first."""
        ...


def load_chunks(path: str = KB_PATH) -> list[Chunk]:
    """Read the knowledge base and split it into titled chunks.

    Splitting strategy lives here and only here: retrieval classes receive
    ready-made ``Chunk`` objects, so the chunking rules can change without
    touching any ranking code.

    Args:
        path: Path to the knowledge base text file.

    Returns:
        All sections in file order.

    Raises:
        FileNotFoundError: If the knowledge base file does not exist.
        ValueError: If the file contains no ``--- Title ---`` sections.
    """
    kb_file = Path(path)
    if not kb_file.is_file():
        raise FileNotFoundError(
            f"Knowledge base not found at '{kb_file.resolve()}'. "
            "Set KB_PATH in .env or src/config.py to the correct location."
        )
    raw = kb_file.read_text(encoding="utf-8")
    # re.split with one capture group yields [preamble, title1, body1, ...].
    parts = _SECTION_PATTERN.split(raw)
    titles, bodies = parts[1::2], parts[2::2]
    chunks = [
        Chunk(title=t.strip(), text=b.strip(), index=i)
        for i, (t, b) in enumerate(zip(titles, bodies))
        if b.strip()
    ]
    if not chunks:
        raise ValueError(
            f"'{kb_file}' contains no '--- Section Title ---' sections; "
            "check the file format."
        )
    return chunks

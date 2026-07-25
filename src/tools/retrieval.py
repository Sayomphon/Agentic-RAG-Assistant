"""Custom RAG retrieval tool: ranked search over knowledge_base.txt.

Design:
    - ``Chunk`` / ``load_chunks``  — chunking, independent of retrieval.
    - ``Retriever`` protocol       — the contract every implementation obeys.
    - ``BM25Retriever``            — Phase 1 keyword implementation.
    - ``get_retriever``            — factory selecting by ``SEARCH_MODE``;
      a cached singleton so the index is built exactly once per process.
    - ``search_knowledge_base``    — the LangChain tool exposed to agents.

Adding a semantic or vector-DB retriever later means writing one new class
and one new ``elif`` in the factory — the tool signature, the agents, and
the graph stay untouched.
"""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from langchain_core.tools import tool
from rank_bm25 import BM25Okapi

from src.config import KB_PATH, MIN_SCORE, SEARCH_MODE, TOP_K

_SECTION_PATTERN = re.compile(r"^--- (?P<title>.+?) ---$", re.MULTILINE)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


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


def _tokenize(text: str) -> list[str]:
    """Lowercase and split text into alphanumeric tokens."""
    return _TOKEN_PATTERN.findall(text.lower())


class Retriever(Protocol):
    """Contract for every retrieval implementation (keyword, semantic, ...)."""

    def search(self, query: str, top_k: int) -> list[Chunk]:
        """Return up to ``top_k`` relevant chunks, best first."""
        ...


class BM25Retriever:
    """Keyword retriever backed by a BM25 index built once at construction.

    Scale note: for the current ~20-chunk KB an in-memory index with a
    linear scan per query is ideal. At ~100k chunks this design would
    change: batch-embed the corpus offline, store vectors in an external
    store (e.g. pgvector/Qdrant), and query an approximate-nearest-
    neighbour index instead of scoring every chunk.
    """

    def __init__(self, chunks: list[Chunk], min_score: float = MIN_SCORE) -> None:
        """Tokenize the corpus and build the index — once, at build time.

        Args:
            chunks: Corpus to index.
            min_score: BM25 score a chunk must exceed to be returned.
        """
        self._chunks = chunks
        self._min_score = min_score
        # Corpus tokenization happens exactly once, here — never at query time.
        self._index = BM25Okapi([_tokenize(f"{c.title} {c.text}") for c in chunks])

    def search(self, query: str, top_k: int) -> list[Chunk]:
        """Return up to ``top_k`` chunks scoring above ``min_score``, best first."""
        return [chunk for chunk, _ in self.search_with_scores(query, top_k)]

    def search_with_scores(self, query: str, top_k: int) -> list[tuple[Chunk, float]]:
        """Like :meth:`search`, but keep scores (used by the standalone demo).

        Args:
            query: Free-text query; empty or non-alphanumeric input yields [].
            top_k: Maximum number of results.

        Returns:
            ``(chunk, score)`` pairs, highest score first. Empty when nothing
            clears ``min_score`` — never a least-bad match, so the generator
            can honestly report "not found".
        """
        tokens = _tokenize(query)
        if not tokens or top_k <= 0:
            return []
        scores = self._index.get_scores(tokens)
        # Partial selection beats sorting the whole score array (O(n log k)).
        top = heapq.nlargest(top_k, enumerate(scores), key=lambda pair: pair[1])
        return [
            (self._chunks[i], float(s)) for i, s in top if s > self._min_score
        ]


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    """Build and cache the retriever selected by ``SEARCH_MODE``.

    The ``lru_cache`` makes this a lazy singleton: the file read, chunking,
    tokenization, and index build all happen exactly once per process — a
    naive rebuild-per-query version would redo all of that on every call.

    Returns:
        The process-wide retriever instance.

    Raises:
        ValueError: If ``SEARCH_MODE`` names an unknown implementation.
    """
    chunks = load_chunks()
    if SEARCH_MODE == "keyword":
        return BM25Retriever(chunks)
    raise ValueError(
        f"Unknown SEARCH_MODE {SEARCH_MODE!r}; expected 'keyword'. "
        "(Add new modes here — the tool and agents need no changes.)"
    )


@tool
def search_knowledge_base(query: str, top_k: int = TOP_K) -> list[str]:
    """Search the Siam Innovate company knowledge base for policy information.

    The knowledge base is the official employee handbook covering topics
    such as travel, leave, remote work, expenses, IT security, benefits,
    and HR processes. Returns raw text snippets ranked most-relevant
    first. Returns an empty list when the handbook contains nothing
    relevant to the query.

    Args:
        query: Search terms describing the information needed.
        top_k: Maximum number of snippets to return.
    """
    return [chunk.as_snippet() for chunk in get_retriever().search(query, top_k)]


if __name__ == "__main__":  # Standalone verification — no LLM involved.
    retriever = get_retriever()
    assert isinstance(retriever, BM25Retriever)  # demo needs scores
    for q in [
        "international travel policy",
        "work from home",
        "annual leave",
        "CEO salary",
        "insurance",
    ]:
        print(f'\n=== "{q}" ===')
        hits = retriever.search_with_scores(q, TOP_K)
        if not hits:
            print(f"  (no results above MIN_SCORE={MIN_SCORE})")
        for chunk, score in hits:
            print(f"  {score:5.2f}  {chunk.title}")

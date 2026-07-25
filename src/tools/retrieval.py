"""RAG retrieval tool: ranked search over the knowledge base.

This module is the boundary between agents and retrieval. Agents import
exactly two names from here — ``search_knowledge_base`` (the tool) and
``has_english_search_terms`` (the query-language probe) — and both are
re-exported unchanged no matter which retrieval strategy is active.

The strategies themselves (BM25, OpenAI embeddings, hybrid fusion) live in
``src/retrievers/``; ``get_retriever`` picks one by ``config.SEARCH_MODE``.
Adding another strategy means one new class and one new factory branch —
this tool, the agents, and the graph stay untouched.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from src.config import TOP_K
from src.retrievers import ScoredChunk, get_retriever, has_english_search_terms

__all__ = ["has_english_search_terms", "search_knowledge_base", "search_scored"]


def search_scored(
    query: str,
    top_k: int | None = None,
    mode: str | None = None,
) -> list[ScoredChunk]:
    """Ranked search returning full hits (title, score, source) — the core
    retrieval routine the tool below wraps, shared with evaluation and UI
    layers that need ranking metadata without going through an agent.

    Args:
        query: Search terms describing the information needed.
        top_k: Result cap; ``None`` uses ``config.TOP_K``.
        mode: Retrieval mode override; ``None`` uses ``config.SEARCH_MODE``.
    """
    return get_retriever(mode).search(
        query, top_k=TOP_K if top_k is None else top_k
    )


@tool
def search_knowledge_base(
    query: str,
    top_k: Annotated[int | None, InjectedToolArg] = None,
    mode: Annotated[str | None, InjectedToolArg] = None,
) -> list[ScoredChunk]:
    """Search the Siam Innovate company knowledge base for policy information.

    The knowledge base is the official employee handbook covering topics
    such as travel, leave, remote work, expenses, IT security, benefits,
    and HR processes. Returns raw handbook sections ranked most-relevant
    first. Returns an empty list when the handbook contains nothing
    relevant to the query.

    Args:
        query: Search terms describing the information needed.
    """
    # ``top_k`` and ``mode`` are InjectedToolArg: they are stripped from the
    # schema the model sees and supplied by the caller from trusted state,
    # so the LLM can choose *what* to search for but never how much to
    # return or which retrieval strategy to use.
    return search_scored(query, top_k=top_k, mode=mode)


if __name__ == "__main__":  # Standalone verification — no LLM involved.
    from src.config import SEARCH_MODE

    retriever = get_retriever()
    print(f"SEARCH_MODE={SEARCH_MODE}  retriever={type(retriever).__name__}")
    for q in [
        "international travel policy",
        "work from home",
        "annual leave",
        "What is the CEO's salary?",
        "What are the cybersecurity incident reporting rules?",
    ]:
        print(f'\n=== "{q}" ===')
        hits = retriever.search(q, TOP_K)
        if not hits:
            print("  (no results passed the relevance gates)")
        for hit in hits:
            print(f"  {hit.score:7.4f}  [{hit.source}]  {hit.title}")

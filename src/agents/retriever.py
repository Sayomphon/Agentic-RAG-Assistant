"""Data Retriever agent: retrieval only — structurally barred from answering.

The guardrail here is two-layered:
    1. Structural — ``tool_choice="required"`` forces a tool call, so the
       model *cannot* answer from its own knowledge.
    2. Prompt — the system prompt forbids answering or rewriting.
Structural enforcement is what makes the guarantee reliable; the prompt
reinforces intent and guides query reformulation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents import get_llm
from src.config import TOP_K
from src.tools.retrieval import (
    has_english_search_terms,
    search_knowledge_base,
    search_scored,
)

if TYPE_CHECKING:
    from src.graph import PipelineState

RETRIEVER_SYSTEM_PROMPT = """\
You are the Data Retriever agent in a two-agent pipeline. Your ONLY job
is information retrieval from the company knowledge base.

Rules:
- Call the `search_knowledge_base` tool exactly ONCE. Use one concise English
  search query that preserves every important user intent.
- If the user's query already contains English search terms, copy the user's
  wording unchanged into the tool's `query` argument. Do not add synonyms,
  related HR topics, or inferred intent.
- If the query contains no English search terms, translate it into concise
  English handbook vocabulary before calling the tool.
- Do not set or request the number of results; the tool enforces its own limit.
- NEVER answer the user's question yourself.
- NEVER summarize, rewrite, filter, or add to the retrieved snippets.
- The raw snippets returned by the tool are the only output that matters.
"""


def _select_search_query(user_query: str, tool_args: dict[str, object]) -> str:
    """Preserve English user intent; use the model only for translation."""
    if has_english_search_terms(user_query):
        return user_query
    translated_query = str(tool_args.get("query", "")).strip()
    return translated_query or user_query


def retriever_node(state: PipelineState) -> dict[str, object]:
    """Force a knowledge-base search and hand the snippets off via state.

    Args:
        state: Pipeline state containing the user ``query``, plus optional
            per-run ``search_mode`` / ``top_k`` overrides (UI knobs; the
            config defaults apply when absent).

    Returns:
        Partial state update with the retrieved ``snippets``, the scored
        ``hits`` (title/score/source metadata for presentation layers),
        and the ``search_query`` that was actually executed.
    """
    llm_with_tool = get_llm().bind_tools(
        [search_knowledge_base],
        tool_choice="required",  # structural guardrail: answering is impossible
    )
    ai_msg = llm_with_tool.invoke(
        [
            SystemMessage(content=RETRIEVER_SYSTEM_PROMPT),
            HumanMessage(content=state["query"]),
        ]
    )
    if not ai_msg.tool_calls:
        return {"snippets": [], "hits": []}

    # Execute one tool call only, through the same ranking path the tool
    # wraps (``search_scored`` keeps the score/source metadata that the
    # string-only tool output drops). The extra slice keeps the output
    # bound deterministic even if a lower layer misbehaves.
    search_query = _select_search_query(
        state["query"],
        ai_msg.tool_calls[0]["args"],
    )
    top_k = state.get("top_k") or TOP_K
    hits = search_scored(
        search_query,
        top_k=top_k,
        mode=state.get("search_mode"),
    )[:top_k]
    return {
        "snippets": [hit.as_snippet() for hit in hits],
        "hits": hits,
        "search_query": search_query,
    }

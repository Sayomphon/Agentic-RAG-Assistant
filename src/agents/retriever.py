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
from src.tools.retrieval import search_knowledge_base

if TYPE_CHECKING:
    from src.graph import PipelineState

RETRIEVER_SYSTEM_PROMPT = """\
You are the Data Retriever agent in a two-agent pipeline. Your ONLY job
is information retrieval from the company knowledge base.

Rules:
- ALWAYS call the `search_knowledge_base` tool to find snippets relevant
  to the user's query. Reformulate the query into effective search terms
  when that will retrieve better results (e.g. expand abbreviations,
  use the vocabulary a policy handbook would use).
- NEVER answer the user's question yourself.
- NEVER summarize, rewrite, filter, or add to the retrieved snippets.
- The raw snippets returned by the tool are the only output that matters.
"""


def retriever_node(state: PipelineState) -> dict[str, list[str]]:
    """Force a knowledge-base search and hand the snippets off via state.

    Args:
        state: Pipeline state containing the user ``query``.

    Returns:
        Partial state update with the retrieved ``snippets``.
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
    # Execute every tool call the model issued; dedupe while keeping order
    # in case reformulated searches return the same chunk twice.
    snippets: list[str] = []
    for tool_call in ai_msg.tool_calls:
        for snippet in search_knowledge_base.invoke(tool_call["args"]):
            if snippet not in snippets:
                snippets.append(snippet)
    return {"snippets": snippets}

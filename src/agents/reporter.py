"""Report Generator agent: grounded synthesis from retrieved snippets only.

Guardrails:
    - Prompt layer: answer ONLY from snippets, merge duplicates, and use a
      fixed not-found sentence when the snippets are insufficient.
    - Deterministic layer: when the retriever hands off zero snippets, the
      node returns the not-found sentence directly — no LLM call, so the
      fallback text is guaranteed byte-exact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents import get_llm

if TYPE_CHECKING:
    from src.graph import PipelineState

NOT_FOUND_SENTENCE = "I could not find this information in the knowledge base."

REPORTER_SYSTEM_PROMPT = f"""\
You are the Report Generator agent, an expert writer and synthesizer.
Write a clear, well-structured answer to the user's query using ONLY the
provided snippets from the company knowledge base.

Rules:
- Use ONLY information stated in the snippets. Never add outside
  knowledge, assumptions, or invented details.
- Merge overlapping snippets: if the same fact appears in more than one
  snippet, state it exactly once.
- If the snippets do not contain the information needed to answer the
  query, reply with exactly this sentence and nothing else:
  "{NOT_FOUND_SENTENCE}"
- Keep the answer concise, well formatted (short paragraphs or bullet
  points), and directly responsive to the query.
"""


def generator_node(state: PipelineState) -> dict[str, str]:
    """Synthesize the final grounded answer from the handed-off snippets.

    Args:
        state: Pipeline state containing ``query`` and ``snippets``.

    Returns:
        Partial state update with the final ``report``.
    """
    if not state["snippets"]:
        # Deterministic fallback: nothing retrieved, nothing to synthesize.
        return {"report": NOT_FOUND_SENTENCE}

    snippets_text = "\n\n".join(state["snippets"])
    msg = get_llm().invoke(
        [
            SystemMessage(content=REPORTER_SYSTEM_PROMPT),
            HumanMessage(
                content=f"User query: {state['query']}\n\nSnippets:\n{snippets_text}"
            ),
        ]
    )
    return {"report": str(msg.content)}

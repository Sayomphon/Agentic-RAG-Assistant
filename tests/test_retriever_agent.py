"""Tests for tool-call and output-bound guardrails in the Retriever Agent.

The retrieval core (``search_scored``) is patched *below* the tool, never
in the agent module, so every assertion here runs through the real
``search_knowledge_base`` tool object — if the node ever bypassed the tool
again, these tests would not notice a change in results, they would fail
on the tool never having been invoked.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.agents import retriever as retriever_module
from src.agents.retriever import retriever_node
from src.config import TOP_K
from src.retrievers.base import Chunk, ScoredChunk
from src.tools.retrieval import search_knowledge_base


def _tool_call(query: str, **extra_args: object) -> dict[str, object]:
    """A tool call shaped the way LangChain hands them back."""
    return {
        "name": search_knowledge_base.name,
        "args": {"query": query, **extra_args},
    }


def _fake_hits(count: int) -> list[ScoredChunk]:
    return [
        ScoredChunk(
            chunk=Chunk(title=f"T{i}", text=f"snippet-{i}", index=i),
            score=float(count - i),
            source="bm25",
        )
        for i in range(count)
    ]


class _FakeBoundLLM:
    def __init__(self, tool_calls: list[dict[str, object]]) -> None:
        self._tool_calls = tool_calls

    def invoke(self, _messages: object) -> SimpleNamespace:
        return SimpleNamespace(tool_calls=self._tool_calls)


class _FakeLLM:
    def __init__(self, tool_calls: list[dict[str, object]]) -> None:
        self._bound = _FakeBoundLLM(tool_calls)

    def bind_tools(self, _tools: object, **_kwargs: object) -> _FakeBoundLLM:
        return self._bound


class RetrieverAgentTests(unittest.TestCase):
    """Ensure provider behaviour cannot bypass retrieval output limits."""

    @patch("src.tools.retrieval.search_scored")
    @patch("src.agents.retriever.get_llm")
    def test_executes_only_first_tool_call_and_caps_output(
        self,
        mock_get_llm: Mock,
        mock_search: Mock,
    ) -> None:
        mock_get_llm.return_value = _FakeLLM(
            [
                _tool_call("expanded unrelated HR compensation terms"),
                _tool_call("second query"),
            ]
        )
        # A misbehaving lower layer returns more hits than requested; the
        # node's defensive slice must still cap the evidence set.
        mock_search.return_value = _fake_hits(TOP_K + 3)

        result = retriever_node(
            {"query": "What is the CEO's salary?", "snippets": [], "report": ""}
        )

        mock_search.assert_called_once_with(
            "What is the CEO's salary?", top_k=TOP_K, mode=None
        )
        self.assertEqual(len(result["snippets"]), TOP_K)
        self.assertEqual(len(result["hits"]), TOP_K)
        self.assertEqual(
            result["snippets"],
            [hit.as_snippet() for hit in mock_search.return_value[:TOP_K]],
        )

    @patch("src.tools.retrieval.search_scored")
    @patch("src.agents.retriever.get_llm")
    def test_dispatches_the_bound_tool_exactly_once(
        self,
        mock_get_llm: Mock,
        mock_search: Mock,
    ) -> None:
        """The tool object itself runs — the node has no other search path."""
        mock_get_llm.return_value = _FakeLLM([_tool_call("annual leave")])
        mock_search.return_value = _fake_hits(1)

        with patch.object(
            search_knowledge_base, "func", wraps=search_knowledge_base.func
        ) as tool_body:
            retriever_node(
                {"query": "annual leave", "snippets": [], "report": ""}
            )

        tool_body.assert_called_once_with(
            query="annual leave", top_k=TOP_K, mode=None
        )

    @patch("src.tools.retrieval.search_scored")
    @patch("src.agents.retriever.get_llm")
    def test_rewritten_retry_also_goes_through_the_tool(
        self,
        mock_get_llm: Mock,
        mock_search: Mock,
    ) -> None:
        """Retries take the same tool path — no shortcut on attempt 2+."""
        mock_search.return_value = _fake_hits(1)

        with patch.object(
            search_knowledge_base, "func", wraps=search_knowledge_base.func
        ) as tool_body:
            retriever_node(
                {
                    "query": "I want to quit my job",
                    "snippets": [],
                    "report": "",
                    "search_attempts": ["I want to quit my job"],
                    "rewritten_query": "resignation process",
                }
            )

        mock_get_llm.assert_not_called()
        tool_body.assert_called_once_with(
            query="resignation process", top_k=TOP_K, mode=None
        )

    @patch("src.tools.retrieval.search_scored")
    @patch("src.agents.retriever.get_llm")
    def test_model_arguments_cannot_override_trusted_config(
        self,
        mock_get_llm: Mock,
        mock_search: Mock,
    ) -> None:
        """``top_k``/``mode`` come from state, whatever the model asks for."""
        mock_get_llm.return_value = _FakeLLM(
            [_tool_call("annual leave", top_k=99, mode="hybrid")]
        )
        mock_search.return_value = _fake_hits(1)

        retriever_node({"query": "annual leave", "snippets": [], "report": ""})

        mock_search.assert_called_once_with("annual leave", top_k=TOP_K, mode=None)

    @patch("src.tools.retrieval.search_scored")
    @patch("src.agents.retriever.get_llm")
    def test_non_english_query_uses_model_translation(
        self,
        mock_get_llm: Mock,
        mock_search: Mock,
    ) -> None:
        mock_get_llm.return_value = _FakeLLM([_tool_call("remote work approval")])
        mock_search.return_value = _fake_hits(1)

        result = retriever_node(
            {
                "query": (
                    "ทำงานจากบ้านต้อง"
                    "ขออนุมัติอย่างไร"
                ),
                "snippets": [],
                "report": "",
            }
        )

        mock_search.assert_called_once_with(
            "remote work approval", top_k=TOP_K, mode=None
        )
        self.assertEqual(result["search_query"], "remote work approval")
        self.assertEqual(result["snippets"], ["[T0]\nsnippet-0"])

    @patch("src.tools.retrieval.search_scored")
    @patch("src.agents.retriever.get_llm")
    def test_state_overrides_reach_the_search(
        self,
        mock_get_llm: Mock,
        mock_search: Mock,
    ) -> None:
        mock_get_llm.return_value = _FakeLLM([_tool_call("annual leave")])
        mock_search.return_value = _fake_hits(2)

        retriever_node(
            {
                "query": "annual leave",
                "snippets": [],
                "report": "",
                "search_mode": "hybrid",
                "top_k": 2,
            }
        )

        mock_search.assert_called_once_with("annual leave", top_k=2, mode="hybrid")

    @patch("src.agents.retriever.get_llm")
    def test_missing_tool_call_fails_closed(self, mock_get_llm: Mock) -> None:
        mock_get_llm.return_value = _FakeLLM([])

        result = retriever_node({"query": "question", "snippets": [], "report": ""})

        # Fail closed, but the attempt is still recorded — the retry loop
        # terminates on the attempt count, so it must grow on every pass.
        self.assertEqual(
            result,
            {
                "snippets": [],
                "hits": [],
                "search_attempts": ["question"],
                "rewritten_query": "",
            },
        )

    @patch("src.tools.retrieval.search_scored")
    @patch("src.agents.retriever.get_llm")
    def test_unknown_tool_name_fails_closed(
        self,
        mock_get_llm: Mock,
        mock_search: Mock,
    ) -> None:
        mock_get_llm.return_value = _FakeLLM(
            [{"name": "answer_directly", "args": {"query": "question"}}]
        )

        result = retriever_node({"query": "question", "snippets": [], "report": ""})

        mock_search.assert_not_called()
        self.assertEqual(result["snippets"], [])
        self.assertEqual(result["search_attempts"], ["question"])

    def test_agent_module_exposes_no_direct_retrieval_path(self) -> None:
        """The bound tool is the module's only way into the knowledge base."""
        self.assertFalse(hasattr(retriever_module, "search_scored"))
        self.assertTrue(hasattr(retriever_module, "search_knowledge_base"))


if __name__ == "__main__":
    unittest.main()

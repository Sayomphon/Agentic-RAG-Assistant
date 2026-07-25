"""Regression tests for natural-language retrieval quality."""

from __future__ import annotations

import unittest

from evals.evaluate_retrieval import evaluate
from src.config import TOP_K
from src.tools.retrieval import get_retriever, search_knowledge_base


class RetrievalEvaluationTests(unittest.TestCase):
    """Keep every golden retrieval query precise and fully recalled."""

    def test_all_golden_cases_match_exactly(self) -> None:
        failures = [
            (
                result.case_id,
                sorted(result.expected),
                sorted(result.actual),
            )
            for result in evaluate()
            if not result.exact
        ]
        self.assertEqual(failures, [])

    def test_empty_and_punctuation_only_queries_return_nothing(self) -> None:
        retriever = get_retriever()
        self.assertEqual(retriever.search("", top_k=TOP_K), [])
        self.assertEqual(retriever.search("?!...", top_k=TOP_K), [])

    def test_non_positive_top_k_returns_nothing(self) -> None:
        self.assertEqual(get_retriever().search("annual leave", top_k=0), [])

    def test_tool_enforces_configured_top_k(self) -> None:
        snippets = search_knowledge_base.invoke(
            {"query": "international travel approval allowance insurance"}
        )
        self.assertLessEqual(len(snippets), TOP_K)


if __name__ == "__main__":
    unittest.main()

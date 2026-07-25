"""Regression tests for natural-language retrieval quality."""

from __future__ import annotations

import unittest

from src.config import KB_PATH, TOP_K
from src.evaluation.regression import evaluate
from src.retrievers import get_retriever
from src.retrievers.base import ScoredChunk, load_chunks
from src.tools.retrieval import search_knowledge_base


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
        hits = search_knowledge_base.invoke(
            {"query": "international travel approval allowance insurance"}
        )
        self.assertLessEqual(len(hits), TOP_K)
        self.assertTrue(all(isinstance(hit, ScoredChunk) for hit in hits))

    def test_tool_reads_the_required_knowledge_base_file(self) -> None:
        """The assignment's artifact is the default runtime source."""
        self.assertEqual(KB_PATH, "knowledge_base.txt")
        chunks = load_chunks()
        self.assertGreater(len(chunks), 1)
        self.assertEqual(
            {chunk.source_file for chunk in chunks}, {"knowledge_base.txt"}
        )


if __name__ == "__main__":
    unittest.main()

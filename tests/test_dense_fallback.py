"""Tests for the embedding retriever's failure boundary.

Every failure is injected at the OpenAI client, so these run offline and
make no network call. What they pin down is the degradation contract: a
provider problem must surface as ``EmbeddingIndexError`` — the one
exception the factory knows how to fall back from — never as a raw
provider error escaping into the pipeline.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from openai import OpenAIError

from src.retrievers import factory
from src.retrievers.base import Chunk
from src.retrievers.dense import EmbeddingIndexError, OpenAIEmbeddingRetriever
from src.retrievers.keyword import BM25Retriever
from src.retrievers.reranker import RerankingRetriever

_CHUNKS = [Chunk(title="T0", text="remote work requires approval", index=0)]


class DenseFailureBoundaryTests(unittest.TestCase):
    """Client construction and index build share one error boundary."""

    @patch("src.retrievers.dense.OpenAI", side_effect=OpenAIError("Missing credentials."))
    def test_client_construction_failure_is_translated(self, _mock_openai: Mock) -> None:
        with self.assertRaises(EmbeddingIndexError):
            OpenAIEmbeddingRetriever(_CHUNKS, cache_dir="/nonexistent-cache")

    @patch("src.retrievers.dense.OpenAI")
    def test_index_build_failure_is_translated(self, mock_openai: Mock) -> None:
        mock_openai.return_value.embeddings.create.side_effect = OpenAIError("API down")
        with self.assertRaises(EmbeddingIndexError):
            OpenAIEmbeddingRetriever(_CHUNKS, cache_dir="/nonexistent-cache")

    def test_query_failure_is_counted_before_degradation(self) -> None:
        retriever = object.__new__(OpenAIEmbeddingRetriever)
        retriever._query_failure_count = 0
        retriever._fallback = None
        retriever._embed_query = Mock(side_effect=OpenAIError("API down"))

        self.assertEqual(retriever.search("remote work", top_k=1), [])
        self.assertEqual(retriever.query_failure_count, 1)


class FactoryDegradationTests(unittest.TestCase):
    """A missing credential degrades retrieval; it never crashes the run."""

    def setUp(self) -> None:
        # The factory caches one retriever per mode for the process, so a
        # failure injected here must not leak into (or out of) other tests.
        factory._build_retriever.cache_clear()
        self.addCleanup(factory._build_retriever.cache_clear)

    @patch("src.retrievers.dense.OpenAI", side_effect=OpenAIError("Missing credentials."))
    def test_semantic_mode_falls_back_to_keyword(self, _mock_openai: Mock) -> None:
        self.assertIsInstance(factory.get_retriever("semantic"), BM25Retriever)

    @patch("src.retrievers.dense.OpenAI", side_effect=OpenAIError("Missing credentials."))
    def test_hybrid_mode_falls_back_to_a_single_keyword_index(
        self, _mock_openai: Mock
    ) -> None:
        # Plain BM25, not a fusion wrapper around it — so the lexical
        # evidence is counted once, not once per fused side.
        self.assertIsInstance(factory.get_retriever("hybrid"), BM25Retriever)

    @patch("src.retrievers.dense.OpenAIEmbeddingRetriever")
    def test_successful_hybrid_mode_adds_reranking_and_preserves_identity(
        self,
        mock_dense: Mock,
    ) -> None:
        mock_dense.return_value = Mock()

        retriever = factory.get_retriever("hybrid")

        self.assertIsInstance(retriever, RerankingRetriever)
        self.assertEqual(retriever.SOURCE, "hybrid")


if __name__ == "__main__":
    unittest.main()

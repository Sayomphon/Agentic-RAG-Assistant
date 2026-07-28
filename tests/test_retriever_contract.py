"""Executable contract shared by current and future Retriever backends."""

from __future__ import annotations

import math
import re
import unittest
from dataclasses import fields
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from openai import OpenAIError

from src.retrievers.base import (
    RETRIEVER_CONTRACT_VERSION,
    Chunk,
    Retriever,
    ScoredChunk,
    load_chunks,
)
from src.retrievers.dense import OpenAIEmbeddingRetriever
from src.retrievers.hybrid import HybridRetriever
from src.retrievers.keyword import BM25Retriever
from src.retrievers.reranker import RerankingRetriever

_SEARCHABLE_TEXT = re.compile(r"[a-zA-Z0-9\u0e00-\u0e7f]")


def _hit(index: int, score: float, source: str) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            title=f"Section {index}",
            text=f"Evidence body {index}",
            index=index,
            source_file="contract-fixture.txt",
        ),
        score=score,
        source=source,
    )


class _StaticRetriever:
    """Deterministic, contract-compliant fixture for composition tests."""

    def __init__(self, hits: list[ScoredChunk]) -> None:
        self._hits = hits
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int) -> list[ScoredChunk]:
        self.calls.append((query, top_k))
        if top_k <= 0 or not _SEARCHABLE_TEXT.search(query):
            return []
        return self._hits[:top_k]


class _ReverseReranker:
    def rerank(
        self,
        _query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        return [
            ScoredChunk(
                chunk=hit.chunk,
                score=float(position),
                source=hit.source,
                retrieval_score=hit.score,
                reranker_score=float(position),
            )
            for position, hit in enumerate(reversed(candidates), start=1)
        ][::-1][:top_k]


def _dense_fixture() -> OpenAIEmbeddingRetriever:
    """Build a deterministic dense retriever without API or filesystem I/O."""
    retriever = object.__new__(OpenAIEmbeddingRetriever)
    retriever._chunks = [
        Chunk("Dense A", "alpha", 100, "contract-fixture.txt"),
        Chunk("Dense B", "beta", 101, "contract-fixture.txt"),
    ]
    retriever._min_cosine = -1.0
    retriever._fallback = None
    retriever._query_failure_count = 0
    retriever._matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    retriever._embed_query = Mock(
        return_value=np.array([1.0, 0.0], dtype=np.float32)
    )
    return retriever


class RetrieverContractTests(unittest.TestCase):
    """Freeze observable behavior before adding an Enterprise backend."""

    @classmethod
    def setUpClass(cls) -> None:
        keyword = BM25Retriever(load_chunks())
        dense = _dense_fixture()
        hybrid = HybridRetriever(
            _StaticRetriever([_hit(1, 0.9, "bm25"), _hit(2, 0.7, "bm25")]),
            _StaticRetriever([_hit(2, 0.8, "dense"), _hit(3, 0.6, "dense")]),
            candidate_k=3,
        )
        reranked = RerankingRetriever(
            _StaticRetriever(
                [_hit(4, 0.9, "hybrid"), _hit(5, 0.8, "hybrid")]
            ),
            _ReverseReranker(),
            candidate_k=2,
            min_reranker_score=None,
        )
        cls.retrievers: dict[str, tuple[Retriever, str]] = {
            "keyword": (keyword, "international travel approval"),
            "dense": (dense, "alpha"),
            "hybrid": (hybrid, "travel approval"),
            "reranked": (reranked, "travel approval"),
        }

    def assert_valid_hits(self, hits: list[ScoredChunk], top_k: int) -> None:
        self.assertIsInstance(hits, list)
        self.assertLessEqual(len(hits), top_k)
        self.assertTrue(all(isinstance(hit, ScoredChunk) for hit in hits))
        self.assertTrue(all(math.isfinite(hit.score) for hit in hits))
        self.assertTrue(all(hit.source.strip() for hit in hits))
        self.assertEqual(
            [hit.score for hit in hits],
            sorted((hit.score for hit in hits), reverse=True),
        )
        indexes = [hit.chunk.index for hit in hits]
        self.assertEqual(len(indexes), len(set(indexes)))
        for hit in hits:
            self.assertEqual(
                hit.as_snippet(),
                f"[{hit.title}]\n{hit.text}",
            )

    def test_contract_version_and_runtime_protocol_are_frozen(self) -> None:
        self.assertEqual(RETRIEVER_CONTRACT_VERSION, "1.0.0")
        for name, (retriever, _query) in self.retrievers.items():
            with self.subTest(retriever=name):
                self.assertIsInstance(retriever, Retriever)

    def test_normative_contract_documents_the_r2_fail_safe_policy(self) -> None:
        contract_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "RETRIEVER_CONTRACT.md"
        )
        contract = contract_path.read_text(encoding="utf-8")

        self.assertIn("Primary reranker", contract)
        self.assertIn("Secondary reranker", contract)
        self.assertIn("production-default `fail_closed`", contract)
        self.assertIn("raw exception details", contract)

    def test_scored_chunk_required_fields_are_stable(self) -> None:
        self.assertEqual(
            [field.name for field in fields(ScoredChunk)],
            [
                "chunk",
                "score",
                "source",
                "retrieval_score",
                "reranker_score",
            ],
        )

    def test_all_implementations_return_valid_best_first_hits(self) -> None:
        for name, (retriever, query) in self.retrievers.items():
            with self.subTest(retriever=name):
                hits = retriever.search(query, top_k=2)
                self.assertTrue(hits)
                self.assert_valid_hits(hits, top_k=2)

    def test_all_implementations_enforce_non_positive_top_k(self) -> None:
        for name, (retriever, query) in self.retrievers.items():
            with self.subTest(retriever=name):
                self.assertEqual(retriever.search(query, top_k=0), [])
                self.assertEqual(retriever.search(query, top_k=-1), [])

    def test_all_implementations_reject_non_searchable_queries(self) -> None:
        for name, (retriever, _query) in self.retrievers.items():
            for query in ("", "   ", "?!..."):
                with self.subTest(retriever=name, query=query):
                    self.assertEqual(retriever.search(query, top_k=3), [])

    def test_hybrid_deduplicates_logical_chunks(self) -> None:
        duplicate = _hit(7, 0.9, "bm25")
        hybrid = HybridRetriever(
            _StaticRetriever([duplicate]),
            _StaticRetriever([_hit(7, 0.8, "dense")]),
            candidate_k=2,
        )

        hits = hybrid.search("duplicate evidence", top_k=2)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].source, "bm25+dense")

    def test_dense_query_failure_preserves_fallback_provenance(self) -> None:
        fallback_hit = _hit(8, 3.0, "bm25")
        fallback = _StaticRetriever([fallback_hit])
        dense = _dense_fixture()
        dense._fallback = fallback
        dense._embed_query = Mock(side_effect=OpenAIError("provider unavailable"))

        hits = dense.search("fallback query", top_k=1)

        self.assertEqual(hits, [fallback_hit])
        self.assertEqual(dense.query_failure_count, 1)
        self.assertEqual(hits[0].source, "bm25")

    def test_reranker_failure_fails_closed_without_breaking_contract(self) -> None:
        base_hits = [_hit(9, 0.9, "hybrid"), _hit(10, 0.8, "hybrid")]
        base = _StaticRetriever(base_hits)
        failing_reranker = Mock()
        failing_reranker.rerank.side_effect = RuntimeError("model unavailable")
        retriever = RerankingRetriever(
            base,
            failing_reranker,
            candidate_k=2,
        )

        hits = retriever.search("fallback query", top_k=1)

        self.assertEqual(hits, [])
        self.assertEqual(retriever.reranker_fallback_count, 1)
        self.assertEqual(retriever.fail_closed_count, 1)


if __name__ == "__main__":
    unittest.main()

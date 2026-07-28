"""Tests for local reranking contracts, bounds, and degradation."""

from __future__ import annotations

import time
import unittest

from src.retrievers.base import Chunk, ScoredChunk
from src.retrievers.reranker import (
    LocalCrossEncoderReranker,
    RerankerTimeoutError,
    RerankingRetriever,
)


def _hit(index: int, score: float = 1.0) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(title=f"Section {index}", text=f"Evidence {index}", index=index),
        score=score,
        source="hybrid",
    )


class _Backend:
    def __init__(self, scores: list[float], delay: float = 0.0) -> None:
        self._scores = scores
        self._delay = delay
        self.calls = 0

    def predict(
        self,
        sentences: object,
        *,
        batch_size: int,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> list[float]:
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        return self._scores


class _BaseRetriever:
    SOURCE = "hybrid"

    def __init__(self, hits: list[ScoredChunk]) -> None:
        self._hits = hits
        self.requested_top_k: list[int] = []

    def search(self, _query: str, top_k: int) -> list[ScoredChunk]:
        self.requested_top_k.append(top_k)
        return self._hits[:top_k]


class _FailingReranker:
    def rerank(
        self,
        _query: str,
        _candidates: list[ScoredChunk],
        _top_k: int,
    ) -> list[ScoredChunk]:
        raise RuntimeError("Sensitive third-party failure details")


class LocalRerankerTests(unittest.TestCase):
    def test_reranks_and_preserves_retrieval_metadata(self) -> None:
        backend = _Backend([0.2, 0.9, 0.5])
        reranker = LocalCrossEncoderReranker(
            model_factory=lambda: backend,
            timeout_seconds=1,
        )

        hits = reranker.rerank(
            "query",
            [_hit(0, 0.8), _hit(1, 0.7), _hit(2, 0.6)],
            top_k=2,
        )

        self.assertEqual([hit.title for hit in hits], ["Section 1", "Section 2"])
        self.assertEqual([hit.reranker_score for hit in hits], [0.9, 0.5])
        self.assertEqual([hit.retrieval_score for hit in hits], [0.7, 0.6])
        self.assertEqual([hit.source for hit in hits], ["hybrid", "hybrid"])

    def test_model_is_loaded_lazily_and_only_once(self) -> None:
        backend = _Backend([1.0])
        loads = 0

        def factory() -> _Backend:
            nonlocal loads
            loads += 1
            return backend

        reranker = LocalCrossEncoderReranker(
            model_factory=factory,
            timeout_seconds=1,
        )
        self.assertEqual(loads, 0)

        reranker.rerank("first", [_hit(0)], top_k=1)
        reranker.rerank("second", [_hit(0)], top_k=1)

        self.assertEqual(loads, 1)
        self.assertEqual(backend.calls, 2)

    def test_warmup_loads_without_running_inference(self) -> None:
        backend = _Backend([1.0])
        loads = 0

        def factory() -> _Backend:
            nonlocal loads
            loads += 1
            return backend

        reranker = LocalCrossEncoderReranker(model_factory=factory)

        reranker.warmup()
        reranker.warmup()

        self.assertEqual(loads, 1)
        self.assertEqual(backend.calls, 0)

    def test_timeout_is_bounded_and_reported(self) -> None:
        backend = _Backend([1.0], delay=0.1)
        reranker = LocalCrossEncoderReranker(
            model_factory=lambda: backend,
            timeout_seconds=0.01,
        )

        started = time.perf_counter()
        with self.assertRaises(RerankerTimeoutError):
            reranker.rerank("query", [_hit(0)], top_k=1)

        self.assertLess(time.perf_counter() - started, 0.08)


class RerankingRetrieverTests(unittest.TestCase):
    def test_warmup_delegates_without_running_inference(self) -> None:
        backend = _Backend([1.0])
        loads = 0

        def factory() -> _Backend:
            nonlocal loads
            loads += 1
            return backend

        retriever = RerankingRetriever(
            _BaseRetriever([_hit(0)]),
            LocalCrossEncoderReranker(model_factory=factory),
        )

        retriever.warmup()
        retriever.warmup()

        self.assertEqual(loads, 1)
        self.assertEqual(backend.calls, 0)

    def test_retrieves_candidates_before_reranking(self) -> None:
        base = _BaseRetriever([_hit(index) for index in range(10)])
        backend = _Backend([float(index) for index in range(6)])
        reranker = LocalCrossEncoderReranker(
            model_factory=lambda: backend,
            timeout_seconds=1,
        )
        retriever = RerankingRetriever(base, reranker, candidate_k=6)

        hits = retriever.search("query", top_k=2)

        self.assertEqual(base.requested_top_k, [6])
        self.assertEqual([hit.title for hit in hits], ["Section 5", "Section 4"])
        self.assertEqual(retriever.SOURCE, "hybrid")

    def test_failure_falls_back_to_original_order(self) -> None:
        original = [_hit(0, 0.9), _hit(1, 0.8), _hit(2, 0.7)]
        retriever = RerankingRetriever(
            _BaseRetriever(original),
            _FailingReranker(),
            candidate_k=3,
        )

        hits = retriever.search("private query", top_k=2)

        self.assertEqual(hits, original[:2])
        self.assertEqual(retriever.reranker_fallback_count, 1)

    def test_answerability_gate_rejects_low_reranker_scores(self) -> None:
        base = _BaseRetriever([_hit(index) for index in range(3)])
        backend = _Backend([0.05, 0.50, 0.90])
        reranker = LocalCrossEncoderReranker(
            model_factory=lambda: backend,
            timeout_seconds=1,
        )
        retriever = RerankingRetriever(
            base,
            reranker,
            candidate_k=3,
            min_reranker_score=0.50,
        )

        hits = retriever.search("query", top_k=3)

        self.assertEqual([hit.reranker_score for hit in hits], [0.90, 0.50])
        self.assertEqual(retriever.answerability_rejection_count, 1)

    def test_answerability_gate_can_reject_every_candidate(self) -> None:
        base = _BaseRetriever([_hit(0), _hit(1)])
        backend = _Backend([0.10, 0.20])
        reranker = LocalCrossEncoderReranker(
            model_factory=lambda: backend,
            timeout_seconds=1,
        )
        retriever = RerankingRetriever(
            base,
            reranker,
            candidate_k=2,
            min_reranker_score=0.80,
        )

        self.assertEqual(retriever.search("query", top_k=2), [])
        self.assertEqual(retriever.answerability_rejection_count, 2)

    def test_disabled_answerability_gate_preserves_reranked_results(self) -> None:
        base = _BaseRetriever([_hit(0), _hit(1)])
        backend = _Backend([-4.0, -8.0])
        reranker = LocalCrossEncoderReranker(
            model_factory=lambda: backend,
            timeout_seconds=1,
        )
        retriever = RerankingRetriever(
            base,
            reranker,
            candidate_k=2,
            min_reranker_score=None,
        )

        self.assertEqual(len(retriever.search("query", top_k=2)), 2)
        self.assertEqual(retriever.answerability_rejection_count, 0)

    def test_non_positive_top_k_skips_retrieval_and_reranking(self) -> None:
        base = _BaseRetriever([_hit(0)])
        retriever = RerankingRetriever(
            base,
            _FailingReranker(),
            candidate_k=3,
        )

        self.assertEqual(retriever.search("query", top_k=0), [])
        self.assertEqual(base.requested_top_k, [])


if __name__ == "__main__":
    unittest.main()

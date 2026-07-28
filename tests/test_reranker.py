"""Tests for local reranking contracts, bounds, and degradation."""

from __future__ import annotations

import time
import unittest
from unittest.mock import Mock, patch

from src.agents.reporter import NOT_FOUND_SENTENCE, generator_node
from src.retrievers.base import Chunk, ScoredChunk
from src.retrievers.context import ContextBuilder
from src.retrievers.reranker import (
    CascadingReranker,
    FailureReasonCode,
    LocalCrossEncoderReranker,
    RerankerBusyError,
    RerankerInvalidScoreError,
    RerankerModelLoadError,
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
    model_name = "sensitive-model"

    def __init__(
        self,
        error: Exception | None = None,
    ) -> None:
        self._error = error or RuntimeError(
            "Sensitive third-party failure details"
        )
        self.calls = 0

    def rerank(
        self,
        _query: str,
        _candidates: list[ScoredChunk],
        _top_k: int,
    ) -> list[ScoredChunk]:
        self.calls += 1
        raise self._error


class _StaticReranker:
    def __init__(self, scores: list[float], model_name: str) -> None:
        self._scores = scores
        self.model_name = model_name
        self.calls = 0

    def rerank(
        self,
        _query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        self.calls += 1
        return [
            ScoredChunk(
                chunk=hit.chunk,
                score=score,
                source=hit.source,
                retrieval_score=hit.score,
                reranker_score=score,
            )
            for hit, score in zip(candidates, self._scores, strict=True)
        ][:top_k]


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

    def test_invalid_non_finite_scores_are_rejected(self) -> None:
        reranker = LocalCrossEncoderReranker(
            model_factory=lambda: _Backend([float("nan")]),
            timeout_seconds=1,
        )

        with self.assertRaises(RerankerInvalidScoreError):
            reranker.rerank("query", [_hit(0)], top_k=1)

    @patch("sentence_transformers.CrossEncoder")
    @patch("huggingface_hub.snapshot_download")
    def test_immutable_revision_is_passed_to_snapshot_loader(
        self,
        mock_snapshot_download: Mock,
        mock_cross_encoder: Mock,
    ) -> None:
        revision = "a" * 40
        mock_snapshot_download.return_value = "/approved/snapshot"
        reranker = LocalCrossEncoderReranker(
            model_name="approved/model",
            model_revision=revision,
            cache_dir=".cache/approved",
            local_files_only=True,
        )

        reranker.warmup()

        mock_snapshot_download.assert_called_once_with(
            repo_id="approved/model",
            revision=revision,
            cache_dir=".cache/approved",
            local_files_only=True,
        )
        self.assertFalse(mock_cross_encoder.call_args.kwargs["trust_remote_code"])


class CascadingRerankerTests(unittest.TestCase):
    def test_primary_success_does_not_touch_secondary(self) -> None:
        primary = _StaticReranker([0.9], "primary-model")
        secondary = _StaticReranker([0.8], "secondary-model")
        cascade = CascadingReranker(primary, secondary)

        hits = cascade.rerank("query", [_hit(0)], top_k=1)

        self.assertEqual(hits[0].reranker_score, 0.9)
        self.assertEqual(primary.calls, 1)
        self.assertEqual(secondary.calls, 0)
        self.assertEqual(cascade.active_reranker_model, "primary-model")
        self.assertEqual(cascade.primary_reranker_failure_count, 0)

    def test_primary_failure_uses_secondary_and_sanitized_telemetry(self) -> None:
        primary = _FailingReranker(RerankerModelLoadError("private path"))
        secondary = _StaticReranker([0.8], "secondary-model")
        cascade = CascadingReranker(primary, secondary)

        hits = cascade.rerank(
            "private query",
            [_hit(0)],
            top_k=1,
        )

        self.assertEqual(hits[0].reranker_score, 0.8)
        self.assertEqual(cascade.primary_reranker_failure_count, 1)
        self.assertEqual(cascade.secondary_reranker_usage_count, 1)
        self.assertEqual(cascade.secondary_reranker_failure_count, 0)
        self.assertEqual(cascade.active_reranker_model, "secondary-model")
        self.assertEqual(
            cascade.last_fallback_reason_code,
            FailureReasonCode.MODEL_LOAD_FAILED.value,
        )

    def test_primary_timeout_uses_secondary(self) -> None:
        cascade = CascadingReranker(
            _FailingReranker(RerankerTimeoutError("private timeout")),
            _StaticReranker([0.7], "secondary-model"),
        )

        hits = cascade.rerank("query", [_hit(0)], top_k=1)

        self.assertEqual(hits[0].reranker_score, 0.7)
        self.assertEqual(
            cascade.last_fallback_reason_code,
            FailureReasonCode.INFERENCE_TIMEOUT.value,
        )

    def test_busy_primary_uses_secondary(self) -> None:
        cascade = CascadingReranker(
            _FailingReranker(RerankerBusyError("private busy state")),
            _StaticReranker([0.7], "secondary-model"),
        )

        cascade.rerank("query", [_hit(0)], top_k=1)

        self.assertEqual(
            cascade.last_fallback_reason_code,
            FailureReasonCode.WORKER_BUSY.value,
        )

    def test_invalid_primary_output_uses_secondary(self) -> None:
        cascade = CascadingReranker(
            _StaticReranker([float("nan")], "invalid-primary"),
            _StaticReranker([0.7], "secondary-model"),
        )

        hits = cascade.rerank("query", [_hit(0)], top_k=1)

        self.assertEqual(hits[0].reranker_score, 0.7)
        self.assertEqual(
            cascade.last_fallback_reason_code,
            FailureReasonCode.INVALID_SCORE_ARRAY.value,
        )

    def test_out_of_memory_primary_uses_secondary(self) -> None:
        cascade = CascadingReranker(
            _FailingReranker(MemoryError("private allocation")),
            _StaticReranker([0.7], "secondary-model"),
        )

        cascade.rerank("query", [_hit(0)], top_k=1)

        self.assertEqual(
            cascade.last_fallback_reason_code,
            FailureReasonCode.OUT_OF_MEMORY.value,
        )


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

    def test_primary_and_secondary_failure_fail_closed(self) -> None:
        original = [_hit(0, 0.9), _hit(1, 0.8), _hit(2, 0.7)]
        cascade = CascadingReranker(
            _FailingReranker(RerankerModelLoadError("private primary")),
            _FailingReranker(RuntimeError("private secondary")),
        )
        retriever = RerankingRetriever(
            _BaseRetriever(original),
            cascade,
            candidate_k=3,
        )

        with self.assertLogs("src.retrievers.reranker", level="WARNING") as logs:
            hits = retriever.search("private query", top_k=2)

        self.assertEqual(hits, [])
        self.assertEqual(retriever.reranker_fallback_count, 1)
        self.assertEqual(retriever.primary_reranker_failure_count, 1)
        self.assertEqual(retriever.secondary_reranker_usage_count, 1)
        self.assertEqual(retriever.secondary_reranker_failure_count, 1)
        self.assertEqual(retriever.fail_closed_count, 1)
        self.assertEqual(retriever.fusion_fallback_count, 0)
        log_payload = "\n".join(logs.output)
        self.assertNotIn("private query", log_payload)
        self.assertNotIn("private primary", log_payload)
        self.assertNotIn("private secondary", log_payload)
        self.assertNotIn("Evidence 0", log_payload)

        with patch("src.agents.reporter.get_llm") as mock_get_llm:
            answer = generator_node(
                {"query": "private query", "snippets": []}  # type: ignore[arg-type]
            )
        mock_get_llm.assert_not_called()
        self.assertEqual(answer["report"], NOT_FOUND_SENTENCE)

    def test_secondary_uses_its_independent_answerability_threshold(self) -> None:
        cascade = CascadingReranker(
            _FailingReranker(),
            _StaticReranker([0.4, 0.2], "secondary-model"),
        )
        retriever = RerankingRetriever(
            _BaseRetriever([_hit(0), _hit(1)]),
            cascade,
            candidate_k=2,
            min_reranker_score=0.9,
            secondary_min_reranker_score=0.3,
        )

        hits = retriever.search("query", top_k=2)

        self.assertEqual([hit.reranker_score for hit in hits], [0.4])
        self.assertEqual(retriever.answerability_rejection_count, 1)
        self.assertEqual(retriever.active_reranker_model, "secondary-model")
        context = ContextBuilder(
            max_context_chars=1_000,
            min_body_chars=5,
        ).build(hits)
        self.assertEqual(context.snippets, ("[Section 0]\nEvidence 0",))

    def test_failure_path_not_found_discipline_is_100_percent(self) -> None:
        retriever = RerankingRetriever(
            _BaseRetriever([_hit(0)]),
            CascadingReranker(_FailingReranker(), _FailingReranker()),
        )
        correct = 0

        with self.assertLogs("src.retrievers.reranker", level="WARNING"):
            for index in range(10):
                hits = retriever.search(f"negative case {index}", top_k=1)
                answer = generator_node(
                    {"query": f"negative case {index}", "snippets": []}
                )
                correct += int(
                    not hits and answer["report"] == NOT_FOUND_SENTENCE
                )

        self.assertEqual(correct, 10)
        self.assertEqual(retriever.fail_closed_count, 10)

    def test_fusion_order_is_available_only_as_explicit_policy(self) -> None:
        original = [_hit(0, 0.9), _hit(1, 0.8)]
        retriever = RerankingRetriever(
            _BaseRetriever(original),
            _FailingReranker(),
            candidate_k=2,
            failure_policy="fusion_order",
        )

        with self.assertLogs("src.retrievers.reranker", level="WARNING"):
            hits = retriever.search("query", top_k=1)

        self.assertEqual(hits, original[:1])
        self.assertEqual(retriever.fusion_fallback_count, 1)
        self.assertEqual(retriever.fail_closed_count, 0)

    def test_conservative_policy_without_reviewed_gate_fails_closed(self) -> None:
        retriever = RerankingRetriever(
            _BaseRetriever([_hit(0)]),
            _FailingReranker(),
            failure_policy="conservative",
        )

        with self.assertLogs("src.retrievers.reranker", level="WARNING"):
            hits = retriever.search("query", top_k=1)

        self.assertEqual(hits, [])
        self.assertEqual(retriever.fail_closed_count, 1)

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

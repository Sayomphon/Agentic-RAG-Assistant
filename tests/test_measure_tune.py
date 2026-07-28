"""Tests for the Track A Step 3 measurement and tuning decision logic."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.evaluation.run_measure_tune import (
    PreparedCase,
    ProfileEvaluation,
    RESULTS_JSON_PATH,
    RESULTS_MARKDOWN_PATH,
    TuneProfile,
    _fuse_candidates,
    _load_prepared_cache,
    _profile_payload,
    _rerank_from_scores,
    _validate_output_paths,
    _write_prepared_cache,
    evaluate_profile,
    select_balanced_profile,
    select_profile,
)
from src.retrievers.base import Chunk, ScoredChunk


def _hit(index: int, score: float, source: str) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            title=f"Section {index}",
            text=("Evidence " * 20).strip(),
            index=index,
        ),
        score=score,
        source=source,
    )


class TuneProfileTests(unittest.TestCase):
    def test_rejects_unbounded_or_inconsistent_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "candidate_k"):
            TuneProfile(0, 1, 0.3, None, 100)
        with self.assertRaisesRegex(ValueError, "top_k"):
            TuneProfile(2, 3, 0.3, None, 100)
        with self.assertRaisesRegex(ValueError, "min_cosine"):
            TuneProfile(2, 1, float("nan"), None, 100)
        with self.assertRaisesRegex(ValueError, "max_context_chars"):
            TuneProfile(2, 1, 0.3, None, 0)

    def test_profile_id_is_stable_and_complete(self) -> None:
        profile = TuneProfile(24, 4, 0.34, 0.10, 6_000)
        self.assertEqual(
            profile.profile_id,
            "c24-k4-cos0.34-rron-0.10-ctx6000",
        )


class ReplayPipelineTests(unittest.TestCase):
    def test_fusion_applies_dense_threshold_before_rrf(self) -> None:
        keyword = [_hit(0, 8.0, "bm25")]
        dense = [
            _hit(1, 0.60, "dense"),
            _hit(2, 0.20, "dense"),
        ]

        hits = _fuse_candidates(
            "query",
            keyword,
            dense,
            candidate_k=3,
            min_cosine=0.30,
        )

        self.assertEqual({hit.title for hit in hits}, {"Section 0", "Section 1"})

    def test_cached_reranking_is_stable_and_preserves_scores(self) -> None:
        candidates = [
            _hit(0, 0.8, "hybrid"),
            _hit(1, 0.7, "hybrid"),
            _hit(2, 0.6, "hybrid"),
        ]

        hits = _rerank_from_scores(
            candidates,
            {0: 0.10, 1: 0.90, 2: 0.50},
            top_k=2,
            min_score=0.50,
        )

        self.assertEqual([hit.title for hit in hits], ["Section 1", "Section 2"])
        self.assertEqual([hit.reranker_score for hit in hits], [0.90, 0.50])
        self.assertEqual([hit.retrieval_score for hit in hits], [0.7, 0.6])

    def test_prepared_cache_excludes_content_and_is_owner_only(self) -> None:
        case = {
            "id": "safe-cache",
            "category": "english_answerable",
            "language": "en",
            "query": "SENSITIVE EVALUATION QUERY",
            "expected_titles": ["Private Title"],
        }
        chunk = Chunk(
            title="Private Title",
            text="PRIVATE DOCUMENT BODY",
            index=0,
        )
        prepared = PreparedCase(
            case=case,  # type: ignore[arg-type]
            keyword_hits=(ScoredChunk(chunk, 2.0, "bm25"),),
            dense_hits=(ScoredChunk(chunk, 0.5, "dense"),),
            reranker_scores={0: 0.9},
            keyword_latency_ms=0.1,
            dense_latency_ms=1.0,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prepared.json"
            _write_prepared_cache(
                [prepared],
                {"min": 0.9, "max": 0.9, "p50": 0.9, "p95": 0.9},
                path,
            )
            serialized = path.read_text(encoding="utf-8")
            restored = _load_prepared_cache([case], [chunk], path)  # type: ignore[list-item]

            self.assertNotIn(case["query"], serialized)
            self.assertNotIn(chunk.title, serialized)
            self.assertNotIn(chunk.text, serialized)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIsNotNone(restored)

    def test_v2_outputs_cannot_overwrite_historical_or_existing_evidence(
        self,
    ) -> None:
        self.assertEqual(RESULTS_JSON_PATH.name, "track_a_ablation_results_v2.json")
        self.assertEqual(
            RESULTS_MARKDOWN_PATH.name,
            "track_a_ablation_results_v2.md",
        )
        with self.assertRaisesRegex(ValueError, "historical"):
            _validate_output_paths(
                RESULTS_JSON_PATH.parent / "track_a_step3_results.json",
                Path("new-report.md"),
            )
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.json"
            existing.touch()
            with self.assertRaisesRegex(FileExistsError, "versioned"):
                _validate_output_paths(
                    existing,
                    Path(directory) / "new-report.md",
                )


class SelectionTests(unittest.TestCase):
    def _evaluation(
        self,
        *,
        profile: TuneProfile,
        score: float,
        discipline: float,
        hard_gates: bool = True,
    ) -> ProfileEvaluation:
        metrics = {
            "hit_rate_at_k": 1.0,
            "recall_at_k": 0.9,
            "mrr": 0.9,
            "false_positive_rate": 1.0 - discipline,
            "not_found_discipline": discipline,
            "latency_avg_ms": 0.0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
        }
        return ProfileEvaluation(
            profile=profile,
            metrics=metrics,
            category_metrics={"thai_answerable": {"recall": 1.0}},
            quality_score=score,
            passed_hard_gates=hard_gates,
            passed_safety_target=discipline >= 0.9,
            gate_failures=() if hard_gates else ("regression",),
            context_avg_chars=100.0,
            context_p95_chars=100.0,
            context_truncation_rate=0.0,
            context_header_validity=1.0,
            context_budget_validity=1.0,
            average_final_hits=1.0,
            cases=(),
        )

    def test_selection_excludes_regressions_and_prioritizes_safety(self) -> None:
        unsafe_high_score = self._evaluation(
            profile=TuneProfile(12, 4, 0.3, None, 4_000),
            score=0.99,
            discipline=0.8,
        )
        safe = self._evaluation(
            profile=TuneProfile(24, 4, 0.3, 0.1, 6_000),
            score=0.90,
            discipline=0.9,
        )
        regressed = self._evaluation(
            profile=TuneProfile(30, 6, 0.3, 0.1, 12_000),
            score=1.0,
            discipline=1.0,
            hard_gates=False,
        )

        self.assertIs(select_profile([unsafe_high_score, safe, regressed]), safe)

    def test_balanced_selection_keeps_quality_while_reducing_candidates(
        self,
    ) -> None:
        quality_winner = self._evaluation(
            profile=TuneProfile(30, 6, 0.1, 0.01, 6_000),
            score=0.90,
            discipline=0.8,
        )
        balanced = self._evaluation(
            profile=TuneProfile(12, 6, 0.1, 0.01, 6_000),
            score=0.82,
            discipline=0.8,
        )
        too_much_quality_loss = self._evaluation(
            profile=TuneProfile(6, 4, 0.1, 0.01, 6_000),
            score=0.70,
            discipline=0.8,
        )

        self.assertIs(
            select_balanced_profile(
                [quality_winner, balanced, too_much_quality_loss],
                quality_winner,
            ),
            balanced,
        )

    def test_sanitized_payload_does_not_include_raw_query_or_body(self) -> None:
        result = self._evaluation(
            profile=TuneProfile(24, 4, 0.3, 0.1, 6_000),
            score=0.9,
            discipline=1.0,
        )

        payload = _profile_payload(result, include_cases=True)
        serialized = str(payload).lower()

        self.assertNotIn("query", serialized)
        self.assertNotIn("snippet", serialized)
        self.assertNotIn("document_body", serialized)
        self.assertNotIn("citation_validity", payload)
        self.assertEqual(payload["context_header_validity"], 1.0)
        self.assertEqual(payload["context_budget_validity"], 1.0)
        self.assertIsNone(payload["answer_citation_validity"])
        self.assertIsNone(payload["answer_citation_coverage"])


class ProfileEvaluationTests(unittest.TestCase):
    def test_profile_applies_context_budget_and_passes_improvement_gates(
        self,
    ) -> None:
        case = {
            "id": "th_case",
            "category": "thai_answerable",
            "language": "th",
            "query": "คำถาม",
            "expected_titles": ["Section 0"],
        }
        prepared = PreparedCase(
            case=case,  # type: ignore[arg-type]
            keyword_hits=(),
            dense_hits=(_hit(0, 0.6, "dense"),),
            reranker_scores={0: 0.9},
            keyword_latency_ms=0.1,
            dense_latency_ms=1.0,
        )
        baseline_categories = {
            "english_answerable": {"recall": 1.0, "mrr": 1.0},
            "mixed_answerable": {"recall": 1.0, "mrr": 1.0},
            "multi_section": {"recall": 0.8, "mrr": 0.8},
            "thai_answerable": {"recall": 0.0, "mrr": 0.0},
        }
        # Add empty fixtures for categories used by hard gates while keeping
        # the focused assertion on the Thai case.
        prepared_cases = [prepared]
        for category, title in (
            ("english_answerable", "Section 1"),
            ("mixed_answerable", "Section 2"),
            ("multi_section", "Section 3"),
        ):
            category_case = {
                "id": category,
                "category": category,
                "language": "en",
                "query": category,
                "expected_titles": [title],
            }
            index = int(title.split()[-1])
            prepared_cases.append(
                PreparedCase(
                    case=category_case,  # type: ignore[arg-type]
                    keyword_hits=(),
                    dense_hits=(_hit(index, 0.6, "dense"),),
                    reranker_scores={index: 0.9},
                    keyword_latency_ms=0.1,
                    dense_latency_ms=1.0,
                )
            )

        result = evaluate_profile(
            TuneProfile(4, 4, 0.3, 0.1, 500),
            prepared_cases,
            {
                "recall_at_k": 0.75,
                "mrr": 0.75,
                "not_found_discipline": 0.0,
            },
            baseline_categories,
        )

        self.assertTrue(result.passed_hard_gates)
        self.assertEqual(result.category_metrics["thai_answerable"]["recall"], 1.0)
        self.assertEqual(result.context_header_validity, 1.0)
        self.assertEqual(result.context_budget_validity, 1.0)
        self.assertLessEqual(result.context_p95_chars, 500)


if __name__ == "__main__":
    unittest.main()

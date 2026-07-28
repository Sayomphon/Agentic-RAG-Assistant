"""Tests for the Track A / Step 1 baseline contract and runner helpers."""

from __future__ import annotations

import unittest

from src.evaluation.baseline_dataset import (
    REQUIRED_CATEGORY_COUNTS,
    BaselineCase,
    load_baseline_cases,
    validate_baseline_cases,
)
from src.evaluation.run_baseline import (
    _case_payload,
    corpus_snapshot,
    environment_snapshot,
    expected_manifest,
    retrieval_config_snapshot,
    verify_manifest,
)
from src.evaluation.run_eval import CaseResult
from src.retrievers.base import Chunk, ScoredChunk, load_chunks
from src.retrievers.hybrid import HybridRetriever


class _StubRetriever:
    def __init__(self, hits: list[ScoredChunk], failures: int = 0) -> None:
        self._hits = hits
        self.query_failure_count = failures

    def search(self, _query: str, top_k: int) -> list[ScoredChunk]:
        return self._hits[:top_k]


class BaselineDatasetTests(unittest.TestCase):
    """Pin the labelled dataset before quality work changes retrieval."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_baseline_cases()
        cls.titles = {chunk.title for chunk in load_chunks()}

    def test_dataset_meets_required_category_counts(self) -> None:
        distribution = validate_baseline_cases(
            self.cases,
            valid_titles=self.titles,
        )
        self.assertEqual(distribution, REQUIRED_CATEGORY_COUNTS)
        self.assertEqual(len(self.cases), 40)

    def test_case_ids_are_unique(self) -> None:
        case_ids = [case["id"] for case in self.cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_negative_and_answerable_labels_are_separated(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                if case["category"] == "negative":
                    self.assertEqual(case["expected_titles"], [])
                else:
                    self.assertTrue(case["expected_titles"])

    def test_multi_section_cases_require_multiple_sources(self) -> None:
        multi_section = [
            case for case in self.cases
            if case["category"] == "multi_section"
        ]
        self.assertTrue(
            all(len(case["expected_titles"]) >= 2 for case in multi_section)
        )

    def test_validator_rejects_a_label_missing_from_the_corpus(self) -> None:
        invalid: BaselineCase = {
            "id": "invalid_title",
            "category": "english_answerable",
            "language": "en",
            "query": "A valid-looking query",
            "expected_titles": ["Section That Does Not Exist"],
        }
        with self.assertRaisesRegex(ValueError, "unknown titles"):
            validate_baseline_cases(
                [*self.cases, invalid],
                valid_titles=self.titles,
            )

    def test_versioned_manifest_matches_dataset_corpus_and_config(self) -> None:
        recorded = verify_manifest(
            self.cases,
            require_current_config=False,
        )
        current = expected_manifest(self.cases)
        self.assertEqual(recorded["dataset_sha256"], current["dataset_sha256"])
        self.assertEqual(recorded["corpus"], current["corpus"])
        self.assertEqual(recorded["retrieval_config"]["top_k"], 4)
        self.assertEqual(recorded["retrieval_config"]["min_cosine"], 0.38)


class BaselineSnapshotTests(unittest.TestCase):
    """Ensure reproducibility metadata stays useful and secret-free."""

    def test_corpus_snapshot_is_complete_and_deterministic(self) -> None:
        first = corpus_snapshot()
        second = corpus_snapshot()
        self.assertEqual(first, second)
        self.assertEqual(first["section_count"], 54)
        self.assertEqual(first["source_files"], ["knowledge_base.txt"])
        self.assertRegex(str(first["sha256"]), r"^[0-9a-f]{64}$")

    def test_environment_snapshot_matches_pinned_direct_dependencies(self) -> None:
        snapshot = environment_snapshot()
        dependencies = snapshot["dependencies"]
        self.assertIsInstance(dependencies, list)
        self.assertTrue(dependencies)
        for dependency in dependencies:
            with self.subTest(package=dependency["package"]):
                self.assertEqual(
                    dependency["installed"],
                    dependency["declared"],
                )

    def test_snapshots_expose_only_non_secret_configuration(self) -> None:
        environment_keys = set(environment_snapshot())
        config_keys = set(retrieval_config_snapshot())
        forbidden = {
            "api_key",
            "openai_api_key",
            "token",
            "secret",
            "password",
        }
        self.assertTrue(environment_keys.isdisjoint(forbidden))
        self.assertTrue(config_keys.isdisjoint(forbidden))

    def test_negative_case_payload_has_no_answerable_only_metrics(self) -> None:
        result = CaseResult(
            case_id="negative",
            category="negative",
            expected=(),
            retrieved=(),
            latency_ms=0.1,
        )
        payload = _case_payload(result)
        self.assertIsNone(payload["recall"])
        self.assertIsNone(payload["reciprocal_rank"])

    def test_hybrid_exposes_dense_provider_failures(self) -> None:
        hit = ScoredChunk(
            chunk=Chunk(title="Remote Work Policy", text="Evidence", index=1),
            score=1.0,
            source="bm25",
        )
        hybrid = HybridRetriever(
            _StubRetriever([hit]),
            _StubRetriever([], failures=2),
        )
        self.assertEqual(hybrid.query_failure_count, 2)


if __name__ == "__main__":
    unittest.main()

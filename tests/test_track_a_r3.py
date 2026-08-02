"""Tests for the shared Track A R3 evidence and ablation contracts."""

from __future__ import annotations

import unittest

from src.evaluation.run_track_a_ablation import ablation_profiles
from src.evaluation.track_a_r3 import (
    R3ValidationError,
    evidence_identity,
    normalized_rss_mb,
    selected_profile,
    validate_published_artifact,
)


class R3EvidenceContractTests(unittest.TestCase):
    def test_ablation_matrix_is_complete_and_profile_ids_are_unique(self) -> None:
        profiles = ablation_profiles()

        self.assertEqual(
            [profile.ablation_id for profile in profiles],
            [f"A{index}" for index in range(8)],
        )
        self.assertEqual(len({profile.profile_id for profile in profiles}), 8)
        for profile in profiles:
            self.assertIn(f"c{profile.candidate_k}", profile.profile_id)
            self.assertIn(f"k{profile.top_k}", profile.profile_id)
            self.assertIn(f"rr{profile.reranker_role}", profile.profile_id)
            self.assertIn(f"failure{profile.failure_mode}", profile.profile_id)

    def test_selected_profile_matches_controlled_identity(self) -> None:
        profile = selected_profile()
        identity = evidence_identity()

        self.assertEqual(profile["profile_id"], "track_a_balanced_v1")
        self.assertEqual(profile["top_k"], identity["top_k"])
        self.assertEqual(identity["dataset"]["case_count"], 40)  # type: ignore[index]
        self.assertEqual(len(identity["dataset"]["sha256"]), 64)  # type: ignore[index]
        self.assertEqual(len(identity["corpus"]["sha256"]), 64)  # type: ignore[index]

    def test_published_artifact_rejects_raw_content_and_credentials(self) -> None:
        for payload in (
            {"query": "private"},
            {"nested": {"document_body": "private"}},
            {"answer": "private"},
            {"safe": "sk-secretmaterial123"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(R3ValidationError):
                    validate_published_artifact(payload)

    def test_published_artifact_allows_sanitized_case_metadata(self) -> None:
        validate_published_artifact(
            {
                "case_id": "th_leave_01",
                "expected_titles": ["Leave Policy"],
                "raw_queries_stored": False,
                "document_bodies_stored": False,
                "answer_citation_validity": 1.0,
            }
        )

    def test_ram_units_are_normalized_across_macos_and_linux(self) -> None:
        self.assertEqual(normalized_rss_mb(1024 * 1024, "Darwin"), 1.0)
        self.assertEqual(normalized_rss_mb(1024, "Linux"), 1.0)


if __name__ == "__main__":
    unittest.main()

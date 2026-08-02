"""Tests for strict, security-relevant configuration parsing."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import (
    _RETRIEVAL_PROFILES,
    _env_choice,
    _env_optional_float,
    _env_revision,
)


class OptionalFloatConfigTests(unittest.TestCase):
    def test_missing_or_blank_value_uses_the_reviewed_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_env_optional_float("TEST_GATE", 0.01), 0.01)
        with patch.dict(os.environ, {"TEST_GATE": "  "}, clear=True):
            self.assertEqual(_env_optional_float("TEST_GATE", 0.01), 0.01)

    def test_explicit_disable_sentinel_returns_none(self) -> None:
        for value in ("none", "off", "disabled"):
            with self.subTest(value=value):
                with patch.dict(
                    os.environ,
                    {"TEST_GATE": value},
                    clear=True,
                ):
                    self.assertIsNone(
                        _env_optional_float("TEST_GATE", 0.01)
                    )

    def test_non_finite_value_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"TEST_GATE": "nan"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "finite"):
                _env_optional_float("TEST_GATE", 0.01)


class RetrievalProfileConfigTests(unittest.TestCase):
    def test_keyword_safe_is_the_runtime_fallback(self) -> None:
        profile = _RETRIEVAL_PROFILES["keyword_safe"]

        self.assertEqual(profile.search_mode, "keyword")
        self.assertEqual(profile.reranker_failure_policy, "fail_closed")

    def test_official_track_a_profile_is_authoritative(self) -> None:
        profile = _RETRIEVAL_PROFILES["track_a_balanced_v1"]

        self.assertEqual(profile.search_mode, "hybrid")
        self.assertEqual(profile.candidate_k, 12)
        self.assertEqual(profile.top_k, 6)
        self.assertEqual(profile.hybrid_min_cosine, 0.20)
        self.assertEqual(profile.reranker_min_score, 0.01)
        self.assertEqual(profile.reranker_batch_size, 4)
        self.assertEqual(profile.reranker_max_length, 512)
        self.assertEqual(profile.reranker_timeout_seconds, 10.0)
        self.assertEqual(profile.max_context_chars, 6_000)
        self.assertEqual(profile.reranker_failure_policy, "fail_closed")
        self.assertEqual(profile.secondary_policy, "all_supported")

    def test_m1_candidate_profile_is_versioned_and_bounded(self) -> None:
        profile = _RETRIEVAL_PROFILES["track_a_balanced_v2"]

        self.assertEqual(profile.candidate_k, 10)
        self.assertEqual(profile.top_k, 6)
        self.assertEqual(profile.reranker_batch_size, 4)
        self.assertEqual(profile.reranker_max_length, 128)
        self.assertEqual(profile.reranker_min_score, 0.01)
        self.assertEqual(
            profile.secondary_policy,
            "emergency_low_risk_only",
        )

    def test_m1_candidate_document_matches_runtime_profile(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (
                project_root
                / "src"
                / "evaluation"
                / "configs"
                / "track_a_balanced_v2.json"
            ).read_text(encoding="utf-8")
        )
        profile = _RETRIEVAL_PROFILES["track_a_balanced_v2"]

        self.assertEqual(payload["schema_version"], "track-a-runtime-profile-v2")
        self.assertEqual(payload["profile_id"], "track_a_balanced_v2")
        self.assertEqual(payload["candidate_k"], profile.candidate_k)
        self.assertEqual(payload["top_k"], profile.top_k)
        self.assertEqual(
            payload["reranker_max_length"],
            profile.reranker_max_length,
        )
        self.assertEqual(
            payload["secondary_policy"],
            profile.secondary_policy,
        )
        self.assertRegex(
            payload["reranker_model_revision"],
            r"^[0-9a-f]{40}$",
        )
        self.assertRegex(
            payload["secondary_model_revision"],
            r"^[0-9a-f]{40}$",
        )
        self.assertTrue(
            payload["selection_evidence"]["requires_r3_v3_before_approval"]
        )

    def test_explicit_enumerated_override_is_validated(self) -> None:
        allowed = frozenset({"fail_closed", "fusion_order"})
        with patch.dict(
            os.environ,
            {"TEST_POLICY": "FUSION_ORDER"},
            clear=True,
        ):
            self.assertEqual(
                _env_choice("TEST_POLICY", "fail_closed", allowed),
                "fusion_order",
            )
        with patch.dict(
            os.environ,
            {"TEST_POLICY": "unsafe"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "TEST_POLICY"):
                _env_choice("TEST_POLICY", "fail_closed", allowed)

    def test_model_revision_requires_a_full_immutable_commit(self) -> None:
        revision = "a" * 40
        with patch.dict(
            os.environ,
            {"TEST_REVISION": revision},
            clear=True,
        ):
            self.assertEqual(
                _env_revision("TEST_REVISION", "b" * 40),
                revision,
            )
        with patch.dict(
            os.environ,
            {"TEST_REVISION": "main"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "40-character"):
                _env_revision("TEST_REVISION", "b" * 40)

    def test_env_example_and_readme_name_the_same_official_profile(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        env_example = (project_root / ".env.example").read_text(
            encoding="utf-8"
        )
        readme = (project_root / "README.md").read_text(encoding="utf-8")

        self.assertIn("RETRIEVAL_PROFILE=track_a_balanced_v1", env_example)
        self.assertIn("RERANKER_FAILURE_POLICY=fail_closed", env_example)
        self.assertIn(
            "RERANKER_FALLBACK_MODEL_REVISION="
            "2cfc18c9415c912f9d8155881c133215df768a70",
            env_example,
        )
        self.assertIn("`track_a_balanced_v1` profile", readme)
        self.assertIn("explicit env var > named profile", readme)


if __name__ == "__main__":
    unittest.main()

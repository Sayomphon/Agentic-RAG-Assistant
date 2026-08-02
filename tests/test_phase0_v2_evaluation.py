"""Tests for the versioned Enterprise Phase 0 v2 checkpoint."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import (
    RETRIEVAL_PROFILE,
    RERANKER_FAILURE_POLICY,
    RERANKER_FALLBACK_MODEL,
    RERANKER_FALLBACK_MODEL_REVISION,
    SEARCH_MODE,
)
from src.evaluation.baseline_dataset import load_baseline_cases
from src.evaluation.phase0 import (
    PHASE0_V1_SPEC,
    PHASE0_V2_SPEC,
    expected_phase0_manifest,
    load_frozen_phase0_manifest,
    phase0_v2_config_snapshot,
    verify_phase0_manifest,
    write_phase0_manifest,
)
from src.evaluation.run_phase0_v2 import main


class Phase0V2ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_baseline_cases()

    def test_v2_uses_independent_versioned_paths_and_schemas(self) -> None:
        self.assertNotEqual(
            PHASE0_V2_SPEC.manifest_path,
            PHASE0_V1_SPEC.manifest_path,
        )
        self.assertNotEqual(
            PHASE0_V2_SPEC.results_json_path,
            PHASE0_V1_SPEC.results_json_path,
        )
        self.assertEqual(PHASE0_V2_SPEC.baseline_id, "enterprise-phase0-v2")
        self.assertEqual(
            PHASE0_V2_SPEC.report_schema_version,
            "enterprise-phase0-baseline-report-v2",
        )

    def test_v2_snapshot_freezes_profile_and_safety_configuration(self) -> None:
        snapshot = phase0_v2_config_snapshot()
        serving = snapshot["serving"]
        reranker = snapshot["reranker"]

        self.assertEqual(serving["retrieval_profile"], RETRIEVAL_PROFILE)
        self.assertEqual(serving["search_mode"], SEARCH_MODE)
        self.assertEqual(
            reranker["failure_policy"],
            RERANKER_FAILURE_POLICY,
        )
        self.assertEqual(
            reranker["fallback_model"],
            RERANKER_FALLBACK_MODEL,
        )
        self.assertEqual(
            reranker["fallback_model_revision"],
            RERANKER_FALLBACK_MODEL_REVISION,
        )
        self.assertRegex(
            str(reranker["fallback_model_revision"]),
            r"^[0-9a-f]{40}$",
        )

    def test_v2_manifest_round_trip_and_tamper_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enterprise_phase0_v2.manifest.json"
            created = write_phase0_manifest(
                self.cases,
                path=path,
                spec=PHASE0_V2_SPEC,
            )
            loaded = load_frozen_phase0_manifest(
                path,
                spec=PHASE0_V2_SPEC,
            )

            self.assertEqual(created, loaded)
            self.assertEqual(created["baseline_id"], "enterprise-phase0-v2")
            self.assertEqual(
                created["runtime_config"],
                phase0_v2_config_snapshot(),
            )
            with self.assertRaises(FileExistsError):
                write_phase0_manifest(
                    self.cases,
                    path=path,
                    spec=PHASE0_V2_SPEC,
                )

    def test_expected_v2_manifest_contains_no_secret_fields(self) -> None:
        manifest = expected_phase0_manifest(
            self.cases,
            spec=PHASE0_V2_SPEC,
        )
        encoded_keys = {
            str(key).lower()
            for section in manifest.values()
            if isinstance(section, dict)
            for key in section
        }

        self.assertTrue(
            encoded_keys.isdisjoint(
                {"api_key", "password", "secret", "access_token"}
            )
        )

    def test_v2_verification_fails_when_manifest_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.manifest.json"

            with self.assertRaises(FileNotFoundError):
                verify_phase0_manifest(
                    self.cases,
                    path=path,
                    spec=PHASE0_V2_SPEC,
                )


class Phase0V2CommandTests(unittest.TestCase):
    @patch("src.evaluation.run_phase0_v2.run_phase0", return_value=0)
    def test_v2_entrypoint_delegates_to_shared_runner(
        self,
        run_phase0_mock,
    ) -> None:
        result = main(["--verify-manifest-only"])

        self.assertEqual(result, 0)
        run_phase0_mock.assert_called_once_with(
            ["--verify-manifest-only"],
            spec=PHASE0_V2_SPEC,
        )


if __name__ == "__main__":
    unittest.main()

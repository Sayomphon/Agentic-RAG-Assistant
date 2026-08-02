"""Tests for Track A R0 freeze, provenance, and immutability controls."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from src.evaluation.run_track_a_closure import _parse_args
from src.evaluation.track_a_closure import (
    TRACK_A_CLOSURE_ID,
    TRACK_A_CLOSURE_MANIFEST_PATH,
    build_track_a_r4_assessment,
    load_track_a_closure_manifest,
    render_track_a_closure_report,
    validate_track_a_closure_manifest,
    verify_track_a_r0_freeze,
    verify_track_a_r0_repository_state,
)


class TrackAClosureManifestTests(unittest.TestCase):
    def test_frozen_manifest_matches_reviewed_git_baseline(self) -> None:
        manifest = verify_track_a_r0_freeze()

        self.assertEqual(manifest["closure_id"], TRACK_A_CLOSURE_ID)
        self.assertEqual(
            manifest["repository"]["base_commit"],
            "fd3ac95f3f2ecc0ae3df9746d329802f656d1432",
        )

    def test_manifest_loader_rejects_duplicate_json_keys(self) -> None:
        encoded = TRACK_A_CLOSURE_MANIFEST_PATH.read_text(encoding="utf-8")
        duplicate = (
            f'"closure_id": "{TRACK_A_CLOSURE_ID}", '
            f'"closure_id": "{TRACK_A_CLOSURE_ID}"'
        )
        encoded = encoded.replace(
            f'"closure_id": "{TRACK_A_CLOSURE_ID}"',
            duplicate,
            1,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.manifest.json"
            path.write_text(encoded, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "repeats JSON key"):
                load_track_a_closure_manifest(path)

    def test_structural_validation_rejects_path_traversal(self) -> None:
        manifest = load_track_a_closure_manifest()
        manifest["immutable_artifacts"][0]["path"] = "../baseline_results.json"

        with self.assertRaisesRegex(ValueError, "stay within the project"):
            validate_track_a_closure_manifest(manifest)

    def test_verification_fails_closed_on_tampered_digest(self) -> None:
        manifest = load_track_a_closure_manifest()
        manifest["immutable_artifacts"][0]["sha256"] = "0" * 64

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tampered.manifest.json"
            path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_track_a_r0_freeze(path)

    def test_historical_and_planned_artifact_names_are_frozen(self) -> None:
        manifest = load_track_a_closure_manifest()
        historical = {
            identity["path"] for identity in manifest["immutable_artifacts"]
        }

        self.assertEqual(
            historical,
            {
                "baseline_results.json",
                "baseline_results.md",
                "phase0_baseline_results.json",
                "phase0_baseline_results.md",
                "src/evaluation/datasets/lean_quality_v1.json",
                "src/evaluation/datasets/lean_quality_v1.manifest.json",
                "track_a_step3_results.json",
                "track_a_step3_results.md",
            },
        )
        self.assertIn(
            "track_a_closure_report_v2.md",
            manifest["planned_artifacts"],
        )
        self.assertIn(
            "docs/TRACK_A_DECISION_RECORD.md",
            manifest["planned_artifacts"],
        )

    def test_secondary_reranker_gap_is_explicit_and_blocking(self) -> None:
        manifest = load_track_a_closure_manifest()
        secondary = manifest["frozen_inputs"]["models"]["secondary_reranker"]

        self.assertEqual(secondary["status"], "not-configured-at-r0")
        self.assertTrue(secondary["required_before_official_evaluation"])


class TrackAClosureCommandTests(unittest.TestCase):
    def test_cli_requires_explicit_verification_action(self) -> None:
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                _parse_args([])

    @patch("src.evaluation.track_a_closure.subprocess.run")
    def test_repository_state_requires_approved_branch(
        self,
        mock_run: Mock,
    ) -> None:
        manifest = load_track_a_closure_manifest()
        mock_run.return_value.stdout = "main\n"

        with self.assertRaisesRegex(ValueError, "fix/track-a-closure"):
            verify_track_a_r0_repository_state(manifest)

    @patch("src.evaluation.track_a_closure.subprocess.run")
    def test_repository_state_rejects_dirty_worktree(
        self,
        mock_run: Mock,
    ) -> None:
        manifest = load_track_a_closure_manifest()
        mock_run.side_effect = [
            Mock(stdout="fix/track-a-closure\n"),
            Mock(returncode=0),
            Mock(stdout=" M src/config.py\n"),
        ]

        with self.assertRaisesRegex(ValueError, "clean worktree"):
            verify_track_a_r0_repository_state(manifest)


class TrackAR4AssessmentTests(unittest.TestCase):
    def test_current_evidence_fails_closed_without_approval(self) -> None:
        assessment = build_track_a_r4_assessment(
            generated_at="2026-08-02T00:00:00+07:00"
        )
        gates = {
            gate["name"]: gate["passed"]
            for gate in assessment["gates"]
        }

        self.assertEqual(assessment["status"], "NOT_APPROVED")
        self.assertFalse(assessment["parent_plan_update_eligible"])
        self.assertFalse(gates["R3 final-answer quality"])
        self.assertFalse(gates["R3 performance"])
        self.assertFalse(gates["Human/Domain review"])
        self.assertFalse(gates["Product/Business approval"])
        self.assertEqual(
            assessment["next_track"],
            "Additional Track A remediation",
        )

    def test_report_is_aggregate_only_and_records_blockers(self) -> None:
        assessment = build_track_a_r4_assessment(
            generated_at="2026-08-02T00:00:00+07:00"
        )

        report = render_track_a_closure_report(assessment)

        self.assertIn("Track A Status: `NOT_APPROVED`", report)
        self.assertIn("Answer citation coverage", report)
        self.assertIn("Parent Plan completion status was not updated", report)
        self.assertNotIn("mixed_expense_approval", report)
        self.assertNotIn("en_remote_work_days", report)

    def test_identity_mismatch_fails_before_decision(self) -> None:
        source = Path("track_a_answer_results_v2.json")
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["identity"]["corpus"]["sha256"] = "0" * 64

        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory) / "answer.json"
            tampered.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with patch.dict(
                "src.evaluation.track_a_closure._R4_JSON_EVIDENCE",
                {"R3 answer evaluation": tampered},
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "identities differ",
                ):
                    build_track_a_r4_assessment()

    def test_cli_accepts_r4_report_action_without_external_flags(self) -> None:
        args = _parse_args(["--write-r4-report"])

        self.assertTrue(args.write_r4_report)
        self.assertFalse(args.allow_query_embeddings)


if __name__ == "__main__":
    unittest.main()

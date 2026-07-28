"""Tests for the Enterprise Phase 0 manifest, gates, and data boundary."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from src.evaluation.baseline_dataset import load_baseline_cases
from src.evaluation.baseline_support import _run_check
from src.evaluation.phase0 import (
    PHASE0_BASELINE_ID,
    PHASE0_MANIFEST_PATH,
    PHASE0_RESULTS_JSON_PATH,
    expected_phase0_manifest,
    load_frozen_phase0_manifest,
    phase0_config_snapshot,
    source_tree_snapshot,
    validate_frozen_phase0_manifest,
    verify_phase0_manifest,
    write_phase0_manifest,
)
from src.evaluation.run_phase0 import (
    _evaluate_runtime_mode,
    _ensure_corpus_embedding_boundary,
    _parse_args,
)
from src.retrievers.base import Chunk, ScoredChunk


def _all_mapping_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            *(str(key).lower() for key in value),
            *(
                nested
                for child in value.values()
                for nested in _all_mapping_keys(child)
            ),
        }
    if isinstance(value, list):
        return {
            nested
            for child in value
            for nested in _all_mapping_keys(child)
        }
    return set()


class Phase0ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_baseline_cases()

    def test_frozen_manifest_and_report_are_internally_consistent(self) -> None:
        self.assertTrue(PHASE0_MANIFEST_PATH.is_file())
        manifest = load_frozen_phase0_manifest()
        report = json.loads(
            PHASE0_RESULTS_JSON_PATH.read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["baseline_id"], PHASE0_BASELINE_ID)
        self.assertEqual(manifest["retriever_contract_version"], "1.0.0")
        self.assertEqual(manifest["dataset"]["case_count"], 40)
        self.assertEqual(manifest["corpus"]["section_count"], 54)
        self.assertEqual(report["manifest"], manifest)

    @patch(
        "src.evaluation.phase0._phase0_source_files",
        side_effect=AssertionError("current source must not be inspected"),
    )
    def test_historical_integrity_does_not_compare_current_source(
        self,
        _mock_source_files: Mock,
    ) -> None:
        manifest = load_frozen_phase0_manifest()

        self.assertEqual(manifest["baseline_id"], PHASE0_BASELINE_ID)

    def test_structural_validation_rejects_invalid_digest(self) -> None:
        manifest = load_frozen_phase0_manifest()
        manifest["source_tree"]["sha256"] = "not-a-digest"

        with self.assertRaisesRegex(ValueError, "SHA-256"):
            validate_frozen_phase0_manifest(manifest)

    def test_structural_validation_rejects_path_traversal(self) -> None:
        manifest = load_frozen_phase0_manifest()
        manifest["dataset"]["file"] = "../outside.json"

        with self.assertRaisesRegex(ValueError, "stay within the project"):
            validate_frozen_phase0_manifest(manifest)

    def test_manifest_loader_rejects_duplicate_json_keys(self) -> None:
        manifest = load_frozen_phase0_manifest()
        encoded = json.dumps(manifest)
        duplicate = (
            f'"baseline_id": "{PHASE0_BASELINE_ID}", '
            f'"baseline_id": "{PHASE0_BASELINE_ID}"'
        )
        encoded = encoded.replace(
            f'"baseline_id": "{PHASE0_BASELINE_ID}"',
            duplicate,
            1,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.manifest.json"
            path.write_text(encoded, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "repeats JSON key"):
                load_frozen_phase0_manifest(path)

    def test_source_tree_snapshot_is_deterministic_and_complete(self) -> None:
        first = source_tree_snapshot()
        second = source_tree_snapshot()

        self.assertEqual(first, second)
        self.assertRegex(str(first["sha256"]), r"^[0-9a-f]{64}$")
        self.assertIn("src/retrievers/base.py", first["files"])
        self.assertIn("tests/test_retriever_contract.py", first["files"])
        self.assertIn("docs/RETRIEVER_CONTRACT.md", first["files"])

    def test_phase0_snapshot_contains_no_secret_fields(self) -> None:
        keys = _all_mapping_keys(
            {
                "config": phase0_config_snapshot(),
                "manifest": expected_phase0_manifest(self.cases),
            }
        )
        forbidden = {
            "api_key",
            "openai_api_key",
            "password",
            "secret",
            "access_token",
            "refresh_token",
        }
        self.assertTrue(keys.isdisjoint(forbidden))

    def test_manifest_creation_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phase0.manifest.json"
            created = write_phase0_manifest(self.cases, path=path)

            self.assertEqual(created["baseline_id"], PHASE0_BASELINE_ID)
            with self.assertRaises(FileExistsError):
                write_phase0_manifest(self.cases, path=path)

    def test_manifest_verification_fails_closed_on_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phase0.manifest.json"
            write_phase0_manifest(self.cases, path=path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["corpus"]["sha256"] = "0" * 64
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_phase0_manifest(self.cases, path=path)


class Phase0BoundaryTests(unittest.TestCase):
    def test_strict_manifest_verification_is_an_explicit_lifecycle_action(
        self,
    ) -> None:
        args = _parse_args(["--verify-manifest-only"])
        self.assertTrue(args.verify_manifest_only)

        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                _parse_args(
                    [
                        "--verify-manifest-only",
                        "--modes",
                        "semantic",
                        "--allow-query-embeddings",
                    ]
                )

    def test_external_modes_require_explicit_query_approval(self) -> None:
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                _parse_args(["--modes", "semantic"])

        args = _parse_args(
            ["--modes", "semantic", "--allow-query-embeddings"]
        )
        self.assertTrue(args.allow_query_embeddings)

    @patch(
        "src.evaluation.run_phase0.has_usable_embedding_cache",
        return_value=False,
    )
    def test_missing_corpus_cache_fails_closed(
        self,
        _mock_cache: Mock,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "Refusing"):
            _ensure_corpus_embedding_boundary(
                allow_corpus_embeddings=False,
            )

    @patch(
        "src.evaluation.run_phase0.has_usable_embedding_cache",
        return_value=False,
    )
    def test_corpus_cache_rebuild_requires_separate_approval(
        self,
        _mock_cache: Mock,
    ) -> None:
        self.assertFalse(
            _ensure_corpus_embedding_boundary(
                allow_corpus_embeddings=True,
            )
        )

    @patch("src.evaluation.baseline_support.subprocess.run")
    def test_local_gate_overrides_operator_search_mode(
        self,
        mock_run: Mock,
    ) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Ran 1 test\n",
            stderr="",
        )

        _run_check(
            "test",
            ["python", "-m", "unittest"],
            count_pattern=re.compile(r"Ran (?P<count>\d+)"),
            environment_overrides={"SEARCH_MODE": "keyword"},
        )

        self.assertEqual(
            mock_run.call_args.kwargs["env"]["SEARCH_MODE"],
            "keyword",
        )

    def test_runtime_evaluation_fails_on_first_degraded_query(self) -> None:
        class _FailingRetriever:
            SOURCE = "dense"

            def __init__(self) -> None:
                self.query_failure_count = 0
                self.calls = 0

            def search(self, _query: str, top_k: int) -> list[ScoredChunk]:
                self.calls += 1
                self.query_failure_count += 1
                return [
                    ScoredChunk(
                        Chunk("Fallback", "Evidence", 1),
                        1.0,
                        "bm25",
                    )
                ]

        retriever = _FailingRetriever()
        cases = load_baseline_cases()[:2]

        with self.assertRaisesRegex(RuntimeError, "degraded"):
            _evaluate_runtime_mode("semantic", retriever, cases)

        self.assertEqual(retriever.calls, 1)


if __name__ == "__main__":
    unittest.main()

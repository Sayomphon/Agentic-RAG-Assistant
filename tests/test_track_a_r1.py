"""Tests for R1 comparative evidence, isolation, and data boundaries."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from copy import deepcopy
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from src.evaluation.run_track_a_closure import _parse_args
from src.evaluation.track_a_closure import load_track_a_closure_manifest
from src.evaluation.track_a_r1 import (
    PHASE0_RESULTS_PATH,
    R1_BASELINE_ID,
    R1_SCHEMA_VERSION,
    TRACK_A_CLOSURE_MANIFEST_PATH,
    R1ExecutionError,
    R1ValidationError,
    _category_metrics_from_cases,
    _comparison,
    _load_post_track_a_profile,
    _metrics_from_cases,
    _pre_profile,
    _run_legacy_worker,
    _sha256_file,
    _worker_environment,
    load_r1_artifact,
    validate_legacy_worker_payload,
    validate_r1_artifact,
    write_r1_artifacts,
)


def _case_for_top_k(
    raw_case: dict[str, object],
    top_k: int,
) -> dict[str, object]:
    case = deepcopy(raw_case)
    expected = list(case["expected_titles"])
    retrieved = list(case["retrieved_titles"])[:top_k]
    case["retrieved_titles"] = retrieved
    case["hit"] = any(title in retrieved for title in expected)
    case["false_positive"] = not expected and bool(retrieved)
    if expected:
        case["recall"] = (
            sum(title in retrieved for title in expected) / len(expected)
        )
        case["reciprocal_rank"] = 0.0
        for rank, title in enumerate(retrieved, start=1):
            if title in expected:
                case["reciprocal_rank"] = 1.0 / rank
                break
    else:
        case["recall"] = None
        case["reciprocal_rank"] = None
    return case


def _worker_payload(
    top_k: int,
    *,
    include_checks: bool,
) -> dict[str, object]:
    historical = json.loads(
        (PHASE0_RESULTS_PATH.parent / "baseline_results.json").read_text(
            encoding="utf-8"
        )
    )
    closure = load_track_a_closure_manifest()
    post = _load_post_track_a_profile(closure)
    post_retrieval = post["retrieval"]

    retrieval: dict[str, object] = {}
    implementations = {
        "keyword": ("BM25Retriever", "bm25"),
        "semantic": ("OpenAIEmbeddingRetriever", "dense"),
        "hybrid": ("HybridRetriever", "hybrid"),
    }
    for mode in ("keyword", "semantic", "hybrid"):
        cases = [
            _case_for_top_k(case, top_k)
            for case in post_retrieval[mode]["cases"]
        ]
        implementation, source = implementations[mode]
        retrieval[mode] = {
            "health": {
                "implementation": implementation,
                "source": source,
                "query_failure_count": 0,
                "fallback_count": 0,
            },
            "metrics": _metrics_from_cases(cases),
            "category_metrics": _category_metrics_from_cases(cases),
            "cases": cases,
        }

    checks = (
        [
            {
                "name": "unit_tests",
                "command": "python -m unittest discover -s tests -v",
                "exit_code": 0,
                "duration_ms": 1.0,
                "case_count": 45,
                "passed": True,
            },
            {
                "name": "keyword_regression",
                "command": "python -m src.evaluation.regression",
                "exit_code": 0,
                "duration_ms": 1.0,
                "case_count": 15,
                "passed": True,
            },
        ]
        if include_checks
        else []
    )
    return {
        "schema_version": "track-a-legacy-step1-worker-v1",
        "top_k": top_k,
        "manifest": historical["manifest"],
        "environment": historical["environment"],
        "corpus_embedding_cache": {
            "ready": True,
            "file_name": "embeddings-d171c6d797f73525.npz",
            "corpus_api_call_allowed": False,
        },
        "checks": checks,
        "retrieval": retrieval,
    }


def _artifact() -> dict[str, object]:
    closure = load_track_a_closure_manifest()
    repository = closure["repository"]
    worker_default = validate_legacy_worker_payload(
        _worker_payload(4, include_checks=True),
        expected_top_k=4,
        require_checks=True,
    )
    worker_controlled = validate_legacy_worker_payload(
        _worker_payload(6, include_checks=False),
        expected_top_k=6,
        require_checks=False,
    )
    pre_default = _pre_profile(
        worker_default,
        source_commit=repository["pre_upgrade_commit"],
    )
    pre_controlled = _pre_profile(
        worker_controlled,
        source_commit=repository["pre_upgrade_commit"],
    )
    post = _load_post_track_a_profile(closure)
    return {
        "schema_version": R1_SCHEMA_VERSION,
        "baseline_id": R1_BASELINE_ID,
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "provenance": {
            "evaluation_commit": "1" * 40,
            "pre_upgrade_commit": repository["pre_upgrade_commit"],
            "post_track_a_commit": repository["base_commit"],
            "working_tree_clean": True,
            "legacy_worktree_clean": True,
            "dataset_sha256": closure["frozen_inputs"]["dataset"]["file"][
                "sha256"
            ],
            "corpus_sha256": closure["frozen_inputs"]["corpus"]["sha256"],
            "requirements": [
                {"path": "requirements-dev.txt", "sha256": "2" * 64},
                {"path": "requirements.txt", "sha256": "3" * 64},
            ],
            "worker": {
                "path": "src/evaluation/legacy_step1_worker.py",
                "sha256": "4" * 64,
            },
            "closure_manifest": {
                "path": (
                    "src/evaluation/datasets/"
                    "track_a_closure_v2.manifest.json"
                ),
                "sha256": _sha256_file(TRACK_A_CLOSURE_MANIFEST_PATH),
            },
            "commands": ["one safe command"],
            "provider_failure_count": 0,
            "fallback_count": 0,
        },
        "data_boundary": {
            "query_embeddings_approved": True,
            "corpus_embedding_cache_ready": True,
            "corpus_embeddings_approved": False,
            "answer_evaluation_approved": False,
            "raw_queries_stored": False,
            "document_bodies_stored": False,
            "prompts_stored": False,
            "credentials_stored": False,
        },
        "checks": [
            {
                "scope": "current",
                "name": "unit_tests",
                "passed": True,
            },
            {
                "scope": "current",
                "name": "keyword_regression",
                "passed": True,
            },
            {
                "scope": "current",
                "name": "retriever_contract",
                "passed": True,
            },
            {
                "scope": "legacy",
                "name": "unit_tests",
                "passed": True,
            },
            {
                "scope": "legacy",
                "name": "keyword_regression",
                "passed": True,
            },
        ],
        "profiles": {
            "pre_track_a_operational_default": pre_default,
            "pre_track_a_controlled_top_k_6": pre_controlled,
            "post_track_a_selected_top_k_6": post,
        },
        "comparisons": {
            "operational_default": _comparison(
                pre_id="pre_track_a_operational_default",
                pre_profile=pre_default,
                post_id="post_track_a_selected_top_k_6",
                post_profile=post,
            ),
            "controlled_top_k_6": _comparison(
                pre_id="pre_track_a_controlled_top_k_6",
                pre_profile=pre_controlled,
                post_id="post_track_a_selected_top_k_6",
                post_profile=post,
            ),
        },
    }


class LegacyWorkerPayloadTests(unittest.TestCase):
    def test_accepts_complete_three_mode_payload(self) -> None:
        payload = validate_legacy_worker_payload(
            _worker_payload(4, include_checks=True),
            expected_top_k=4,
            require_checks=True,
        )

        self.assertEqual(tuple(payload["retrieval"]), (
            "keyword",
            "semantic",
            "hybrid",
        ))

    def test_rejects_wrong_dataset_hash(self) -> None:
        payload = _worker_payload(4, include_checks=True)
        payload["manifest"]["dataset_sha256"] = "0" * 64

        with self.assertRaisesRegex(R1ValidationError, "dataset SHA-256"):
            validate_legacy_worker_payload(
                payload,
                expected_top_k=4,
                require_checks=True,
            )

    def test_rejects_wrong_schema(self) -> None:
        payload = _worker_payload(4, include_checks=True)
        payload["schema_version"] = "unsupported"

        with self.assertRaisesRegex(R1ValidationError, "schema_version"):
            validate_legacy_worker_payload(
                payload,
                expected_top_k=4,
                require_checks=True,
            )

    def test_rejects_wrong_corpus_hash(self) -> None:
        payload = _worker_payload(4, include_checks=True)
        payload["manifest"]["corpus"]["sha256"] = "0" * 64

        with self.assertRaisesRegex(R1ValidationError, "corpus SHA-256"):
            validate_legacy_worker_payload(
                payload,
                expected_top_k=4,
                require_checks=True,
            )

    def test_rejects_missing_hybrid_evidence(self) -> None:
        payload = _worker_payload(4, include_checks=True)
        del payload["retrieval"]["hybrid"]

        with self.assertRaisesRegex(R1ValidationError, "three modes|must contain"):
            validate_legacy_worker_payload(
                payload,
                expected_top_k=4,
                require_checks=True,
            )

    def test_rejects_provider_fallback(self) -> None:
        payload = _worker_payload(4, include_checks=True)
        payload["retrieval"]["hybrid"]["health"]["fallback_count"] = 1

        with self.assertRaisesRegex(R1ValidationError, "fallback_count"):
            validate_legacy_worker_payload(
                payload,
                expected_top_k=4,
                require_checks=True,
            )

    def test_rejects_metric_not_derived_from_cases(self) -> None:
        payload = _worker_payload(4, include_checks=True)
        payload["retrieval"]["hybrid"]["metrics"]["mrr"] = 0.123

        with self.assertRaisesRegex(R1ValidationError, "metrics.mrr"):
            validate_legacy_worker_payload(
                payload,
                expected_top_k=4,
                require_checks=True,
            )

    @patch("src.evaluation.track_a_r1.subprocess.run")
    def test_worker_failure_does_not_echo_provider_details(
        self,
        mock_run: Mock,
    ) -> None:
        mock_run.return_value = Mock(
            returncode=1,
            stdout=b"",
            stderr=b"sensitive-provider-detail raw-query document-body",
        )
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key-value-that-is-never-printed"},
            clear=False,
        ):
            with self.assertRaises(R1ExecutionError) as raised:
                _run_legacy_worker(
                    legacy_root=Path("/private/tmp/legacy"),
                    legacy_python=Path("/private/tmp/legacy/venv/bin/python"),
                    top_k=4,
                    run_checks=True,
                )

        message = str(raised.exception)
        self.assertNotIn("sensitive-provider-detail", message)
        self.assertNotIn("raw-query", message)


class R1ArtifactTests(unittest.TestCase):
    def test_complete_artifact_passes(self) -> None:
        artifact = validate_r1_artifact(_artifact())

        self.assertFalse(
            artifact["comparisons"]["operational_default"]["same_top_k"]
        )
        self.assertTrue(
            artifact["comparisons"]["controlled_top_k_6"]["same_top_k"]
        )

    def test_controlled_comparison_rejects_different_top_k(self) -> None:
        artifact = _artifact()
        comparison = artifact["comparisons"]["controlled_top_k_6"]
        comparison["same_top_k"] = False
        comparison["pre_top_k"] = 4

        with self.assertRaisesRegex(R1ValidationError, "same TOP_K"):
            validate_r1_artifact(artifact)

    def test_artifact_rejects_raw_query_field(self) -> None:
        artifact = _artifact()
        artifact["provenance"]["query"] = "sensitive"

        with self.assertRaises(R1ValidationError):
            validate_r1_artifact(artifact)

    def test_writer_refuses_to_overwrite_versioned_evidence(self) -> None:
        artifact = validate_r1_artifact(_artifact())
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "result.json"
            markdown_path = Path(directory) / "result.md"
            write_r1_artifacts(
                artifact,
                json_path=json_path,
                markdown_path=markdown_path,
            )
            loaded = load_r1_artifact(json_path)
            self.assertEqual(loaded["baseline_id"], R1_BASELINE_ID)

            with self.assertRaises(FileExistsError):
                write_r1_artifacts(
                    artifact,
                    json_path=json_path,
                    markdown_path=markdown_path,
                )


class R1CommandBoundaryTests(unittest.TestCase):
    def test_cli_requires_isolated_worktree_and_python(self) -> None:
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                _parse_args(["--run-r1", "--allow-query-embeddings"])

    def test_worker_environment_does_not_copy_unrelated_secret(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key-value-that-is-never-printed",
                "UNRELATED_SECRET": "must-not-cross-boundary",
            },
            clear=True,
        ):
            environment = _worker_environment(Path("/private/tmp/legacy"))

        self.assertIn("OPENAI_API_KEY", environment)
        self.assertNotIn("UNRELATED_SECRET", environment)
        self.assertEqual(environment["SEARCH_MODE"], "keyword")
        self.assertEqual(environment["TOP_K"], "4")


if __name__ == "__main__":
    unittest.main()

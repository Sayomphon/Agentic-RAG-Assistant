"""Evaluate the frozen Step 1 runtime without modifying its worktree.

This file belongs to the remediation branch, but the orchestrator executes it
with ``PYTHONPATH`` and ``cwd`` pointing at the detached ``5e8537b`` worktree.
All ``src`` imports therefore resolve to the historical implementation. The
worker writes one sanitized JSON document to stdout and never writes baseline
artifacts, queries, document bodies, prompts, environment variables, or
credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from src.config import EMBEDDING_CACHE_DIR, EMBEDDING_MODEL
from src.evaluation.baseline_dataset import load_baseline_cases
from src.evaluation.run_baseline import (
    _case_payload,
    _mode_metrics,
    environment_snapshot,
    run_local_checks,
    verify_manifest,
)
from src.evaluation.run_eval import build_retrievers, evaluate_mode
from src.retrievers.base import load_chunks

WORKER_SCHEMA_VERSION = "track-a-legacy-step1-worker-v1"
SUPPORTED_MODES = ("keyword", "semantic", "hybrid")
_EXPECTED_IMPLEMENTATIONS = {
    "keyword": "BM25Retriever",
    "semantic": "OpenAIEmbeddingRetriever",
    "hybrid": "HybridRetriever",
}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", required=True, type=int)
    parser.add_argument(
        "--run-local-checks",
        action="store_true",
        help="Run the frozen unit and keyword-regression suites once.",
    )
    args = parser.parse_args(argv)
    if args.top_k <= 0:
        parser.error("--top-k must be positive.")
    return args


def _embedding_cache_path() -> Path:
    chunks = load_chunks()
    fingerprint = hashlib.sha256(
        "\x00".join(
            [EMBEDDING_MODEL, *(chunk.as_snippet() for chunk in chunks)]
        ).encode("utf-8")
    ).hexdigest()[:16]
    return Path(EMBEDDING_CACHE_DIR) / f"embeddings-{fingerprint}.npz"


def _require_usable_embedding_cache() -> str:
    """Validate the cache without pickle and refuse a corpus API rebuild."""
    path = _embedding_cache_path()
    if not path.is_file():
        raise RuntimeError("The frozen corpus embedding cache is unavailable.")
    try:
        with np.load(path, allow_pickle=False) as archive:
            matrix = archive["embeddings"]
    except (OSError, KeyError, ValueError) as exc:
        raise RuntimeError(
            "The frozen corpus embedding cache is invalid."
        ) from exc
    if (
        matrix.ndim != 2
        or matrix.shape[0] != len(load_chunks())
        or matrix.shape[1] <= 0
        or not np.isfinite(matrix).all()
    ):
        raise RuntimeError(
            "The frozen corpus embedding cache has an invalid shape."
        )
    return path.name


def _category_metrics(
    results: Sequence[Any],
) -> dict[str, dict[str, float | int]]:
    """Aggregate each dataset category without retaining query text."""
    categories = tuple(dict.fromkeys(result.category for result in results))
    output: dict[str, dict[str, float | int]] = {}
    for category in categories:
        selected = [result for result in results if result.category == category]
        if category == "negative":
            false_positive_rate = (
                sum(result.false_positive for result in selected)
                / len(selected)
            )
            output[category] = {
                "case_count": len(selected),
                "false_positive_rate": false_positive_rate,
                "not_found_discipline": 1.0 - false_positive_rate,
            }
            continue
        output[category] = {
            "case_count": len(selected),
            "hit_rate_at_k": (
                sum(result.hit for result in selected) / len(selected)
            ),
            "recall_at_k": (
                sum(result.recall for result in selected) / len(selected)
            ),
            "mrr": (
                sum(result.reciprocal_rank for result in selected)
                / len(selected)
            ),
        }
    return output


def _health(mode: str, retriever: object) -> dict[str, object]:
    implementation = type(retriever).__name__
    if implementation != _EXPECTED_IMPLEMENTATIONS[mode]:
        raise RuntimeError(
            f"{mode} resolved to an unexpected retrieval implementation."
        )
    failure_count = int(getattr(retriever, "query_failure_count", 0))
    if failure_count:
        raise RuntimeError(
            f"{mode} had {failure_count} embedding provider failure(s)."
        )
    return {
        "implementation": implementation,
        "source": str(getattr(retriever, "SOURCE", mode)),
        "query_failure_count": failure_count,
        "fallback_count": 0,
    }


def build_worker_payload(
    *,
    top_k: int,
    include_local_checks: bool,
) -> dict[str, object]:
    """Run all three historical modes and return a sanitized payload."""
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    cases = load_baseline_cases()
    manifest = verify_manifest(cases)
    cache_name = _require_usable_embedding_cache()
    checks = run_local_checks() if include_local_checks else []

    retrieval: dict[str, object] = {}
    for mode, retriever in build_retrievers(SUPPORTED_MODES).items():
        results = evaluate_mode(retriever, cases, top_k=top_k)
        retrieval[mode] = {
            "health": _health(mode, retriever),
            "metrics": _mode_metrics(results),
            "category_metrics": _category_metrics(results),
            "cases": [_case_payload(result) for result in results],
        }

    return {
        "schema_version": WORKER_SCHEMA_VERSION,
        "top_k": top_k,
        "manifest": manifest,
        "environment": environment_snapshot(),
        "corpus_embedding_cache": {
            "ready": True,
            "file_name": cache_name,
            "corpus_api_call_allowed": False,
        },
        "checks": [
            {
                "name": check.name,
                "command": check.command,
                "exit_code": check.exit_code,
                "duration_ms": check.duration_ms,
                "case_count": check.case_count,
                "passed": check.passed,
            }
            for check in checks
        ],
        "retrieval": retrieval,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = build_worker_payload(
        top_k=args.top_k,
        include_local_checks=args.run_local_checks,
    )
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

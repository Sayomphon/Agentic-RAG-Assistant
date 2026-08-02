"""Create and verify the Enterprise Track Phase 0 baseline.

The default command is entirely local and measures keyword retrieval. Semantic
or hybrid evaluation is opt-in because it sends evaluation query strings to
the configured OpenAI Embeddings project. Knowledge-base content is never sent
unless the operator separately permits rebuilding a missing/corrupt corpus
embedding cache.

Usage:
    python -m src.evaluation.run_phase0 --initialize-manifest
    python -m src.evaluation.run_phase0 --verify-manifest-only
    python -m src.evaluation.run_phase0
    python -m src.evaluation.run_phase0 \
        --modes keyword semantic hybrid --allow-query-embeddings
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime
from typing import Mapping, Sequence

from src.config import (
    EMBEDDING_CACHE_DIR,
    EMBEDDING_MODEL,
    RERANKER_ENABLED,
    TOP_K,
)
from src.evaluation.baseline_dataset import (
    BaselineCase,
    load_baseline_cases,
)
from src.evaluation.baseline_support import (
    CheckResult,
    case_payload,
    checks_table,
    environment_snapshot,
    mode_metrics,
    retrieval_summary_table,
    run_answer_evaluation,
    run_contract_check,
    run_local_checks,
)
from src.evaluation.phase0 import (
    PHASE0_V1_SPEC,
    Phase0BaselineSpec,
    verify_phase0_manifest,
    write_phase0_manifest,
)
from src.evaluation.run_eval import (
    CaseResult,
    category_table,
    misses_table,
)
from src.retrievers import get_retriever
from src.retrievers.base import Retriever, load_chunks
from src.retrievers.dense import has_usable_embedding_cache
from src.retrievers.reranker import RerankingRetriever

SUPPORTED_MODES = ("keyword", "semantic", "hybrid")
_EXPECTED_SOURCES = {
    "keyword": "bm25",
    "semantic": "dense",
    "hybrid": "hybrid",
}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--initialize-manifest",
        action="store_true",
        help="Create the reviewed Phase 0 manifest once, then exit.",
    )
    parser.add_argument(
        "--verify-manifest-only",
        action="store_true",
        help=(
            "Strictly compare current source/data/config with the frozen "
            "Phase 0 manifest, then exit without running evaluation."
        ),
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=SUPPORTED_MODES,
        default=["keyword"],
        help="Retrieval modes to measure (default: keyword).",
    )
    parser.add_argument(
        "--allow-query-embeddings",
        action="store_true",
        help=(
            "Allow evaluation query strings to be sent to the configured "
            "OpenAI Embeddings project for semantic/hybrid modes."
        ),
    )
    parser.add_argument(
        "--allow-corpus-embeddings",
        action="store_true",
        help=(
            "Allow knowledge-base snippets to be embedded only when the local "
            "content-addressed corpus cache is absent or invalid."
        ),
    )
    parser.add_argument(
        "--include-answer-eval",
        action="store_true",
        help=(
            "Run the paid answer-level evaluation. This sends evaluation "
            "queries, retrieved snippets, and generated answers to OpenAI."
        ),
    )
    parser.add_argument(
        "--answer-mode",
        choices=SUPPORTED_MODES,
        default="hybrid",
        help="Retrieval mode used by answer-level evaluation (default: hybrid).",
    )
    args = parser.parse_args(argv)

    external_modes = set(args.modes) & {"semantic", "hybrid"}
    if external_modes and not args.allow_query_embeddings:
        parser.error(
            "semantic/hybrid evaluation requires --allow-query-embeddings"
        )
    if args.include_answer_eval and not args.allow_query_embeddings:
        parser.error(
            "--include-answer-eval requires --allow-query-embeddings"
        )
    if args.initialize_manifest and args.verify_manifest_only:
        parser.error(
            "--initialize-manifest and --verify-manifest-only are mutually exclusive"
        )
    if (args.initialize_manifest or args.verify_manifest_only) and (
        args.include_answer_eval
        or args.allow_query_embeddings
        or args.allow_corpus_embeddings
        or args.modes != ["keyword"]
    ):
        parser.error(
            "Manifest lifecycle commands cannot be combined with evaluation flags"
        )
    return args


def _ensure_corpus_embedding_boundary(
    *,
    allow_corpus_embeddings: bool,
) -> bool:
    """Return cache status or fail before constructing an external retriever."""
    chunks = load_chunks()
    cache_ready = has_usable_embedding_cache(
        chunks,
        model=EMBEDDING_MODEL,
        cache_dir=EMBEDDING_CACHE_DIR,
    )
    if not cache_ready and not allow_corpus_embeddings:
        raise RuntimeError(
            "The local corpus embedding cache is missing or invalid. Refusing "
            "to send knowledge-base content. Review the data boundary and rerun "
            "with --allow-corpus-embeddings only if that transfer is approved."
        )
    return cache_ready


def _build_runtime_retrievers(
    modes: Sequence[str],
) -> dict[str, Retriever]:
    """Build the same factory-backed implementations used by the application."""
    retrievers: dict[str, Retriever] = {}
    for mode in dict.fromkeys(modes):
        retriever = get_retriever(mode)
        actual_source = str(getattr(retriever, "SOURCE", ""))
        expected_source = _EXPECTED_SOURCES[mode]
        if actual_source != expected_source:
            raise RuntimeError(
                f"{mode} initialized as {type(retriever).__name__} "
                f"(source={actual_source!r}), expected source={expected_source!r}. "
                "Refusing to record a degraded backend as the Phase 0 baseline."
            )
        if (
            mode == "hybrid"
            and RERANKER_ENABLED
            and not isinstance(retriever, RerankingRetriever)
        ):
            raise RuntimeError(
                "Hybrid mode did not initialize the configured reranker; "
                "refusing to record a partial runtime baseline."
            )
        if isinstance(retriever, RerankingRetriever):
            retriever.warmup()
        retrievers[mode] = retriever
    return retrievers


def _runtime_health(retriever: Retriever) -> dict[str, object]:
    return {
        "implementation": type(retriever).__name__,
        "source": str(getattr(retriever, "SOURCE", "")),
        "query_failure_count": int(
            getattr(retriever, "query_failure_count", 0)
        ),
        "reranker_fallback_count": int(
            getattr(retriever, "reranker_fallback_count", 0)
        ),
        "primary_reranker_failure_count": int(
            getattr(retriever, "primary_reranker_failure_count", 0)
        ),
        "secondary_reranker_usage_count": int(
            getattr(retriever, "secondary_reranker_usage_count", 0)
        ),
        "secondary_reranker_failure_count": int(
            getattr(retriever, "secondary_reranker_failure_count", 0)
        ),
        "secondary_policy_rejection_count": int(
            getattr(retriever, "secondary_policy_rejection_count", 0)
        ),
        "fail_closed_count": int(
            getattr(retriever, "fail_closed_count", 0)
        ),
        "fusion_fallback_count": int(
            getattr(retriever, "fusion_fallback_count", 0)
        ),
        "active_reranker_model": str(
            getattr(retriever, "active_reranker_model", "")
        ),
        "last_fallback_reason_code": str(
            getattr(retriever, "last_fallback_reason_code", "")
        ),
        "answerability_rejection_count": int(
            getattr(retriever, "answerability_rejection_count", 0)
        ),
    }


def _assert_healthy_runtime(
    mode: str,
    health: Mapping[str, object],
) -> None:
    query_failures = int(health["query_failure_count"])
    primary_failures = int(health["primary_reranker_failure_count"])
    secondary_usage = int(health["secondary_reranker_usage_count"])
    secondary_failures = int(health["secondary_reranker_failure_count"])
    secondary_policy_rejections = int(
        health["secondary_policy_rejection_count"]
    )
    fail_closed = int(health["fail_closed_count"])
    fusion_fallbacks = int(health["fusion_fallback_count"])
    if (
        query_failures
        or primary_failures
        or secondary_usage
        or secondary_failures
        or secondary_policy_rejections
        or fail_closed
        or fusion_fallbacks
    ):
        raise RuntimeError(
            f"{mode} evaluation degraded: query_failures={query_failures}, "
            f"primary_reranker_failures={primary_failures}, "
            f"secondary_usage={secondary_usage}, "
            f"secondary_failures={secondary_failures}, "
            f"secondary_policy_rejections={secondary_policy_rejections}, "
            f"fail_closed={fail_closed}, "
            f"fusion_fallbacks={fusion_fallbacks}. Refusing to freeze "
            "degraded output as a healthy Phase 0 baseline."
        )


def _evaluate_runtime_mode(
    mode: str,
    retriever: Retriever,
    cases: Sequence[BaselineCase],
    *,
    top_k: int = TOP_K,
) -> list[CaseResult]:
    """Evaluate one mode and abort on the first degraded provider call."""
    results: list[CaseResult] = []
    for case in cases:
        started = time.perf_counter()
        hits = retriever.search(case["query"], top_k=top_k)
        latency_ms = (time.perf_counter() - started) * 1000
        _assert_healthy_runtime(mode, _runtime_health(retriever))
        results.append(
            CaseResult(
                case_id=case["id"],
                category=case["category"],
                expected=tuple(case["expected_titles"]),
                retrieved=tuple(hit.title for hit in hits),
                latency_ms=latency_ms,
            )
        )
    return results


def _build_report(
    *,
    generated_at: str,
    manifest: Mapping[str, object],
    environment: Mapping[str, object],
    checks: Sequence[CheckResult],
    all_results: Mapping[str, list[CaseResult]],
    metrics_by_mode: Mapping[str, Mapping[str, float]],
    health_by_mode: Mapping[str, Mapping[str, object]],
    corpus_cache_ready: bool | None,
    answer_evaluation: CheckResult | None,
) -> str:
    dataset = manifest["dataset"]
    corpus = manifest["corpus"]
    source_tree = manifest["source_tree"]
    assert isinstance(dataset, Mapping)
    assert isinstance(corpus, Mapping)
    assert isinstance(source_tree, Mapping)
    answer_status = (
        "not requested"
        if answer_evaluation is None
        else "PASS" if answer_evaluation.passed else "QUALITY GATE FAILED"
    )

    health_lines = [
        "| mode | implementation | source | query failures "
        "| primary failures | secondary uses | secondary failures "
        "| secondary policy rejects | fail closed | fusion fallback | active model "
        "| answerability rejections |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for mode, health in health_by_mode.items():
        health_lines.append(
            f"| {mode} | {health['implementation']} | {health['source']} | "
            f"{health['query_failure_count']} | "
            f"{health['primary_reranker_failure_count']} | "
            f"{health['secondary_reranker_usage_count']} | "
            f"{health['secondary_reranker_failure_count']} | "
            f"{health['secondary_policy_rejection_count']} | "
            f"{health['fail_closed_count']} | "
            f"{health['fusion_fallback_count']} | "
            f"{health['active_reranker_model'] or '—'} | "
            f"{health['answerability_rejection_count']} |"
        )

    cache_status = (
        "not applicable (keyword-only run)"
        if corpus_cache_ready is None
        else "cache hit; corpus content was not sent"
        if corpus_cache_ready
        else "cache rebuilt with explicit approval"
    )

    return "\n".join(
        [
            "# Enterprise Track — Phase 0 Baseline",
            "",
            f"- Generated at: {generated_at}",
            f"- Baseline ID: `{manifest['baseline_id']}`",
            f"- Retriever contract: `{manifest['retriever_contract_version']}`",
            f"- Dataset: `{dataset['version']}` ({dataset['case_count']} cases)",
            f"- Dataset SHA-256: `{dataset['sha256']}`",
            f"- Corpus SHA-256: `{corpus['sha256']}` "
            f"({corpus['section_count']} sections)",
            f"- Source-tree SHA-256: `{source_tree['sha256']}` "
            f"({source_tree['file_count']} files)",
            f"- Runtime: Python {environment['python_version']}",
            f"- Corpus embedding boundary: {cache_status}",
            f"- Answer-level evaluation: {answer_status}",
            "",
            "## Verification gates",
            "",
            checks_table(checks),
            "",
            "## Retrieval baseline",
            "",
            retrieval_summary_table(metrics_by_mode),
            "",
            "Answerable metrics are separated from negative discipline. "
            "A false positive is any result returned for a negative case.",
            "",
            "## Runtime health",
            "",
            "\n".join(health_lines),
            "",
            "## Per-category breakdown",
            "",
            category_table(dict(all_results)),
            "",
            "## Imperfect cases",
            "",
            misses_table(dict(all_results)),
            "",
            "## Reproducibility and security",
            "",
            "- Unit, exact keyword regression, and Retriever contract gates run "
            "before any external API request.",
            "- Evaluation modes use the same factory-backed implementations as "
            "the application; fallback output is rejected as an invalid baseline.",
            "- Reports store case IDs, labels, retrieved titles, scores, and "
            "latency—not raw queries, prompts, secrets, or document bodies.",
            "- Semantic/hybrid modes send evaluation query strings to OpenAI "
            "Embeddings only after an explicit command-line approval flag.",
            "- A missing/corrupt corpus cache fails closed unless corpus embedding "
            "is approved with a separate flag.",
            "- Any source, test, contract, dependency, dataset, corpus, or runtime "
            "configuration change makes the strict reproduction gate fail. "
            "The historical manifest remains immutable while later-phase CI "
            "validates its structure without comparing current source bytes.",
            "",
        ]
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    spec: Phase0BaselineSpec = PHASE0_V1_SPEC,
) -> int:
    """Initialize or execute the fail-closed Phase 0 baseline."""
    args = _parse_args(argv)
    cases: list[BaselineCase] = load_baseline_cases()

    if args.initialize_manifest:
        manifest = write_phase0_manifest(
            cases,
            path=spec.manifest_path,
            spec=spec,
        )
        print(
            f"Initialized {manifest['baseline_id']} manifest. "
            "Review and version it before relying on the baseline."
        )
        return 0

    if args.verify_manifest_only:
        manifest = verify_phase0_manifest(
            cases,
            path=spec.manifest_path,
            spec=spec,
        )
        print(
            f"{manifest['baseline_id']} exactly matches the current "
            "source, dataset, corpus, contract, and runtime config."
        )
        return 0

    manifest = verify_phase0_manifest(
        cases,
        path=spec.manifest_path,
        spec=spec,
    )
    checks = [*run_local_checks(), run_contract_check()]

    external_modes = set(args.modes) & {"semantic", "hybrid"}
    corpus_cache_ready = (
        _ensure_corpus_embedding_boundary(
            allow_corpus_embeddings=args.allow_corpus_embeddings,
        )
        if external_modes or args.include_answer_eval
        else None
    )

    retrievers = _build_runtime_retrievers(args.modes)
    all_results: dict[str, list[CaseResult]] = {}
    health_by_mode: dict[str, dict[str, object]] = {}
    for mode, retriever in retrievers.items():
        all_results[mode] = _evaluate_runtime_mode(mode, retriever, cases)
        health = _runtime_health(retriever)
        _assert_healthy_runtime(mode, health)
        health_by_mode[mode] = health

    metrics_by_mode = {
        mode: mode_metrics(results)
        for mode, results in all_results.items()
    }
    answer_evaluation = (
        run_answer_evaluation(args.answer_mode)
        if args.include_answer_eval
        else None
    )

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    environment = environment_snapshot()
    payload = {
        "schema_version": spec.report_schema_version,
        "baseline_id": spec.baseline_id,
        "generated_at": generated_at,
        "manifest": manifest,
        "environment": environment,
        "data_boundary": {
            "query_embeddings_approved": bool(external_modes),
            "corpus_embedding_cache_ready": corpus_cache_ready,
            "corpus_embeddings_approved": args.allow_corpus_embeddings,
            "answer_evaluation_approved": args.include_answer_eval,
            "raw_queries_stored": False,
            "document_bodies_stored": False,
        },
        "checks": [
            {**asdict(check), "passed": check.passed}
            for check in checks
        ],
        "retrieval": {
            mode: {
                "health": health_by_mode[mode],
                "metrics": metrics_by_mode[mode],
                "cases": [case_payload(result) for result in results],
            }
            for mode, results in all_results.items()
        },
        "answer_evaluation": (
            None
            if answer_evaluation is None
            else {
                **asdict(answer_evaluation),
                "passed": answer_evaluation.passed,
                "report": "answer_eval_results.md",
            }
        ),
    }
    spec.results_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    spec.results_markdown_path.write_text(
        _build_report(
            generated_at=generated_at,
            manifest=manifest,
            environment=environment,
            checks=checks,
            all_results=all_results,
            metrics_by_mode=metrics_by_mode,
            health_by_mode=health_by_mode,
            corpus_cache_ready=corpus_cache_ready,
            answer_evaluation=answer_evaluation,
        ),
        encoding="utf-8",
    )

    print(retrieval_summary_table(metrics_by_mode))
    print(f"\nWritten to {spec.results_markdown_path.name}")
    print(f"Written to {spec.results_json_path.name}")
    if answer_evaluation is not None and not answer_evaluation.passed:
        print(
            "Answer-level quality gates did not pass; the measured result "
            "remains recorded for review."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

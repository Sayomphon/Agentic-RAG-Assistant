"""Create a reproducible Track A / Step 1 baseline report.

The runner performs fail-fast, no-cost validation before constructing an
embedding retriever. It records only an explicit allowlist of environment and
configuration fields; secrets and raw environment variables are never read
into the report.

Usage:
    python -m src.evaluation.run_baseline
    python -m src.evaluation.run_baseline --modes keyword
    python -m src.evaluation.run_baseline --include-answer-eval
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from src.config import (
    DENSE_WEIGHT,
    EMBEDDING_MODEL,
    FUSION_METHOD,
    KB_PATH,
    MAX_SEARCH_ATTEMPTS,
    MIN_COSINE,
    MIN_MATCHED_TERMS,
    MIN_RELATIVE_SCORE,
    MIN_SCORE,
    MODEL_NAME,
    RRF_K,
    SEARCH_MODE,
    TITLE_BOOST,
    TOP_K,
)
from src.evaluation.baseline_dataset import (
    DATASET_PATH,
    DATASET_VERSION,
    MANIFEST_PATH,
    BaselineCase,
    file_sha256,
    load_baseline_cases,
    validate_baseline_cases,
)
from src.evaluation.baseline_support import (
    CheckResult,
    case_payload as _case_payload,
    checks_table as _checks_table,
    corpus_snapshot,
    environment_snapshot,
    mode_metrics as _mode_metrics,
    PROJECT_ROOT,
    project_path as _project_path,
    retrieval_summary_table as _retrieval_summary_table,
    run_answer_evaluation as _run_answer_evaluation,
    run_local_checks,
)
from src.evaluation.run_eval import (
    CaseResult,
    build_retrievers,
    category_table,
    evaluate_mode,
    misses_table,
)
from src.retrievers.base import load_chunks

RESULTS_JSON_PATH = PROJECT_ROOT / "baseline_results.json"
RESULTS_MARKDOWN_PATH = PROJECT_ROOT / "baseline_results.md"
SUPPORTED_MODES = ("keyword", "semantic", "hybrid")
def retrieval_config_snapshot() -> dict[str, object]:
    """Return the non-secret settings needed to reproduce retrieval results."""
    return {
        "search_mode": SEARCH_MODE,
        "top_k": TOP_K,
        "min_score": MIN_SCORE,
        "min_matched_terms": MIN_MATCHED_TERMS,
        "min_relative_score": MIN_RELATIVE_SCORE,
        "title_boost": TITLE_BOOST,
        "min_cosine": MIN_COSINE,
        "fusion_method": FUSION_METHOD,
        "rrf_k": RRF_K,
        "dense_weight": DENSE_WEIGHT,
        "embedding_model": EMBEDDING_MODEL,
        "generator_model": MODEL_NAME,
        "max_search_attempts": MAX_SEARCH_ATTEMPTS,
    }


def expected_manifest(cases: Sequence[BaselineCase]) -> dict[str, object]:
    """Build the immutable dataset/corpus/config identity for this baseline."""
    chunks = load_chunks(str(_project_path(KB_PATH)))
    category_distribution = validate_baseline_cases(
        cases,
        valid_titles={chunk.title for chunk in chunks},
    )
    language_distribution: dict[str, int] = {}
    for case in cases:
        language = case["language"]
        language_distribution[language] = language_distribution.get(language, 0) + 1
    return {
        "dataset_version": DATASET_VERSION,
        "created_at": "2026-07-27",
        "dataset_file": DATASET_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "dataset_sha256": file_sha256(DATASET_PATH),
        "corpus": corpus_snapshot(),
        "embedding_model": EMBEDDING_MODEL,
        "retrieval_config": retrieval_config_snapshot(),
        "case_count": len(cases),
        "category_distribution": category_distribution,
        "language_distribution": language_distribution,
    }


def verify_manifest(
    cases: Sequence[BaselineCase],
    *,
    require_current_config: bool = True,
) -> dict[str, object]:
    """Verify frozen evidence, optionally requiring the old runtime config.

    Step 1 creation remains strict: its runner refuses to overwrite a baseline
    after retrieval settings change. Later steps can still verify the immutable
    dataset/corpus identity without pretending the current tuned config is the
    original baseline config.
    """
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Baseline manifest not found: {MANIFEST_PATH}")
    recorded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    current = expected_manifest(cases)
    if not require_current_config and isinstance(recorded, dict):
        current["retrieval_config"] = recorded.get("retrieval_config")
    if recorded != current:
        raise ValueError(
            "Baseline manifest does not match the current dataset, corpus, or "
            "retrieval config. Review the change and version a new manifest."
        )
    return current


def _build_report(
    *,
    generated_at: str,
    manifest: Mapping[str, object],
    environment: Mapping[str, object],
    checks: Sequence[CheckResult],
    all_results: Mapping[str, list[CaseResult]],
    mode_metrics: Mapping[str, Mapping[str, float]],
    answer_evaluation: CheckResult | None,
) -> str:
    python_version = environment["python_version"]
    corpus = manifest["corpus"]
    assert isinstance(corpus, Mapping)
    answer_status = (
        "not requested"
        if answer_evaluation is None
        else "PASS" if answer_evaluation.passed else "QUALITY GATE FAILED"
    )
    return "\n".join(
        [
            "# Track A — Step 1 Mini Baseline",
            "",
            f"- Generated at: {generated_at}",
            f"- Dataset: `{manifest['dataset_version']}` "
            f"({manifest['case_count']} cases)",
            f"- Dataset SHA-256: `{manifest['dataset_sha256']}`",
            f"- Corpus SHA-256: `{corpus['sha256']}` "
            f"({corpus['section_count']} sections)",
            f"- Runtime: Python {python_version}",
            f"- Answer-level evaluation: {answer_status}",
            "",
            "## Verification gates",
            "",
            _checks_table(checks),
            "",
            "## Retrieval baseline",
            "",
            _retrieval_summary_table(mode_metrics),
            "",
            "Metrics for answerable cases are reported separately from negative "
            "discipline. A false positive is any returned chunk for a negative case.",
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
            "- Direct dependencies and installed versions are recorded in "
            "`baseline_results.json`.",
            "- The report captures only an explicit non-secret configuration allowlist.",
            "- API keys, raw environment variables, prompts, and document bodies are "
            "not written to baseline artifacts.",
            "- Re-running against a changed dataset, corpus, or retrieval config fails "
            "the manifest gate and requires an explicit new version.",
            "",
        ]
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=SUPPORTED_MODES,
        default=list(SUPPORTED_MODES),
        help="Retrieval modes to measure (default: all).",
    )
    parser.add_argument(
        "--include-answer-eval",
        action="store_true",
        help="Run the existing paid answer-level evaluation after retrieval.",
    )
    parser.add_argument(
        "--answer-mode",
        choices=SUPPORTED_MODES,
        default="hybrid",
        help="Mode used by answer-level evaluation (default: hybrid).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate, measure, and write JSON/Markdown baseline artifacts."""
    args = _parse_args(argv)
    cases = load_baseline_cases()

    # All local correctness and manifest checks run before any paid API call.
    manifest = verify_manifest(cases)
    checks = run_local_checks()

    retrievers = build_retrievers(args.modes)
    all_results: dict[str, list[CaseResult]] = {}
    for mode, retriever in retrievers.items():
        all_results[mode] = evaluate_mode(retriever, cases)
        provider_failures = int(getattr(retriever, "query_failure_count", 0))
        if provider_failures:
            raise RuntimeError(
                f"{mode} retrieval had {provider_failures} embedding provider "
                "failure(s); refusing to record fallback results as a baseline."
            )
    mode_metrics = {
        mode: _mode_metrics(results)
        for mode, results in all_results.items()
    }
    answer_evaluation = (
        _run_answer_evaluation(args.answer_mode)
        if args.include_answer_eval
        else None
    )

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    environment = environment_snapshot()
    payload = {
        "schema_version": "track-a-step1-baseline-v1",
        "generated_at": generated_at,
        "manifest": manifest,
        "environment": environment,
        "checks": [
            {**asdict(check), "passed": check.passed}
            for check in checks
        ],
        "retrieval": {
            mode: {
                "metrics": mode_metrics[mode],
                "cases": [_case_payload(result) for result in results],
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
    RESULTS_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    RESULTS_MARKDOWN_PATH.write_text(
        _build_report(
            generated_at=generated_at,
            manifest=manifest,
            environment=environment,
            checks=checks,
            all_results=all_results,
            mode_metrics=mode_metrics,
            answer_evaluation=answer_evaluation,
        ),
        encoding="utf-8",
    )

    print(_retrieval_summary_table(mode_metrics))
    print(f"\nWritten to {RESULTS_MARKDOWN_PATH.relative_to(PROJECT_ROOT)}")
    print(f"Written to {RESULTS_JSON_PATH.relative_to(PROJECT_ROOT)}")
    if answer_evaluation is not None and not answer_evaluation.passed:
        print(
            "Answer-level quality gate did not pass; the baseline was still "
            "recorded for comparison."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

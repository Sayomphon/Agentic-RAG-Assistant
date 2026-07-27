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
import importlib.metadata
import json
import math
import platform
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

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
from src.evaluation.run_eval import (
    CaseResult,
    build_retrievers,
    category_table,
    evaluate_mode,
    misses_table,
    summarize,
)
from src.retrievers.base import load_chunks

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
RESULTS_JSON_PATH = PROJECT_ROOT / "baseline_results.json"
RESULTS_MARKDOWN_PATH = PROJECT_ROOT / "baseline_results.md"
SUPPORTED_MODES = ("keyword", "semantic", "hybrid")

_UNIT_TEST_COUNT = re.compile(r"Ran (?P<count>\d+) tests?")
_REGRESSION_CASE_COUNT = re.compile(r"SUMMARY\s+cases=(?P<count>\d+)")


@dataclass(frozen=True)
class CheckResult:
    """Sanitized outcome of one local verification command."""

    name: str
    command: str
    exit_code: int
    duration_ms: float
    case_count: int | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def _project_path(path: str | Path) -> Path:
    """Resolve a configured project path without depending on current cwd."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _corpus_files(path: str | Path = KB_PATH) -> list[Path]:
    """Return source files in the same deterministic order as ``load_chunks``."""
    corpus_path = _project_path(path)
    if corpus_path.is_dir():
        files = sorted(corpus_path.glob("*.txt"))
        if not files:
            raise FileNotFoundError(f"No .txt files found under {corpus_path}.")
        return files
    if corpus_path.is_file():
        return [corpus_path]
    raise FileNotFoundError(f"Knowledge base not found at {corpus_path}.")


def corpus_snapshot(path: str | Path = KB_PATH) -> dict[str, object]:
    """Fingerprint source names and bytes, plus section count and total size."""
    import hashlib

    files = _corpus_files(path)
    digest = hashlib.sha256()
    total_bytes = 0
    for source in files:
        relative_name = source.relative_to(PROJECT_ROOT).as_posix()
        content = source.read_bytes()
        encoded_name = relative_name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        total_bytes += len(content)

    chunks = load_chunks(str(_project_path(path)))
    return {
        "algorithm": "sha256(length-prefixed-relative-path-and-bytes-v1)",
        "sha256": digest.hexdigest(),
        "source_files": [
            source.relative_to(PROJECT_ROOT).as_posix() for source in files
        ],
        "source_file_count": len(files),
        "section_count": len(chunks),
        "total_bytes": total_bytes,
    }


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


def _direct_dependencies(
    requirements_path: Path = REQUIREMENTS_PATH,
) -> list[dict[str, str]]:
    """Compare pinned direct dependencies with installed distribution versions."""
    dependencies: list[dict[str, str]] = []
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        package, separator, declared = line.partition("==")
        if not separator:
            raise ValueError(f"Dependency must be exactly pinned: {line!r}.")
        try:
            installed = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            installed = "(not installed)"
        dependencies.append(
            {
                "package": package,
                "declared": declared,
                "installed": installed,
            }
        )
    return dependencies


def environment_snapshot() -> dict[str, object]:
    """Capture an allowlisted environment summary without inspecting secrets."""
    executable = Path(sys.executable)
    try:
        executable_label = executable.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        executable_label = executable.name
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": executable_label,
        "operating_system": platform.system(),
        "operating_system_release": platform.release(),
        "machine": platform.machine(),
        "dependencies": _direct_dependencies(),
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


def verify_manifest(cases: Sequence[BaselineCase]) -> dict[str, object]:
    """Fail if the versioned manifest no longer matches data, corpus, or config."""
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Baseline manifest not found: {MANIFEST_PATH}")
    recorded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    current = expected_manifest(cases)
    if recorded != current:
        raise ValueError(
            "Baseline manifest does not match the current dataset, corpus, or "
            "retrieval config. Review the change and version a new manifest."
        )
    return current


def _run_check(
    name: str,
    arguments: Sequence[str],
    *,
    count_pattern: re.Pattern[str],
    timeout_seconds: int = 120,
) -> CheckResult:
    """Run a trusted local command without a shell and retain no raw output."""
    started = time.perf_counter()
    completed = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
    )
    duration_ms = (time.perf_counter() - started) * 1000
    combined_output = f"{completed.stdout}\n{completed.stderr}"
    match = count_pattern.search(combined_output)
    result = CheckResult(
        name=name,
        command=" ".join(["python", *arguments[1:]]),
        exit_code=completed.returncode,
        duration_ms=duration_ms,
        case_count=int(match.group("count")) if match else None,
    )
    if not result.passed:
        diagnostic = combined_output.strip()[-4000:]
        raise RuntimeError(
            f"{name} failed with exit code {completed.returncode}.\n{diagnostic}"
        )
    return result


def run_local_checks() -> list[CheckResult]:
    """Run all zero-cost gates before any embedding or LLM request."""
    return [
        _run_check(
            "unit_tests",
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-v",
            ],
            count_pattern=_UNIT_TEST_COUNT,
        ),
        _run_check(
            "keyword_regression",
            [sys.executable, "-m", "src.evaluation.regression"],
            count_pattern=_REGRESSION_CASE_COUNT,
        ),
    ]


def _percentile(values: Sequence[float], quantile: float) -> float:
    """Return an interpolated percentile for a non-empty sequence."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _mode_metrics(results: list[CaseResult]) -> dict[str, float]:
    aggregate = summarize(results)
    latencies = [result.latency_ms for result in results]
    return {
        "hit_rate_at_k": float(aggregate["hit_rate"]),
        "recall_at_k": float(aggregate["recall"]),
        "mrr": float(aggregate["mrr"]),
        "false_positive_rate": float(aggregate["fp_rate"]),
        "not_found_discipline": 1.0 - float(aggregate["fp_rate"]),
        "latency_avg_ms": float(aggregate["latency_ms"]),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


def _case_payload(result: CaseResult) -> dict[str, object]:
    """Serialize labels and outcomes without duplicating raw query text."""
    is_answerable = bool(result.expected)
    return {
        "case_id": result.case_id,
        "category": result.category,
        "expected_titles": list(result.expected),
        "retrieved_titles": list(result.retrieved),
        "hit": result.hit,
        "recall": result.recall if is_answerable else None,
        "reciprocal_rank": result.reciprocal_rank if is_answerable else None,
        "false_positive": result.false_positive,
        "latency_ms": result.latency_ms,
    }


def _format_percent(value: float) -> str:
    return f"{value:.1%}"


def _retrieval_summary_table(
    mode_metrics: Mapping[str, Mapping[str, float]],
) -> str:
    lines = [
        "| mode | hit@k | recall@k | MRR | not-found discipline | avg latency | p95 latency |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, metrics in mode_metrics.items():
        lines.append(
            f"| {mode} | {_format_percent(metrics['hit_rate_at_k'])} | "
            f"{_format_percent(metrics['recall_at_k'])} | {metrics['mrr']:.3f} | "
            f"{_format_percent(metrics['not_found_discipline'])} | "
            f"{metrics['latency_avg_ms']:.1f} ms | "
            f"{metrics['latency_p95_ms']:.1f} ms |"
        )
    return "\n".join(lines)


def _checks_table(checks: Sequence[CheckResult]) -> str:
    lines = [
        "| check | result | count | duration |",
        "|---|---|---:|---:|",
    ]
    for check in checks:
        lines.append(
            f"| {check.name} | {'PASS' if check.passed else 'FAIL'} | "
            f"{check.case_count if check.case_count is not None else '—'} | "
            f"{check.duration_ms:.1f} ms |"
        )
    return "\n".join(lines)


def _run_answer_evaluation(mode: str) -> CheckResult:
    """Run the existing answer-level quality gate using the approved API key."""
    answer_report = PROJECT_ROOT / "answer_eval_results.md"
    previous_mtime = (
        answer_report.stat().st_mtime_ns if answer_report.is_file() else None
    )
    started = time.perf_counter()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.run_answer_eval",
            mode,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=900,
    )
    current_mtime = (
        answer_report.stat().st_mtime_ns if answer_report.is_file() else None
    )
    if current_mtime == previous_mtime:
        diagnostic = f"{completed.stdout}\n{completed.stderr}".strip()[-4000:]
        raise RuntimeError(
            "Answer evaluation did not produce a fresh report; this indicates "
            f"a runtime/provider failure rather than a quality result.\n{diagnostic}"
        )
    return CheckResult(
        name=f"answer_evaluation_{mode}",
        command=f"python -m src.evaluation.run_answer_eval {mode}",
        exit_code=completed.returncode,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


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

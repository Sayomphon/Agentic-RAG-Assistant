"""Shared, security-conscious helpers for reproducible baseline runners.

The Track A and Enterprise Phase 0 runners use the same local gates,
environment snapshot, metrics, and report tables. Keeping those mechanics in
one module prevents the two baselines from drifting while their frozen
manifests and output schemas remain independently versioned.
"""

from __future__ import annotations

import importlib.metadata
import math
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from src.config import KB_PATH
from src.evaluation.run_eval import CaseResult, summarize
from src.retrievers.base import load_chunks

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"

_UNIT_TEST_COUNT = re.compile(r"Ran (?P<count>\d+) tests?")
_REGRESSION_CASE_COUNT = re.compile(r"SUMMARY\s+cases=(?P<count>\d+)")
_LOCAL_CHECK_ENVIRONMENT = {
    # The regression suite is contractually the no-network keyword baseline.
    # An operator's .env must not silently turn it into a paid hybrid run.
    "SEARCH_MODE": "keyword",
    "PYTHONHASHSEED": "0",
}


@dataclass(frozen=True)
class CheckResult:
    """Sanitized outcome of one trusted local verification command."""

    name: str
    command: str
    exit_code: int
    duration_ms: float
    case_count: int | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def project_path(path: str | Path) -> Path:
    """Resolve a configured project path without depending on current cwd."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _corpus_files(path: str | Path = KB_PATH) -> list[Path]:
    """Return corpus files in the same deterministic order as ``load_chunks``."""
    corpus_path = project_path(path)
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

    chunks = load_chunks(str(project_path(path)))
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


def direct_dependencies(
    requirements_path: Path = REQUIREMENTS_PATH,
) -> list[dict[str, str]]:
    """Compare pinned direct dependencies with installed versions."""
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
    """Capture an allowlisted runtime summary without inspecting secrets."""
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
        "dependencies": direct_dependencies(),
    }


def _run_check(
    name: str,
    arguments: Sequence[str],
    *,
    count_pattern: re.Pattern[str],
    timeout_seconds: int = 120,
    environment_overrides: Mapping[str, str] | None = None,
) -> CheckResult:
    """Run a trusted command without a shell and retain no raw output."""
    child_environment = os.environ.copy()
    child_environment.update(environment_overrides or {})

    started = time.perf_counter()
    completed = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        env=child_environment,
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
            environment_overrides=_LOCAL_CHECK_ENVIRONMENT,
        ),
        _run_check(
            "keyword_regression",
            [sys.executable, "-m", "src.evaluation.regression"],
            count_pattern=_REGRESSION_CASE_COUNT,
            environment_overrides=_LOCAL_CHECK_ENVIRONMENT,
        ),
    ]


def run_contract_check() -> CheckResult:
    """Run the frozen Retriever contract suite as an explicit Phase 0 gate."""
    return _run_check(
        "retriever_contract",
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_retriever_contract",
            "-v",
        ],
        count_pattern=_UNIT_TEST_COUNT,
        environment_overrides=_LOCAL_CHECK_ENVIRONMENT,
    )


def run_answer_evaluation(mode: str) -> CheckResult:
    """Run the existing answer-level quality gate with a fresh-report check."""
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


def mode_metrics(results: list[CaseResult]) -> dict[str, float]:
    """Aggregate retrieval quality, negative discipline, and latency."""
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


def case_payload(result: CaseResult) -> dict[str, object]:
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


def retrieval_summary_table(
    metrics_by_mode: Mapping[str, Mapping[str, float]],
) -> str:
    """Render the common retrieval summary table."""
    lines = [
        "| mode | hit@k | recall@k | MRR | not-found discipline | avg latency | p95 latency |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, metrics in metrics_by_mode.items():
        lines.append(
            f"| {mode} | {_format_percent(metrics['hit_rate_at_k'])} | "
            f"{_format_percent(metrics['recall_at_k'])} | {metrics['mrr']:.3f} | "
            f"{_format_percent(metrics['not_found_discipline'])} | "
            f"{metrics['latency_avg_ms']:.1f} ms | "
            f"{metrics['latency_p95_ms']:.1f} ms |"
        )
    return "\n".join(lines)


def checks_table(checks: Sequence[CheckResult]) -> str:
    """Render local verification outcomes without command output."""
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

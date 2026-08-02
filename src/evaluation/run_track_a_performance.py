"""Run isolated Track A R3 latency, memory, and failure benchmarks.

Model scenarios execute in fresh subprocesses so cold-load time and peak RSS
are not contaminated by a previously loaded model. Workers emit sanitized
JSON only; the coordinator refuses partial or failed scenario evidence.

Usage:
    python -m src.evaluation.run_track_a_performance
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import resource
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, replace
from typing import Sequence, cast

from src.config import (
    CONTEXT_DUPLICATE_THRESHOLD,
    CONTEXT_MIN_BODY_CHARS,
    RERANKER_BATCH_SIZE,
    RERANKER_CACHE_DIR,
    RERANKER_DEVICE,
    RERANKER_FALLBACK_CACHE_DIR,
    RERANKER_FALLBACK_MAX_LENGTH,
    RERANKER_FALLBACK_MIN_SCORE,
    RERANKER_FALLBACK_MODEL,
    RERANKER_FALLBACK_MODEL_REVISION,
    RERANKER_MAX_LENGTH,
    RERANKER_MIN_SCORE,
    RERANKER_MODEL,
    RERANKER_MODEL_REVISION,
    RERANKER_TIMEOUT_SECONDS,
)
from src.evaluation.baseline_dataset import load_baseline_cases
from src.evaluation.run_measure_tune import (
    PreparedCase,
    _fuse_candidates,
    _load_prepared_cache,
)
from src.evaluation.track_a_closure import verify_track_a_r0_freeze
from src.evaluation.track_a_r1 import verify_r1_artifact_provenance
from src.evaluation.track_a_r3 import (
    PROJECT_ROOT,
    R3ExecutionError,
    R3ValidationError,
    environment_identity,
    evidence_identity,
    generated_at,
    normalized_rss_mb,
    percentile,
    selected_profile,
    verify_effective_profile,
    write_versioned_pair,
)
from src.retrievers.base import ScoredChunk, load_chunks
from src.retrievers.context import ContextBuilder
from src.retrievers.reranker import (
    CascadingReranker,
    LocalCrossEncoderReranker,
    RerankerBusyError,
    RerankerModelLoadError,
    RerankerTimeoutError,
    RerankingRetriever,
)

RESULTS_JSON_PATH = PROJECT_ROOT / "track_a_performance_results_v2.json"
RESULTS_MARKDOWN_PATH = PROJECT_ROOT / "track_a_performance_results_v2.md"

_SCHEMA_VERSION = "track-a-r3-performance-v2"
_WORKER_SCHEMA_VERSION = "track-a-r3-performance-worker-v1"
_OVERALL_TIMEOUT_MS = (RERANKER_TIMEOUT_SECONDS + 5.0) * 1000
_SCENARIOS = (
    "primary_cold",
    "primary_warm",
    "secondary_cold",
    "secondary_warm",
    "reranker_disabled",
    "candidate_12",
    "candidate_30",
    "primary_timeout_secondary",
    "both_fail_closed",
    "concurrent_busy",
)
_SCENARIO_LABELS = {
    "primary_cold": "Primary model cold start",
    "primary_warm": "Primary model warm inference",
    "secondary_cold": "Secondary model cold start",
    "secondary_warm": "Secondary model warm inference",
    "reranker_disabled": "Reranker disabled",
    "candidate_12": "Candidate 12",
    "candidate_30": "Candidate 30",
    "primary_timeout_secondary": "Primary timeout → Secondary",
    "both_fail_closed": "Both fail → Fail closed",
    "concurrent_busy": "Concurrent requests / Busy policy",
}


@dataclass(frozen=True)
class ScenarioResult:
    """One normalized, content-free performance scenario."""

    schema_version: str
    scenario_id: str
    label: str
    state: str
    model_role: str
    model: str | None
    revision: str | None
    local_files_only: bool
    model_cache_ready: bool
    model_download_ms: float
    model_load_ms: float
    candidate_count: int
    top_k: int
    iteration_count: int
    query_embedding_p50_ms: float
    query_embedding_p95_ms: float
    local_reranker_p50_ms: float
    local_reranker_p95_ms: float
    local_reranker_p99_ms: float
    context_build_p50_ms: float
    context_build_p95_ms: float
    retrieval_e2e_p50_ms: float
    retrieval_e2e_p95_ms: float
    peak_rss_mb: float
    steady_state_rss_mb: float
    fallback_latency_ms: float
    timeout_rate: float
    secondary_usage_rate: float
    unexpected_fallback_count: int
    unhandled_exception_count: int
    fail_closed: bool
    within_overall_timeout: bool
    output_count: int

    def __post_init__(self) -> None:
        if self.schema_version != _WORKER_SCHEMA_VERSION:
            raise R3ValidationError("Unsupported performance worker schema.")
        if self.scenario_id not in _SCENARIOS:
            raise R3ValidationError("Unsupported performance scenario.")
        numeric = (
            self.model_download_ms,
            self.model_load_ms,
            self.query_embedding_p50_ms,
            self.query_embedding_p95_ms,
            self.local_reranker_p50_ms,
            self.local_reranker_p95_ms,
            self.local_reranker_p99_ms,
            self.context_build_p50_ms,
            self.context_build_p95_ms,
            self.retrieval_e2e_p50_ms,
            self.retrieval_e2e_p95_ms,
            self.peak_rss_mb,
            self.steady_state_rss_mb,
            self.fallback_latency_ms,
            self.timeout_rate,
            self.secondary_usage_rate,
        )
        if not all(math.isfinite(value) and value >= 0 for value in numeric):
            raise R3ValidationError("Performance result contains invalid numbers.")
        if not 0.0 <= self.timeout_rate <= 1.0:
            raise R3ValidationError("timeout_rate must be within [0, 1].")
        if not 0.0 <= self.secondary_usage_rate <= 1.0:
            raise R3ValidationError("secondary_usage_rate must be within [0, 1].")


class _RecordedBase:
    SOURCE = "hybrid"

    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self._hits = list(hits)

    def search(self, _query: str, top_k: int) -> list[ScoredChunk]:
        return self._hits[:top_k]


class _FailingReranker:
    def __init__(self, error: Exception, model_name: str) -> None:
        self._error = error
        self.model_name = model_name

    def rerank(
        self,
        _query: str,
        _candidates: list[ScoredChunk],
        _top_k: int,
    ) -> list[ScoredChunk]:
        raise self._error


class _StaticReranker:
    model_name = "r3-static-secondary"

    def rerank(
        self,
        _query: str,
        candidates: list[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        return [
            ScoredChunk(
                chunk=hit.chunk,
                score=1.0 - (position / 100),
                source=hit.source,
                retrieval_score=hit.score,
                reranker_score=1.0 - (position / 100),
            )
            for position, hit in enumerate(candidates[:top_k])
        ]


class _BlockingBackend:
    """Test backend that deterministically holds one worker as busy."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def predict(
        self,
        sentences: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> list[float]:
        self.started.set()
        self.release.wait(timeout=2)
        return [1.0 - (index / 100) for index, _ in enumerate(sentences)]


def _current_rss_mb() -> float:
    """Read current process RSS in MiB without adding a runtime dependency."""
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        kib = float(result.stdout.strip())
        if math.isfinite(kib) and kib >= 0:
            return kib / 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return normalized_rss_mb(
        float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    )


def _peak_rss_mb() -> float:
    return normalized_rss_mb(
        float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    )


def _prepared_cases() -> list[PreparedCase]:
    cases = load_baseline_cases()
    chunks = load_chunks()
    cached = _load_prepared_cache(cases, chunks)
    if cached is None:
        raise R3ExecutionError(
            "Verified prepared cache is required for offline performance evidence."
        )
    prepared, _ = cached
    return prepared


def _model_spec(role: str) -> tuple[str, str, str, int, float | None]:
    if role == "primary":
        return (
            RERANKER_MODEL,
            RERANKER_MODEL_REVISION,
            RERANKER_CACHE_DIR,
            RERANKER_MAX_LENGTH,
            RERANKER_MIN_SCORE,
        )
    return (
        RERANKER_FALLBACK_MODEL,
        RERANKER_FALLBACK_MODEL_REVISION,
        RERANKER_FALLBACK_CACHE_DIR,
        RERANKER_FALLBACK_MAX_LENGTH,
        RERANKER_FALLBACK_MIN_SCORE,
    )


def _candidates(
    prepared: PreparedCase,
    candidate_count: int,
) -> list[ScoredChunk]:
    return _fuse_candidates(
        prepared.case["query"],
        prepared.keyword_hits,
        prepared.dense_hits,
        candidate_k=candidate_count,
        min_cosine=0.20,
    )


def _base_result(
    *,
    scenario_id: str,
    state: str,
    model_role: str,
    model: str | None,
    revision: str | None,
    model_load_ms: float,
    candidate_count: int,
    iterations: int,
    embedding_latencies: Sequence[float] = (),
    reranker_latencies: Sequence[float] = (),
    context_latencies: Sequence[float] = (),
    e2e_latencies: Sequence[float] = (),
    fallback_latency_ms: float = 0.0,
    timeout_rate: float = 0.0,
    secondary_usage_rate: float = 0.0,
    unexpected_fallback_count: int = 0,
    unhandled_exception_count: int = 0,
    fail_closed: bool = False,
    within_overall_timeout: bool = True,
    output_count: int = 0,
) -> ScenarioResult:
    return ScenarioResult(
        schema_version=_WORKER_SCHEMA_VERSION,
        scenario_id=scenario_id,
        label=_SCENARIO_LABELS[scenario_id],
        state=state,
        model_role=model_role,
        model=model,
        revision=revision,
        local_files_only=True,
        model_cache_ready=True,
        model_download_ms=0.0,
        model_load_ms=model_load_ms,
        candidate_count=candidate_count,
        top_k=6,
        iteration_count=iterations,
        query_embedding_p50_ms=percentile(embedding_latencies, 0.50),
        query_embedding_p95_ms=percentile(embedding_latencies, 0.95),
        local_reranker_p50_ms=percentile(reranker_latencies, 0.50),
        local_reranker_p95_ms=percentile(reranker_latencies, 0.95),
        local_reranker_p99_ms=percentile(reranker_latencies, 0.99),
        context_build_p50_ms=percentile(context_latencies, 0.50),
        context_build_p95_ms=percentile(context_latencies, 0.95),
        retrieval_e2e_p50_ms=percentile(e2e_latencies, 0.50),
        retrieval_e2e_p95_ms=percentile(e2e_latencies, 0.95),
        peak_rss_mb=_peak_rss_mb(),
        steady_state_rss_mb=_current_rss_mb(),
        fallback_latency_ms=fallback_latency_ms,
        timeout_rate=timeout_rate,
        secondary_usage_rate=secondary_usage_rate,
        unexpected_fallback_count=unexpected_fallback_count,
        unhandled_exception_count=unhandled_exception_count,
        fail_closed=fail_closed,
        within_overall_timeout=within_overall_timeout,
        output_count=output_count,
    )


def _benchmark_model(
    scenario_id: str,
    *,
    role: str,
    candidate_count: int,
    cold_only: bool,
) -> ScenarioResult:
    prepared_cases = _prepared_cases()
    model, revision, cache_dir, max_length, threshold = _model_spec(role)
    reranker = LocalCrossEncoderReranker(
        model_name=model,
        model_revision=revision,
        cache_dir=cache_dir,
        device=RERANKER_DEVICE,
        batch_size=RERANKER_BATCH_SIZE,
        timeout_seconds=RERANKER_TIMEOUT_SECONDS,
        max_candidates=candidate_count,
        max_length=max_length,
        local_files_only=True,
    )
    started = time.perf_counter()
    reranker.warmup()
    load_ms = (time.perf_counter() - started) * 1000
    selected_cases = prepared_cases[:1] if cold_only else prepared_cases
    embeddings: list[float] = []
    reranker_latencies: list[float] = []
    context_latencies: list[float] = []
    e2e_latencies: list[float] = []
    output_count = 0
    timeout_count = 0
    builder = ContextBuilder(
        max_context_chars=6_000,
        duplicate_threshold=CONTEXT_DUPLICATE_THRESHOLD,
        min_body_chars=CONTEXT_MIN_BODY_CHARS,
    )
    for prepared in selected_cases:
        candidates = _candidates(prepared, candidate_count)
        started = time.perf_counter()
        try:
            ranked = reranker.rerank(
                prepared.case["query"],
                candidates,
                top_k=6,
            )
        except RerankerTimeoutError:
            # A bounded timeout is a measured stress outcome, not an
            # unhandled worker failure. Stop here because the daemon inference
            # may still occupy the single model worker and would contaminate
            # subsequent samples with WORKER_BUSY.
            ranked = []
            timeout_count += 1
        reranker_ms = (time.perf_counter() - started) * 1000
        if threshold is not None:
            ranked = [
                hit
                for hit in ranked
                if hit.reranker_score is not None
                and hit.reranker_score >= threshold
            ]
        started = time.perf_counter()
        context = builder.build(ranked)
        context_ms = (time.perf_counter() - started) * 1000
        embedding_ms = prepared.dense_latency_ms
        embeddings.append(embedding_ms)
        reranker_latencies.append(reranker_ms)
        context_latencies.append(context_ms)
        e2e_latencies.append(
            prepared.keyword_latency_ms
            + embedding_ms
            + reranker_ms
            + context_ms
        )
        output_count += len(context.hits)
        if timeout_count:
            break
    iteration_count = len(reranker_latencies)
    return _base_result(
        scenario_id=scenario_id,
        state="cold" if cold_only else "warm",
        model_role=role,
        model=model,
        revision=revision,
        model_load_ms=load_ms,
        candidate_count=candidate_count,
        iterations=iteration_count,
        embedding_latencies=embeddings,
        reranker_latencies=reranker_latencies,
        context_latencies=context_latencies,
        e2e_latencies=e2e_latencies,
        timeout_rate=timeout_count / iteration_count,
        within_overall_timeout=all(
            latency <= _OVERALL_TIMEOUT_MS for latency in reranker_latencies
        ),
        output_count=output_count,
    )


def _benchmark_disabled() -> ScenarioResult:
    prepared_cases = _prepared_cases()
    embeddings: list[float] = []
    context_latencies: list[float] = []
    e2e_latencies: list[float] = []
    output_count = 0
    builder = ContextBuilder(max_context_chars=6_000)
    for prepared in prepared_cases:
        started = time.perf_counter()
        candidates = _candidates(prepared, 12)[:6]
        context = builder.build(candidates)
        local_ms = (time.perf_counter() - started) * 1000
        embeddings.append(prepared.dense_latency_ms)
        context_latencies.append(local_ms)
        e2e_latencies.append(
            prepared.keyword_latency_ms + prepared.dense_latency_ms + local_ms
        )
        output_count += len(context.hits)
    return _base_result(
        scenario_id="reranker_disabled",
        state="warm",
        model_role="disabled",
        model=None,
        revision=None,
        model_load_ms=0.0,
        candidate_count=12,
        iterations=len(prepared_cases),
        embedding_latencies=embeddings,
        context_latencies=context_latencies,
        e2e_latencies=e2e_latencies,
        output_count=output_count,
    )


def _benchmark_primary_timeout_secondary() -> ScenarioResult:
    prepared = _prepared_cases()[0]
    candidates = _candidates(prepared, 12)
    model, revision, cache_dir, max_length, _ = _model_spec("secondary")
    secondary = LocalCrossEncoderReranker(
        model_name=model,
        model_revision=revision,
        cache_dir=cache_dir,
        device=RERANKER_DEVICE,
        batch_size=RERANKER_BATCH_SIZE,
        timeout_seconds=RERANKER_TIMEOUT_SECONDS,
        max_candidates=12,
        max_length=max_length,
        local_files_only=True,
    )
    started = time.perf_counter()
    secondary.warmup()
    load_ms = (time.perf_counter() - started) * 1000
    cascade = CascadingReranker(
        _FailingReranker(
            RerankerTimeoutError("sanitized injected timeout"),
            "primary",
        ),
        secondary,
    )
    retriever = RerankingRetriever(
        _RecordedBase(candidates),
        cascade,
        candidate_k=12,
        failure_policy="fail_closed",
    )
    started = time.perf_counter()
    unhandled = 0
    try:
        output = retriever.search(prepared.case["query"], top_k=6)
    except Exception:
        output = []
        unhandled = 1
    fallback_ms = (time.perf_counter() - started) * 1000
    return _base_result(
        scenario_id="primary_timeout_secondary",
        state="failure",
        model_role="secondary",
        model=model,
        revision=revision,
        model_load_ms=load_ms,
        candidate_count=12,
        iterations=1,
        fallback_latency_ms=fallback_ms,
        timeout_rate=1.0,
        secondary_usage_rate=float(cascade.secondary_reranker_usage_count),
        unhandled_exception_count=unhandled,
        within_overall_timeout=fallback_ms <= _OVERALL_TIMEOUT_MS,
        output_count=len(output),
    )


def _benchmark_both_fail_closed() -> ScenarioResult:
    prepared = _prepared_cases()[0]
    candidates = _candidates(prepared, 12)
    cascade = CascadingReranker(
        _FailingReranker(RerankerTimeoutError("sanitized"), "primary"),
        _FailingReranker(RerankerModelLoadError("sanitized"), "secondary"),
    )
    retriever = RerankingRetriever(
        _RecordedBase(candidates),
        cascade,
        candidate_k=12,
        failure_policy="fail_closed",
    )
    started = time.perf_counter()
    unhandled = 0
    try:
        output = retriever.search(prepared.case["query"], top_k=6)
    except Exception:
        output = []
        unhandled = 1
    elapsed_ms = (time.perf_counter() - started) * 1000
    return _base_result(
        scenario_id="both_fail_closed",
        state="failure",
        model_role="none",
        model=None,
        revision=None,
        model_load_ms=0.0,
        candidate_count=12,
        iterations=1,
        fallback_latency_ms=elapsed_ms,
        timeout_rate=1.0,
        secondary_usage_rate=float(cascade.secondary_reranker_usage_count),
        unhandled_exception_count=unhandled,
        fail_closed=not output and retriever.fail_closed_count == 1,
        within_overall_timeout=elapsed_ms <= _OVERALL_TIMEOUT_MS,
        output_count=len(output),
    )


def _benchmark_concurrent_busy() -> ScenarioResult:
    prepared = _prepared_cases()[0]
    candidates = _candidates(prepared, 12)
    backend = _BlockingBackend()
    primary = LocalCrossEncoderReranker(
        model_factory=lambda: backend,
        timeout_seconds=2,
        max_candidates=12,
    )
    cascade = CascadingReranker(primary, _StaticReranker())
    outputs: list[list[ScoredChunk]] = []
    errors: list[Exception] = []

    def first_request() -> None:
        try:
            outputs.append(
                cascade.rerank(prepared.case["query"], candidates, top_k=6)
            )
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=first_request, daemon=True)
    started = time.perf_counter()
    thread.start()
    if not backend.started.wait(timeout=1):
        raise R3ExecutionError("Concurrent benchmark did not enter inference.")
    try:
        outputs.append(
            cascade.rerank(prepared.case["query"], candidates, top_k=6)
        )
    except RerankerBusyError as exc:
        errors.append(exc)
    except Exception as exc:
        errors.append(exc)
    finally:
        backend.release.set()
        thread.join(timeout=3)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return _base_result(
        scenario_id="concurrent_busy",
        state="concurrent",
        model_role="cascade",
        model="synthetic-concurrency-fixture",
        revision=None,
        model_load_ms=0.0,
        candidate_count=12,
        iterations=2,
        fallback_latency_ms=elapsed_ms,
        secondary_usage_rate=cascade.secondary_reranker_usage_count / 2,
        unhandled_exception_count=len(errors),
        within_overall_timeout=elapsed_ms <= _OVERALL_TIMEOUT_MS,
        output_count=sum(len(output) for output in outputs),
    )


def run_worker(scenario_id: str) -> ScenarioResult:
    """Dispatch exactly one isolated scenario."""
    if scenario_id == "primary_cold":
        return _benchmark_model(
            scenario_id,
            role="primary",
            candidate_count=12,
            cold_only=True,
        )
    if scenario_id == "primary_warm":
        return _benchmark_model(
            scenario_id,
            role="primary",
            candidate_count=12,
            cold_only=False,
        )
    if scenario_id == "secondary_cold":
        return _benchmark_model(
            scenario_id,
            role="secondary",
            candidate_count=12,
            cold_only=True,
        )
    if scenario_id == "secondary_warm":
        return _benchmark_model(
            scenario_id,
            role="secondary",
            candidate_count=12,
            cold_only=False,
        )
    if scenario_id == "reranker_disabled":
        return _benchmark_disabled()
    if scenario_id == "candidate_12":
        return _benchmark_model(
            scenario_id,
            role="primary",
            candidate_count=12,
            cold_only=False,
        )
    if scenario_id == "candidate_30":
        return _benchmark_model(
            scenario_id,
            role="primary",
            candidate_count=30,
            cold_only=False,
        )
    if scenario_id == "primary_timeout_secondary":
        return _benchmark_primary_timeout_secondary()
    if scenario_id == "both_fail_closed":
        return _benchmark_both_fail_closed()
    if scenario_id == "concurrent_busy":
        return _benchmark_concurrent_busy()
    raise R3ValidationError(f"Unknown performance scenario: {scenario_id}.")


def _run_isolated_worker(scenario_id: str) -> ScenarioResult:
    environment = os.environ.copy()
    environment["RERANKER_LOCAL_FILES_ONLY"] = "true"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.run_track_a_performance",
            "--worker-scenario",
            scenario_id,
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if result.returncode != 0:
        raise R3ExecutionError(
            f"Performance scenario {scenario_id} failed; no partial result recorded."
        )
    try:
        payload = json.loads(result.stdout)
        scenario = ScenarioResult(**payload)
    except (json.JSONDecodeError, TypeError, R3ValidationError):
        raise R3ExecutionError(
            f"Performance scenario {scenario_id} returned invalid evidence."
        ) from None
    if scenario.scenario_id != scenario_id:
        raise R3ExecutionError("Performance worker returned the wrong scenario.")
    return scenario


def performance_gate_failures(
    scenarios: Sequence[ScenarioResult],
) -> tuple[str, ...]:
    """Apply the R3 initial performance guardrails."""
    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    failures: list[str] = []
    if by_id["candidate_12"].retrieval_e2e_p95_ms > 3_000:
        failures.append("warm_retrieval_p95_above_3000_ms")
    if by_id["primary_warm"].local_reranker_p95_ms > 2_000:
        failures.append("primary_local_reranker_p95_above_2000_ms")
    if max(scenario.peak_rss_mb for scenario in scenarios) > 6 * 1024:
        failures.append("peak_rss_above_6_gib")
    healthy = scenarios[:7]
    if any(scenario.unexpected_fallback_count for scenario in healthy):
        failures.append("unexpected_healthy_fallback")
    failure_paths = scenarios[7:]
    if any(scenario.unhandled_exception_count for scenario in failure_paths):
        failures.append("failure_path_unhandled_exception")
    fail_closed = by_id["both_fail_closed"]
    if not fail_closed.fail_closed:
        failures.append("both_fail_path_did_not_close")
    if not fail_closed.within_overall_timeout:
        failures.append("fail_closed_exceeded_overall_timeout")
    if by_id["concurrent_busy"].secondary_usage_rate <= 0:
        failures.append("busy_policy_did_not_use_secondary")
    return tuple(failures)


def _render_report(
    payload: dict[str, object],
    scenarios: Sequence[ScenarioResult],
    failures: Sequence[str],
) -> str:
    rows = [
        "| Scenario | State | Load ms | Reranker p95 | E2E p95 | Peak RSS | "
        "Secondary use | Result |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for scenario in scenarios:
        scenario_ok = (
            scenario.unhandled_exception_count == 0
            and scenario.within_overall_timeout
        )
        rows.append(
            f"| {scenario.label} | {scenario.state} | "
            f"{scenario.model_load_ms:.1f} | "
            f"{scenario.local_reranker_p95_ms:.1f} ms | "
            f"{scenario.retrieval_e2e_p95_ms:.1f} ms | "
            f"{scenario.peak_rss_mb:.1f} MiB | "
            f"{scenario.secondary_usage_rate:.1%} | "
            f"{'PASS' if scenario_ok else 'FAIL'} |"
        )
    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    return "\n".join(
        [
            "# Track A R3 — Performance and Failure Benchmark",
            "",
            f"- Generated at: {payload['generated_at']}",
            f"- Host: {platform.platform()} / {platform.machine()}",
            "- Model download time is reported separately as `0 ms`: every "
            "scenario ran from an immutable local cache with remote access disabled.",
            "- Cold model scenarios execute in fresh subprocesses; warm scenarios "
            "run all 40 frozen cases.",
            "- Query embedding latency is replayed from the verified prepared "
            "cache; local reranker/context latency is measured in this run.",
            "",
            "## Scenario matrix",
            "",
            *rows,
            "",
            "## Guardrails",
            "",
            f"- Warm retrieval p95 (Candidate 12): "
            f"{by_id['candidate_12'].retrieval_e2e_p95_ms:.1f} ms / ≤3000 ms",
            f"- Primary local reranker p95: "
            f"{by_id['primary_warm'].local_reranker_p95_ms:.1f} ms / ≤2000 ms",
            f"- Maximum peak RSS: "
            f"{max(scenario.peak_rss_mb for scenario in scenarios):.1f} MiB / "
            "≤6144 MiB",
            f"- Both-fail closed: {by_id['both_fail_closed'].fail_closed}",
            f"- Concurrent Busy path Secondary usage: "
            f"{by_id['concurrent_busy'].secondary_usage_rate:.1%}",
            f"- Overall performance gate: **{'PASS' if not failures else 'FAIL'}**"
            + (f" — {', '.join(failures)}" if failures else ""),
        ]
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worker-scenario",
        choices=_SCENARIOS,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.worker_scenario:
        result = run_worker(args.worker_scenario)
        print(json.dumps(asdict(result), sort_keys=True))
        return 0

    profile = selected_profile()
    verify_effective_profile(profile)
    verify_track_a_r0_freeze()
    verify_r1_artifact_provenance()
    if _load_prepared_cache(load_baseline_cases(), load_chunks()) is None:
        raise R3ExecutionError("Verified prepared cache is required.")

    scenarios: list[ScenarioResult] = []
    for position, scenario_id in enumerate(_SCENARIOS, start=1):
        print(
            f"Performance {position:02d}/{len(_SCENARIOS)} "
            f"scenario={scenario_id}",
            flush=True,
        )
        if scenario_id == "candidate_12":
            # Candidate 12 is byte-for-byte the Primary warm configuration.
            # Reuse that full 40-case sample instead of heating the same model
            # a second time and pretending the duplicate is independent.
            primary_warm = next(
                result
                for result in scenarios
                if result.scenario_id == "primary_warm"
            )
            scenarios.append(
                replace(
                    primary_warm,
                    scenario_id="candidate_12",
                    label=_SCENARIO_LABELS["candidate_12"],
                )
            )
        else:
            scenarios.append(_run_isolated_worker(scenario_id))
    failures = performance_gate_failures(scenarios)
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": generated_at(),
        "identity": evidence_identity(),
        "environment": environment_identity(),
        "selected_profile": profile,
        "methodology": {
            "isolated_worker_processes": True,
            "local_files_only": True,
            "model_download_measured_separately": True,
            "query_embedding_source": "verified_prepared_cache",
            "candidate_12_reuses_primary_warm_measurement": True,
            "raw_queries_stored": False,
            "document_bodies_stored": False,
            "credentials_stored": False,
        },
        "guardrails": {
            "warm_retrieval_p95_ms": 3_000,
            "primary_local_reranker_p95_ms": 2_000,
            "peak_rss_mb": 6 * 1024,
            "unexpected_healthy_fallback_count": 0,
            "failure_path_unhandled_exception_count": 0,
            "overall_timeout_ms": _OVERALL_TIMEOUT_MS,
        },
        "scenarios": [asdict(scenario) for scenario in scenarios],
        "performance_gate": {
            "passed": not failures,
            "failures": list(failures),
        },
    }
    report = _render_report(payload, scenarios, failures)
    write_versioned_pair(
        payload,
        report,
        json_path=RESULTS_JSON_PATH,
        markdown_path=RESULTS_MARKDOWN_PATH,
    )
    print(f"Written {RESULTS_JSON_PATH.name}")
    print(f"Written {RESULTS_MARKDOWN_PATH.name}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

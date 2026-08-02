"""Offline real-model benchmark for the Track A R2 reranker paths.

The command loads one immutable snapshot from the approved local cache and
uses synthetic policy text only. Output contains model/runtime measurements,
never the query or candidate bodies.

Usage:
    python -m src.evaluation.run_r2_safety --model primary
    python -m src.evaluation.run_r2_safety --model secondary
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import resource
import time
from dataclasses import asdict, dataclass
from typing import Sequence

from src.config import (
    RERANKER_BATCH_SIZE,
    RERANKER_CACHE_DIR,
    RERANKER_DEVICE,
    RERANKER_FALLBACK_CACHE_DIR,
    RERANKER_FALLBACK_MAX_LENGTH,
    RERANKER_FALLBACK_MODEL,
    RERANKER_FALLBACK_MODEL_REVISION,
    RERANKER_MAX_CANDIDATES,
    RERANKER_MAX_LENGTH,
    RERANKER_MODEL,
    RERANKER_MODEL_REVISION,
    RERANKER_TIMEOUT_SECONDS,
)
from src.retrievers.base import Chunk, ScoredChunk
from src.retrievers.reranker import LocalCrossEncoderReranker

_SCHEMA_VERSION = "track-a-r2-reranker-benchmark-v1"
_CANDIDATE_COUNT = 12
_TOP_K = 6
_ITERATIONS = 4


@dataclass(frozen=True)
class ModelSpec:
    role: str
    model: str
    revision: str
    cache_dir: str
    max_length: int


@dataclass(frozen=True)
class BenchmarkResult:
    schema_version: str
    role: str
    model: str
    revision: str
    cache_dir: str
    local_files_only: bool
    trust_remote_code: bool
    device: str
    batch_size: int
    timeout_seconds: float
    max_length: int
    candidate_count: int
    top_k: int
    cold_start_ms: float
    first_inference_ms: float
    warm_inference_avg_ms: float
    warm_inference_p95_ms: float
    peak_rss_mb: float
    output_count: int
    finite_scores: bool
    best_first: bool


def _model_specs() -> dict[str, ModelSpec]:
    return {
        "primary": ModelSpec(
            role="primary",
            model=RERANKER_MODEL,
            revision=RERANKER_MODEL_REVISION,
            cache_dir=RERANKER_CACHE_DIR,
            max_length=RERANKER_MAX_LENGTH,
        ),
        "secondary": ModelSpec(
            role="secondary",
            model=RERANKER_FALLBACK_MODEL,
            revision=RERANKER_FALLBACK_MODEL_REVISION,
            cache_dir=RERANKER_FALLBACK_CACHE_DIR,
            max_length=RERANKER_FALLBACK_MAX_LENGTH,
        ),
    }


def _fixture_hits(count: int) -> list[ScoredChunk]:
    return [
        ScoredChunk(
            chunk=Chunk(
                title=f"Policy {index}",
                text=(
                    "Employees follow the documented approval workflow and "
                    "record the decision in the enterprise system."
                ),
                index=index,
                source_file="r2-synthetic-fixture.txt",
            ),
            score=1.0 / (index + 1),
            source="hybrid",
        )
        for index in range(count)
    ]


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _peak_rss_mb() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux reports KiB.
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return raw / divisor


def benchmark(spec: ModelSpec) -> BenchmarkResult:
    candidate_count = min(_CANDIDATE_COUNT, RERANKER_MAX_CANDIDATES)
    candidates = _fixture_hits(candidate_count)
    reranker = LocalCrossEncoderReranker(
        model_name=spec.model,
        model_revision=spec.revision,
        cache_dir=spec.cache_dir,
        device=RERANKER_DEVICE,
        batch_size=RERANKER_BATCH_SIZE,
        timeout_seconds=RERANKER_TIMEOUT_SECONDS,
        max_candidates=candidate_count,
        max_length=spec.max_length,
        local_files_only=True,
    )

    started = time.perf_counter()
    reranker.warmup()
    cold_start_ms = (time.perf_counter() - started) * 1000

    latencies: list[float] = []
    output: list[ScoredChunk] = []
    for _ in range(_ITERATIONS):
        started = time.perf_counter()
        output = reranker.rerank(
            "documented approval workflow",
            candidates,
            top_k=_TOP_K,
        )
        latencies.append((time.perf_counter() - started) * 1000)

    scores = [hit.score for hit in output]
    warm = latencies[1:]
    return BenchmarkResult(
        schema_version=_SCHEMA_VERSION,
        role=spec.role,
        model=spec.model,
        revision=spec.revision,
        cache_dir=spec.cache_dir,
        local_files_only=True,
        trust_remote_code=False,
        device=RERANKER_DEVICE or "auto",
        batch_size=RERANKER_BATCH_SIZE,
        timeout_seconds=RERANKER_TIMEOUT_SECONDS,
        max_length=spec.max_length,
        candidate_count=candidate_count,
        top_k=_TOP_K,
        cold_start_ms=cold_start_ms,
        first_inference_ms=latencies[0],
        warm_inference_avg_ms=sum(warm) / len(warm),
        warm_inference_p95_ms=_percentile(warm, 0.95),
        peak_rss_mb=_peak_rss_mb(),
        output_count=len(output),
        finite_scores=all(math.isfinite(score) for score in scores),
        best_first=scores == sorted(scores, reverse=True),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark one cached Track A R2 reranker snapshot."
    )
    parser.add_argument(
        "--model",
        choices=tuple(_model_specs()),
        required=True,
        help="Immutable model role to benchmark.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = benchmark(_model_specs()[args.model])
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0 if result.finite_scores and result.best_first else 1


if __name__ == "__main__":
    raise SystemExit(main())

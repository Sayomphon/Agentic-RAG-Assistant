"""Measure and tune Track A quality without overwriting the Step 1 baseline.

The runner sends only the versioned evaluation queries to the configured
OpenAI Embeddings endpoint. Corpus vectors are loaded from the existing local
cache, reranking stays local, and reports contain case IDs/titles rather than
raw queries or document bodies.

The expensive work is bounded:

1. Embed each query exactly once and retain its ranked dense candidates.
2. Score the union of possible fusion candidates once with the local model.
3. Replay the tuning grid entirely in memory.
4. Benchmark only the selected profile through the real local reranker.

Usage:
    python -m src.evaluation.run_measure_tune --allow-query-embeddings
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence, cast

from src.config import (
    CONTEXT_DUPLICATE_THRESHOLD,
    CONTEXT_MIN_BODY_CHARS,
    EMBEDDING_MODEL,
    RERANKER_BATCH_SIZE,
    RERANKER_MAX_LENGTH,
    RERANKER_MODEL,
    RERANKER_MODEL_REVISION,
    RERANKER_TIMEOUT_SECONDS,
)
from src.evaluation.baseline_dataset import (
    DATASET_PATH,
    BaselineCase,
    file_sha256,
    load_baseline_cases,
    validate_baseline_cases,
)
from src.evaluation.run_baseline import (
    _case_payload,
    _checks_table,
    _mode_metrics,
    corpus_snapshot,
    environment_snapshot,
    run_local_checks,
)
from src.evaluation.run_eval import CaseResult
from src.retrievers.base import Chunk, ScoredChunk, load_chunks
from src.retrievers.context import ContextBuilder
from src.retrievers.dense import OpenAIEmbeddingRetriever
from src.retrievers.hybrid import HybridRetriever
from src.retrievers.keyword import BM25Retriever
from src.retrievers.reranker import LocalCrossEncoderReranker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = PROJECT_ROOT / "baseline_results.json"
RESULTS_JSON_PATH = PROJECT_ROOT / "track_a_step3_results.json"
RESULTS_MARKDOWN_PATH = PROJECT_ROOT / "track_a_step3_results.md"
PREPARED_CACHE_PATH = PROJECT_ROOT / ".cache" / "track-a-step3-prepared.json"

CANDIDATE_K_GRID = (12, 24, 30)
TOP_K_GRID = (4, 6)
MIN_COSINE_GRID = (0.00, 0.10, 0.20, 0.30, 0.38)
RERANKER_MIN_SCORE_GRID: tuple[float | None, ...] = (
    None,
    0.01,
    0.05,
    0.10,
    0.20,
    0.50,
)
MAX_CONTEXT_CHARS_GRID = (4_000, 6_000, 12_000)

_EPSILON = 1e-12
_SAFETY_TARGET = 0.90
_BALANCED_QUALITY_RETENTION = 0.90
_BASELINE_SCHEMA = "track-a-step1-baseline-v1"
_RESULT_SCHEMA = "track-a-step3-measure-tune-v1"
_PREPARED_CACHE_SCHEMA = "track-a-step3-prepared-v1"


@dataclass(frozen=True)
class TuneProfile:
    """One bounded retrieval configuration in the offline tuning grid."""

    candidate_k: int
    top_k: int
    min_cosine: float
    reranker_min_score: float | None
    max_context_chars: int
    reranker_enabled: bool = True

    def __post_init__(self) -> None:
        if self.candidate_k <= 0:
            raise ValueError("candidate_k must be positive.")
        if self.top_k <= 0 or self.top_k > self.candidate_k:
            raise ValueError("top_k must be positive and <= candidate_k.")
        if not math.isfinite(self.min_cosine):
            raise ValueError("min_cosine must be finite.")
        if (
            self.reranker_min_score is not None
            and not math.isfinite(self.reranker_min_score)
        ):
            raise ValueError("reranker_min_score must be finite when enabled.")
        if self.max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive.")
        if not self.reranker_enabled and self.reranker_min_score is not None:
            raise ValueError(
                "reranker_min_score cannot be set when reranking is disabled."
            )

    @property
    def profile_id(self) -> str:
        threshold = (
            "none"
            if self.reranker_min_score is None
            else f"{self.reranker_min_score:.2f}"
        )
        reranker = "on" if self.reranker_enabled else "off"
        return (
            f"c{self.candidate_k}-k{self.top_k}-cos{self.min_cosine:.2f}"
            f"-rr{reranker}-{threshold}-ctx{self.max_context_chars}"
        )


@dataclass(frozen=True)
class PreparedCase:
    """Provider and local-model outputs reused by every tuning profile."""

    case: BaselineCase
    keyword_hits: tuple[ScoredChunk, ...]
    dense_hits: tuple[ScoredChunk, ...]
    reranker_scores: Mapping[int, float]
    keyword_latency_ms: float
    dense_latency_ms: float


@dataclass(frozen=True)
class ProfileEvaluation:
    """Metrics and sanitized per-case outcomes for one profile."""

    profile: TuneProfile
    metrics: Mapping[str, float]
    category_metrics: Mapping[str, Mapping[str, float]]
    quality_score: float
    passed_hard_gates: bool
    passed_safety_target: bool
    gate_failures: tuple[str, ...]
    context_avg_chars: float
    context_p95_chars: float
    context_truncation_rate: float
    citation_validity: float
    average_final_hits: float
    cases: tuple[CaseResult, ...]


class _RecordedRetriever:
    """Return one already-ranked list without network or model calls."""

    def __init__(self, hits: Sequence[ScoredChunk]) -> None:
        self._hits = tuple(hits)

    def search(self, _query: str, top_k: int) -> list[ScoredChunk]:
        return list(self._hits[: max(0, top_k)])


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return sum(materialized) / len(materialized) if materialized else 0.0


def _load_frozen_baseline(
    path: Path = BASELINE_PATH,
) -> tuple[dict[str, object], Mapping[str, float], list[dict[str, object]]]:
    """Load Step 1 evidence and verify its immutable data/corpus identity."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != _BASELINE_SCHEMA:
        raise ValueError(
            f"Unsupported baseline schema: {payload.get('schema_version')!r}."
        )

    manifest = payload.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("Baseline manifest is missing or invalid.")
    if manifest.get("dataset_sha256") != file_sha256(DATASET_PATH):
        raise ValueError("Baseline and current evaluation dataset do not match.")

    recorded_corpus = manifest.get("corpus")
    current_corpus = corpus_snapshot()
    if not isinstance(recorded_corpus, dict):
        raise ValueError("Baseline corpus identity is missing or invalid.")
    if recorded_corpus.get("sha256") != current_corpus["sha256"]:
        raise ValueError("Baseline and current corpus do not match.")

    retrieval = payload.get("retrieval")
    if not isinstance(retrieval, dict):
        raise ValueError("Baseline retrieval evidence is missing.")
    keyword = retrieval.get("keyword")
    if not isinstance(keyword, dict):
        raise ValueError("Baseline keyword evidence is missing.")
    metrics = keyword.get("metrics")
    cases = keyword.get("cases")
    if not isinstance(metrics, dict) or not isinstance(cases, list):
        raise ValueError("Baseline keyword metrics/cases are invalid.")
    return (
        payload,
        cast(Mapping[str, float], metrics),
        cast(list[dict[str, object]], cases),
    )


def _category_metrics(results: Sequence[CaseResult]) -> dict[str, dict[str, float]]:
    categories = tuple(dict.fromkeys(result.category for result in results))
    output: dict[str, dict[str, float]] = {}
    for category in categories:
        selected = [result for result in results if result.category == category]
        answerable = [result for result in selected if result.expected]
        negatives = [result for result in selected if not result.expected]
        output[category] = {
            "hit_rate": _mean(float(result.hit) for result in answerable),
            "recall": _mean(result.recall for result in answerable),
            "mrr": _mean(result.reciprocal_rank for result in answerable),
            "not_found_discipline": 1.0
            - _mean(float(result.false_positive) for result in negatives),
        }
    return output


def _baseline_category_metrics(
    cases: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, float]]:
    results = [
        CaseResult(
            case_id=str(case["case_id"]),
            category=str(case["category"]),
            expected=tuple(cast(Sequence[str], case["expected_titles"])),
            retrieved=tuple(cast(Sequence[str], case["retrieved_titles"])),
            latency_ms=float(case["latency_ms"]),
        )
        for case in cases
    ]
    return _category_metrics(results)


def _fuse_candidates(
    query: str,
    keyword_hits: Sequence[ScoredChunk],
    dense_hits: Sequence[ScoredChunk],
    *,
    candidate_k: int,
    min_cosine: float,
) -> list[ScoredChunk]:
    eligible_dense = [
        hit for hit in dense_hits if hit.score >= min_cosine
    ][:candidate_k]
    hybrid = HybridRetriever(
        _RecordedRetriever(keyword_hits[:candidate_k]),
        _RecordedRetriever(eligible_dense),
        candidate_k=candidate_k,
    )
    return hybrid.search(query, top_k=candidate_k)


def _rerank_from_scores(
    candidates: Sequence[ScoredChunk],
    scores: Mapping[int, float],
    *,
    top_k: int,
    min_score: float | None,
) -> list[ScoredChunk]:
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (
            -scores[item[1].chunk.index],
            item[0],
        ),
    )
    output: list[ScoredChunk] = []
    for _, hit in ranked:
        reranker_score = scores[hit.chunk.index]
        if min_score is not None and reranker_score < min_score:
            continue
        output.append(
            ScoredChunk(
                chunk=hit.chunk,
                score=reranker_score,
                source=hit.source,
                retrieval_score=hit.score,
                reranker_score=reranker_score,
            )
        )
        if len(output) == top_k:
            break
    return output


def _possible_fusion_candidates(
    query: str,
    keyword_hits: Sequence[ScoredChunk],
    dense_hits: Sequence[ScoredChunk],
) -> list[ScoredChunk]:
    """Return the exact union that any configured profile may rerank."""
    by_index: dict[int, ScoredChunk] = {}
    for candidate_k in CANDIDATE_K_GRID:
        for min_cosine in MIN_COSINE_GRID:
            for hit in _fuse_candidates(
                query,
                keyword_hits,
                dense_hits,
                candidate_k=candidate_k,
                min_cosine=min_cosine,
            ):
                by_index.setdefault(hit.chunk.index, hit)
    return list(by_index.values())


def _hit_payload(hit: ScoredChunk) -> dict[str, object]:
    """Serialize ranking evidence without query or document content."""
    return {
        "chunk_index": hit.chunk.index,
        "score": hit.score,
        "source": hit.source,
    }


def _restore_hits(
    payloads: Sequence[Mapping[str, object]],
    chunks_by_index: Mapping[int, Chunk],
) -> tuple[ScoredChunk, ...]:
    hits: list[ScoredChunk] = []
    for payload in payloads:
        index = int(payload["chunk_index"])
        if index not in chunks_by_index:
            raise ValueError(f"Prepared cache references unknown chunk {index}.")
        score = float(payload["score"])
        if not math.isfinite(score):
            raise ValueError("Prepared cache contains a non-finite score.")
        hits.append(
            ScoredChunk(
                chunk=chunks_by_index[index],
                score=score,
                source=str(payload["source"]),
            )
        )
    return tuple(hits)


def _prepared_cache_identity() -> dict[str, object]:
    return {
        "dataset_sha256": file_sha256(DATASET_PATH),
        "corpus_sha256": corpus_snapshot()["sha256"],
        "embedding_model": EMBEDDING_MODEL,
        "reranker_model": RERANKER_MODEL,
        "reranker_revision": RERANKER_MODEL_REVISION,
        "candidate_k_grid": list(CANDIDATE_K_GRID),
        "min_cosine_grid": list(MIN_COSINE_GRID),
    }


def _load_prepared_cache(
    cases: Sequence[BaselineCase],
    chunks: Sequence[Chunk],
    path: Path = PREPARED_CACHE_PATH,
) -> tuple[list[PreparedCase], dict[str, float]] | None:
    """Restore sanitized score evidence when its complete identity matches."""
    if not path.is_file():
        return None
    if path.is_symlink():
        raise ValueError("Prepared cache must not be a symbolic link.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != _PREPARED_CACHE_SCHEMA:
        return None
    if payload.get("identity") != _prepared_cache_identity():
        return None

    recorded_cases = payload.get("cases")
    score_distribution = payload.get("reranker_score_distribution")
    if not isinstance(recorded_cases, list) or not isinstance(
        score_distribution,
        dict,
    ):
        raise ValueError("Prepared cache payload is incomplete.")
    if [item.get("case_id") for item in recorded_cases] != [
        case["id"] for case in cases
    ]:
        raise ValueError("Prepared cache case identity/order does not match.")

    chunks_by_index = {chunk.index: chunk for chunk in chunks}
    prepared: list[PreparedCase] = []
    for case, item in zip(cases, recorded_cases, strict=True):
        if not isinstance(item, dict):
            raise ValueError("Prepared cache case record must be an object.")
        keyword_payloads = item.get("keyword_hits")
        dense_payloads = item.get("dense_hits")
        score_payload = item.get("reranker_scores")
        if (
            not isinstance(keyword_payloads, list)
            or not isinstance(dense_payloads, list)
            or not isinstance(score_payload, dict)
        ):
            raise ValueError("Prepared cache contains an invalid case record.")
        scores = {int(index): float(score) for index, score in score_payload.items()}
        if not all(math.isfinite(score) for score in scores.values()):
            raise ValueError("Prepared cache contains a non-finite reranker score.")
        prepared.append(
            PreparedCase(
                case=case,
                keyword_hits=_restore_hits(keyword_payloads, chunks_by_index),
                dense_hits=_restore_hits(dense_payloads, chunks_by_index),
                reranker_scores=scores,
                keyword_latency_ms=float(item["keyword_latency_ms"]),
                dense_latency_ms=float(item["dense_latency_ms"]),
            )
        )
    return prepared, {
        key: float(score_distribution[key])
        for key in ("min", "max", "p50", "p95")
    }


def _write_prepared_cache(
    prepared_cases: Sequence[PreparedCase],
    score_distribution: Mapping[str, float],
    path: Path = PREPARED_CACHE_PATH,
) -> None:
    """Atomically persist sanitized scores with owner-only permissions."""
    if path.exists() and path.is_symlink():
        raise ValueError("Prepared cache must not be a symbolic link.")
    payload = {
        "schema_version": _PREPARED_CACHE_SCHEMA,
        "identity": _prepared_cache_identity(),
        "reranker_score_distribution": dict(score_distribution),
        "cases": [
            {
                "case_id": prepared.case["id"],
                "keyword_hits": [
                    _hit_payload(hit) for hit in prepared.keyword_hits
                ],
                "dense_hits": [
                    _hit_payload(hit) for hit in prepared.dense_hits
                ],
                "reranker_scores": {
                    str(index): score
                    for index, score in prepared.reranker_scores.items()
                },
                "keyword_latency_ms": prepared.keyword_latency_ms,
                "dense_latency_ms": prepared.dense_latency_ms,
            }
            for prepared in prepared_cases
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def prepare_cases(
    cases: Sequence[BaselineCase],
    chunks: list[Chunk],
) -> tuple[list[PreparedCase], dict[str, float], bool]:
    """Perform one embedding and one local scoring pass per evaluation case."""
    cached = _load_prepared_cache(cases, chunks)
    if cached is not None:
        prepared, score_distribution = cached
        print(f"Prepared score cache hit: {PREPARED_CACHE_PATH}")
        return prepared, score_distribution, True

    max_candidate_k = max(CANDIDATE_K_GRID)
    keyword = BM25Retriever(chunks)
    # A permissive gate records scores once; profiles apply their own gate
    # locally. Only top max(candidate_k) can enter any configured pipeline.
    dense = OpenAIEmbeddingRetriever(chunks, min_cosine=-1.0)
    reranker = LocalCrossEncoderReranker(
        batch_size=RERANKER_BATCH_SIZE,
        timeout_seconds=60,
        max_candidates=len(chunks),
        max_length=RERANKER_MAX_LENGTH,
        local_files_only=True,
    )
    reranker.warmup()

    prepared: list[PreparedCase] = []
    all_reranker_scores: list[float] = []
    for position, case in enumerate(cases, start=1):
        query = case["query"]

        started = time.perf_counter()
        keyword_hits = keyword.search(query, top_k=max_candidate_k)
        keyword_latency_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        dense_hits = dense.search(query, top_k=max_candidate_k)
        dense_latency_ms = (time.perf_counter() - started) * 1000
        if dense.query_failure_count:
            raise RuntimeError(
                "An embedding query failed; refusing to tune on degraded results."
            )

        possible = _possible_fusion_candidates(
            query,
            keyword_hits,
            dense_hits,
        )
        scored = reranker.rerank(query, possible, top_k=len(possible))
        score_by_index = {
            hit.chunk.index: cast(float, hit.reranker_score)
            for hit in scored
        }
        if len(score_by_index) != len(possible):
            raise RuntimeError("Local reranker did not score every candidate.")
        all_reranker_scores.extend(score_by_index.values())
        prepared.append(
            PreparedCase(
                case=case,
                keyword_hits=tuple(keyword_hits),
                dense_hits=tuple(dense_hits),
                reranker_scores=score_by_index,
                keyword_latency_ms=keyword_latency_ms,
                dense_latency_ms=dense_latency_ms,
            )
        )
        print(
            f"Prepared {position:02d}/{len(cases)} "
            f"case={case['id']} candidates={len(possible)}"
        )

    score_distribution = {
        "min": min(all_reranker_scores),
        "max": max(all_reranker_scores),
        "p50": _percentile(all_reranker_scores, 0.50),
        "p95": _percentile(all_reranker_scores, 0.95),
    }
    _write_prepared_cache(prepared, score_distribution)
    return prepared, score_distribution, False


def _profile_results(
    profile: TuneProfile,
    prepared_cases: Sequence[PreparedCase],
) -> tuple[list[CaseResult], list[int], list[int], list[int]]:
    context_builder = ContextBuilder(
        max_context_chars=profile.max_context_chars,
        duplicate_threshold=CONTEXT_DUPLICATE_THRESHOLD,
        min_body_chars=CONTEXT_MIN_BODY_CHARS,
    )
    results: list[CaseResult] = []
    context_sizes: list[int] = []
    citation_checks: list[int] = []
    truncation_checks: list[int] = []

    for prepared in prepared_cases:
        query = prepared.case["query"]
        candidates = _fuse_candidates(
            query,
            prepared.keyword_hits,
            prepared.dense_hits,
            candidate_k=profile.candidate_k,
            min_cosine=profile.min_cosine,
        )
        if profile.reranker_enabled:
            hits = _rerank_from_scores(
                candidates,
                prepared.reranker_scores,
                top_k=profile.top_k,
                min_score=profile.reranker_min_score,
            )
        else:
            hits = candidates[: profile.top_k]

        context = context_builder.build(hits)
        snippets_valid = all(
            snippet.startswith(f"[{hit.title}]\n")
            for hit, snippet in zip(context.hits, context.snippets, strict=True)
        )
        budget_valid = context.total_chars <= profile.max_context_chars
        citation_checks.append(int(snippets_valid and budget_valid))
        original_text_by_index = {
            hit.chunk.index: hit.text for hit in hits
        }
        truncation_checks.append(
            int(
                any(
                    hit.text != original_text_by_index[hit.chunk.index]
                    for hit in context.hits
                )
            )
        )
        context_sizes.append(context.total_chars)
        results.append(
            CaseResult(
                case_id=prepared.case["id"],
                category=prepared.case["category"],
                expected=tuple(prepared.case["expected_titles"]),
                retrieved=tuple(hit.title for hit in context.hits),
                latency_ms=0.0,
            )
        )
    return results, context_sizes, citation_checks, truncation_checks


def _gate_failures(
    metrics: Mapping[str, float],
    category_metrics: Mapping[str, Mapping[str, float]],
    baseline_metrics: Mapping[str, float],
    baseline_categories: Mapping[str, Mapping[str, float]],
    *,
    citation_validity: float,
) -> tuple[str, ...]:
    failures: list[str] = []
    for metric in ("recall_at_k", "mrr", "not_found_discipline"):
        if metrics[metric] + _EPSILON < baseline_metrics[metric]:
            failures.append(f"{metric}_below_baseline")
    for category in ("english_answerable", "mixed_answerable", "multi_section"):
        if (
            category_metrics[category]["recall"] + _EPSILON
            < baseline_categories[category]["recall"]
        ):
            failures.append(f"{category}_recall_below_baseline")
    if (
        category_metrics["thai_answerable"]["recall"]
        <= baseline_categories["thai_answerable"]["recall"] + _EPSILON
    ):
        failures.append("thai_recall_not_improved")
    if citation_validity < 1.0:
        failures.append("citation_validity_below_100_percent")
    return tuple(failures)


def evaluate_profile(
    profile: TuneProfile,
    prepared_cases: Sequence[PreparedCase],
    baseline_metrics: Mapping[str, float],
    baseline_categories: Mapping[str, Mapping[str, float]],
) -> ProfileEvaluation:
    results, context_sizes, citation_checks, truncation_checks = _profile_results(
        profile,
        prepared_cases,
    )
    metrics = _mode_metrics(results)
    categories = _category_metrics(results)
    citation_validity = _mean(citation_checks)
    failures = _gate_failures(
        metrics,
        categories,
        baseline_metrics,
        baseline_categories,
        citation_validity=citation_validity,
    )
    thai_recall = categories["thai_answerable"]["recall"]
    quality_score = (
        0.30 * metrics["recall_at_k"]
        + 0.25 * metrics["mrr"]
        + 0.30 * metrics["not_found_discipline"]
        + 0.15 * thai_recall
    )
    return ProfileEvaluation(
        profile=profile,
        metrics=metrics,
        category_metrics=categories,
        quality_score=quality_score,
        passed_hard_gates=not failures,
        passed_safety_target=(
            metrics["not_found_discipline"] + _EPSILON >= _SAFETY_TARGET
        ),
        gate_failures=failures,
        context_avg_chars=_mean(context_sizes),
        context_p95_chars=_percentile(context_sizes, 0.95),
        context_truncation_rate=_mean(truncation_checks),
        citation_validity=citation_validity,
        average_final_hits=_mean(len(result.retrieved) for result in results),
        cases=tuple(results),
    )


def tuning_profiles() -> list[TuneProfile]:
    return [
        TuneProfile(
            candidate_k=candidate_k,
            top_k=top_k,
            min_cosine=min_cosine,
            reranker_min_score=reranker_min_score,
            max_context_chars=max_context_chars,
        )
        for candidate_k in CANDIDATE_K_GRID
        for top_k in TOP_K_GRID
        for min_cosine in MIN_COSINE_GRID
        for reranker_min_score in RERANKER_MIN_SCORE_GRID
        for max_context_chars in MAX_CONTEXT_CHARS_GRID
    ]


def select_profile(
    evaluations: Sequence[ProfileEvaluation],
) -> ProfileEvaluation:
    eligible = [result for result in evaluations if result.passed_hard_gates]
    if not eligible:
        raise RuntimeError("No tuning profile passed the non-regression gates.")
    # Quality and negative discipline lead the decision. Exact ties prefer a
    # smaller candidate pool/context budget to reduce latency and memory.
    return max(
        eligible,
        key=lambda result: (
            result.passed_safety_target,
            result.quality_score,
            result.metrics["not_found_discipline"],
            result.metrics["recall_at_k"],
            result.metrics["mrr"],
            -result.context_truncation_rate,
            -result.profile.candidate_k,
            -result.profile.top_k,
            -result.profile.max_context_chars,
            result.profile.min_cosine,
            result.profile.reranker_min_score or -math.inf,
        ),
    )


def select_balanced_profile(
    evaluations: Sequence[ProfileEvaluation],
    quality_winner: ProfileEvaluation,
) -> ProfileEvaluation:
    """Prefer the smallest pool retaining most measured quality and safety."""
    minimum_quality = (
        quality_winner.quality_score * _BALANCED_QUALITY_RETENTION
    )
    eligible = [
        result
        for result in evaluations
        if result.passed_hard_gates
        and result.quality_score + _EPSILON >= minimum_quality
        and (
            result.metrics["not_found_discipline"] + _EPSILON
            >= quality_winner.metrics["not_found_discipline"]
        )
        and result.context_truncation_rate == 0.0
    ]
    if not eligible:
        return quality_winner
    return max(
        eligible,
        key=lambda result: (
            -result.profile.candidate_k,
            result.quality_score,
            result.metrics["recall_at_k"],
            result.metrics["mrr"],
            -result.profile.top_k,
            -result.profile.max_context_chars,
            result.profile.min_cosine,
        ),
    )


def _benchmark_selected(
    selected: ProfileEvaluation,
    prepared_cases: Sequence[PreparedCase],
) -> dict[str, float]:
    """Measure selected local work and combine it with captured API latency."""
    profile = selected.profile
    reranker = LocalCrossEncoderReranker(
        batch_size=RERANKER_BATCH_SIZE,
        timeout_seconds=60,
        max_candidates=profile.candidate_k,
        max_length=RERANKER_MAX_LENGTH,
        local_files_only=True,
    )
    reranker.warmup()
    context_builder = ContextBuilder(max_context_chars=profile.max_context_chars)
    total_latencies: list[float] = []
    reranker_latencies: list[float] = []

    for prepared in prepared_cases:
        candidates = _fuse_candidates(
            prepared.case["query"],
            prepared.keyword_hits,
            prepared.dense_hits,
            candidate_k=profile.candidate_k,
            min_cosine=profile.min_cosine,
        )
        started = time.perf_counter()
        reranked = reranker.rerank(
            prepared.case["query"],
            candidates,
            top_k=profile.top_k,
        )
        if profile.reranker_min_score is not None:
            reranked = [
                hit
                for hit in reranked
                if cast(float, hit.reranker_score)
                >= profile.reranker_min_score
            ]
        context_builder.build(reranked)
        local_ms = (time.perf_counter() - started) * 1000
        reranker_latencies.append(local_ms)
        total_latencies.append(
            prepared.keyword_latency_ms
            + prepared.dense_latency_ms
            + local_ms
        )

    return {
        "estimated_online_avg_ms": _mean(total_latencies),
        "estimated_online_p50_ms": _percentile(total_latencies, 0.50),
        "estimated_online_p95_ms": _percentile(total_latencies, 0.95),
        "local_rerank_context_avg_ms": _mean(reranker_latencies),
        "local_rerank_context_p95_ms": _percentile(
            reranker_latencies,
            0.95,
        ),
        "embedding_avg_ms": _mean(
            case.dense_latency_ms for case in prepared_cases
        ),
        "embedding_p95_ms": _percentile(
            [case.dense_latency_ms for case in prepared_cases],
            0.95,
        ),
    }


def _profile_payload(
    result: ProfileEvaluation,
    *,
    include_cases: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile_id": result.profile.profile_id,
        "config": asdict(result.profile),
        "metrics": dict(result.metrics),
        "category_metrics": {
            category: dict(metrics)
            for category, metrics in result.category_metrics.items()
        },
        "quality_score": result.quality_score,
        "passed_hard_gates": result.passed_hard_gates,
        "passed_safety_target": result.passed_safety_target,
        "gate_failures": list(result.gate_failures),
        "context_avg_chars": result.context_avg_chars,
        "context_p95_chars": result.context_p95_chars,
        "context_truncation_rate": result.context_truncation_rate,
        "citation_validity": result.citation_validity,
        "average_final_hits": result.average_final_hits,
    }
    if include_cases:
        payload["cases"] = [_case_payload(case) for case in result.cases]
    return payload


def _delta(
    after: Mapping[str, float],
    before: Mapping[str, float],
    metric: str,
) -> float:
    return after[metric] - before[metric]


def _percent(value: float) -> str:
    return f"{value:.1%}"


def _comparison_table(
    baseline_metrics: Mapping[str, float],
    step2_defaults: ProfileEvaluation,
    selected: ProfileEvaluation,
    without_reranker: ProfileEvaluation,
) -> str:
    rows = [
        ("Step 1 baseline", baseline_metrics, None),
        ("Step 2 defaults", step2_defaults.metrics, baseline_metrics),
        ("Step 3 selected", selected.metrics, baseline_metrics),
        ("Selected without reranker", without_reranker.metrics, baseline_metrics),
    ]
    output = [
        "| configuration | recall@k | MRR | not-found discipline "
        "| Δ recall | Δ MRR | Δ not-found |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, metrics, before in rows:
        if before is None:
            deltas = ("—", "—", "—")
        else:
            deltas = (
                f"{_delta(metrics, before, 'recall_at_k'):+.1%}",
                f"{_delta(metrics, before, 'mrr'):+.3f}",
                f"{_delta(metrics, before, 'not_found_discipline'):+.1%}",
            )
        output.append(
            f"| {label} | {_percent(metrics['recall_at_k'])} | "
            f"{metrics['mrr']:.3f} | "
            f"{_percent(metrics['not_found_discipline'])} | "
            f"{deltas[0]} | {deltas[1]} | {deltas[2]} |"
        )
    return "\n".join(output)


def _category_comparison_table(
    baseline_categories: Mapping[str, Mapping[str, float]],
    selected: ProfileEvaluation,
) -> str:
    output = [
        "| category | metric | baseline | selected | delta |",
        "|---|---|---:|---:|---:|",
    ]
    for category, baseline in baseline_categories.items():
        after = selected.category_metrics[category]
        metric_rows = (
            (("not-found discipline", "not_found_discipline"),)
            if category == "negative"
            else (("recall", "recall"), ("MRR", "mrr"))
        )
        for label, metric in metric_rows:
            before_value = baseline[metric]
            after_value = after[metric]
            if metric == "mrr":
                before_display = f"{before_value:.3f}"
                after_display = f"{after_value:.3f}"
            else:
                before_display = _percent(before_value)
                after_display = _percent(after_value)
            output.append(
                f"| {category} | {label} | {before_display} | "
                f"{after_display} | {after_value - before_value:+.3f} |"
            )
    return "\n".join(output)


def _leaderboard(evaluations: Sequence[ProfileEvaluation], limit: int = 10) -> str:
    ranked = sorted(
        evaluations,
        key=lambda result: (
            result.passed_hard_gates,
            result.passed_safety_target,
            result.quality_score,
        ),
        reverse=True,
    )[:limit]
    output = [
        "| profile | score | recall | MRR | not-found | Thai recall | gates |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in ranked:
        output.append(
            f"| `{result.profile.profile_id}` | {result.quality_score:.3f} | "
            f"{_percent(result.metrics['recall_at_k'])} | "
            f"{result.metrics['mrr']:.3f} | "
            f"{_percent(result.metrics['not_found_discipline'])} | "
            f"{_percent(result.category_metrics['thai_answerable']['recall'])} | "
            f"{'PASS' if result.passed_hard_gates else 'FAIL'} |"
        )
    return "\n".join(output)


def _build_report(
    *,
    generated_at: str,
    checks: Sequence[object],
    baseline_sha256: str,
    baseline_metrics: Mapping[str, float],
    baseline_categories: Mapping[str, Mapping[str, float]],
    step2_defaults: ProfileEvaluation,
    selected: ProfileEvaluation,
    quality_winner: ProfileEvaluation,
    without_reranker: ProfileEvaluation,
    evaluations: Sequence[ProfileEvaluation],
    latency: Mapping[str, float],
    score_distribution: Mapping[str, float],
    prepared_cache_hit: bool,
) -> str:
    profile = selected.profile
    reranker_delta = (
        selected.quality_score - without_reranker.quality_score
    )
    return "\n".join(
        [
            "# Track A — Step 3 Measure & Tune",
            "",
            f"- Generated at: {generated_at}",
            f"- Dataset: `{DATASET_PATH.relative_to(PROJECT_ROOT)}` "
            f"({len(selected.cases)} cases)",
            f"- Frozen baseline SHA-256: `{baseline_sha256}`",
            "- External data boundary: evaluation query strings only; no "
            "knowledge-base body or snippet is sent.",
            f"- Prepared score cache: {'hit' if prepared_cache_hit else 'created'} "
            f"({len(selected.cases)} query strings created the cache; "
            f"{0 if prepared_cache_hit else len(selected.cases)} sent in this run).",
            "- Answer-level evaluation: not run.",
            "",
            "## Verification gates",
            "",
            _checks_table(cast(Sequence, checks)),
            "",
            "## Before / after",
            "",
            _comparison_table(
                baseline_metrics,
                step2_defaults,
                selected,
                without_reranker,
            ),
            "",
            "## Category evidence",
            "",
            _category_comparison_table(baseline_categories, selected),
            "",
            "Category recall is a blocking non-regression gate. Category MRR "
            "movement remains visible here and is accepted only when the overall "
            "MRR, recall, Thai recall, and not-found gates pass.",
            "",
            "## Selected configuration",
            "",
            f"- Quality-max profile: `{quality_winner.profile.profile_id}` "
            f"(score={quality_winner.quality_score:.3f})",
            f"- Balanced runtime profile: `{profile.profile_id}` "
            f"(score={selected.quality_score:.3f}, "
            f"{selected.quality_score / quality_winner.quality_score:.1%} "
            "quality retained)",
            f"- `CANDIDATE_K={profile.candidate_k}`",
            f"- `TOP_K={profile.top_k}`",
            f"- `HYBRID_MIN_COSINE={profile.min_cosine:.2f}`",
            f"- `RERANKER_MIN_SCORE={profile.reranker_min_score}`",
            f"- `RERANKER_BATCH_SIZE={RERANKER_BATCH_SIZE}`",
            f"- `RERANKER_TIMEOUT_SECONDS={RERANKER_TIMEOUT_SECONDS:g}`",
            f"- `MAX_CONTEXT_CHARS={profile.max_context_chars}`",
            f"- Citation validity: {_percent(selected.citation_validity)}",
            f"- Context truncation rate: "
            f"{_percent(selected.context_truncation_rate)}",
            f"- Thai recall: "
            f"{_percent(selected.category_metrics['thai_answerable']['recall'])}",
            f"- Context p95: {selected.context_p95_chars:.0f} characters",
            "",
            "## Latency",
            "",
            "- The online estimate adds captured query-embedding latency to a "
            "second local reranker/context benchmark for the selected profile.",
            f"- Estimated online average: "
            f"{latency['estimated_online_avg_ms']:.1f} ms",
            f"- Estimated online p95: "
            f"{latency['estimated_online_p95_ms']:.1f} ms",
            f"- Query embedding p95: {latency['embedding_p95_ms']:.1f} ms",
            f"- Local reranker + context p95: "
            f"{latency['local_rerank_context_p95_ms']:.1f} ms",
            "",
            "## Reranker decision gate",
            "",
            f"- Quality-score delta versus the same profile without reranking: "
            f"{reranker_delta:+.3f}",
            f"- Reranker score range: {score_distribution['min']:.4f}–"
            f"{score_distribution['max']:.4f} "
            f"(p50={score_distribution['p50']:.4f}, "
            f"p95={score_distribution['p95']:.4f})",
            "- Decision: keep the reranker enabled when the selected profile "
            "passes all hard gates and improves the composite score; otherwise "
            "retain it as optional.",
            "",
            "## Top profiles",
            "",
            _leaderboard(evaluations),
            "",
            "## Security and reproducibility",
            "",
            "- The Step 1 baseline is read-only and was not overwritten.",
            "- Dataset and corpus SHA-256 values must match the frozen baseline.",
            "- Query embeddings are requested once per case; the tuning grid "
            "replays captured scores locally.",
            "- Local model loading is cache-only and remote model code is disabled.",
            "- Reports exclude raw queries, prompts, API keys, environment "
            "variables, and document bodies.",
            "",
        ]
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-query-embeddings",
        action="store_true",
        help=(
            "Confirm that the 40 versioned query strings may be sent to the "
            "configured OpenAI Embeddings endpoint."
        ),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help="Frozen Step 1 JSON artifact.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=RESULTS_JSON_PATH,
    )
    parser.add_argument(
        "--output-markdown",
        type=Path,
        default=RESULTS_MARKDOWN_PATH,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.allow_query_embeddings:
        raise SystemExit(
            "Refusing external embedding requests without "
            "--allow-query-embeddings."
        )

    cases = load_baseline_cases()
    chunks = load_chunks()
    validate_baseline_cases(
        cases,
        valid_titles={chunk.title for chunk in chunks},
    )
    baseline_payload, baseline_metrics, baseline_case_payloads = (
        _load_frozen_baseline(args.baseline)
    )
    baseline_categories = _baseline_category_metrics(
        baseline_case_payloads
    )

    # All deterministic correctness gates run before any external request.
    checks = run_local_checks()
    prepared_cases, score_distribution, prepared_cache_hit = prepare_cases(
        cases,
        chunks,
    )

    evaluations = [
        evaluate_profile(
            profile,
            prepared_cases,
            baseline_metrics,
            baseline_categories,
        )
        for profile in tuning_profiles()
    ]
    quality_winner = select_profile(evaluations)
    selected = select_balanced_profile(evaluations, quality_winner)
    # Preserve the exact Step 2 defaults as the intermediate comparison even
    # after Step 3 promotes its selected values into runtime configuration.
    step2_profile = TuneProfile(
        candidate_k=24,
        top_k=4,
        min_cosine=0.38,
        reranker_min_score=None,
        max_context_chars=12_000,
    )
    step2_defaults = evaluate_profile(
        step2_profile,
        prepared_cases,
        baseline_metrics,
        baseline_categories,
    )
    without_reranker = evaluate_profile(
        TuneProfile(
            candidate_k=selected.profile.candidate_k,
            top_k=selected.profile.top_k,
            min_cosine=selected.profile.min_cosine,
            reranker_min_score=None,
            max_context_chars=selected.profile.max_context_chars,
            reranker_enabled=False,
        ),
        prepared_cases,
        baseline_metrics,
        baseline_categories,
    )
    latency = _benchmark_selected(selected, prepared_cases)

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    baseline_sha256 = file_sha256(args.baseline)
    payload = {
        "schema_version": _RESULT_SCHEMA,
        "generated_at": generated_at,
        "baseline": {
            "file": args.baseline.name,
            "sha256": baseline_sha256,
            "schema_version": baseline_payload["schema_version"],
            "metrics": dict(baseline_metrics),
            "category_metrics": baseline_categories,
        },
        "dataset": {
            "file": DATASET_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": file_sha256(DATASET_PATH),
            "case_count": len(cases),
        },
        "corpus": corpus_snapshot(),
        "environment": environment_snapshot(),
        "models": {
            "embedding_model": EMBEDDING_MODEL,
            "reranker_model": RERANKER_MODEL,
            "reranker_revision": RERANKER_MODEL_REVISION,
            "reranker_batch_size": RERANKER_BATCH_SIZE,
            "reranker_timeout_seconds": RERANKER_TIMEOUT_SECONDS,
        },
        "external_data_boundary": {
            "query_strings_sent_to_embedding_provider": (
                0 if prepared_cache_hit else len(cases)
            ),
            "query_strings_used_to_create_prepared_cache": len(cases),
            "knowledge_base_bodies_sent": 0,
            "answer_evaluation_run": False,
            "prepared_cache_hit": prepared_cache_hit,
        },
        "grid": {
            "candidate_k": list(CANDIDATE_K_GRID),
            "top_k": list(TOP_K_GRID),
            "min_cosine": list(MIN_COSINE_GRID),
            "reranker_min_score": list(RERANKER_MIN_SCORE_GRID),
            "max_context_chars": list(MAX_CONTEXT_CHARS_GRID),
            "profile_count": len(evaluations),
        },
        "checks": [
            {**asdict(check), "passed": check.passed}
            for check in checks
        ],
        "reranker_score_distribution": score_distribution,
        "step2_defaults": _profile_payload(
            step2_defaults,
            include_cases=True,
        ),
        "quality_winner": _profile_payload(
            quality_winner,
            include_cases=True,
        ),
        "selected": _profile_payload(selected, include_cases=True),
        "selected_without_reranker": _profile_payload(
            without_reranker,
            include_cases=True,
        ),
        "latency": latency,
        "leaderboard": [
            _profile_payload(result, include_cases=False)
            for result in sorted(
                evaluations,
                key=lambda item: (
                    item.passed_hard_gates,
                    item.passed_safety_target,
                    item.quality_score,
                ),
                reverse=True,
            )[:20]
        ],
    }
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(
        _build_report(
            generated_at=generated_at,
            checks=checks,
            baseline_sha256=baseline_sha256,
            baseline_metrics=baseline_metrics,
            baseline_categories=baseline_categories,
            step2_defaults=step2_defaults,
            selected=selected,
            quality_winner=quality_winner,
            without_reranker=without_reranker,
            evaluations=evaluations,
            latency=latency,
            score_distribution=score_distribution,
            prepared_cache_hit=prepared_cache_hit,
        ),
        encoding="utf-8",
    )

    print(
        _comparison_table(
            baseline_metrics,
            step2_defaults,
            selected,
            without_reranker,
        )
    )
    print(f"\nSelected: {selected.profile.profile_id}")
    print(f"Written to {args.output_markdown}")
    print(f"Written to {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

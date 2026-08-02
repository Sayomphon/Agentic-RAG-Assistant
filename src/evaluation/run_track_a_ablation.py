"""Create the Track A R3 A0-A7 component-ablation evidence.

The runner replays the existing versioned dense/Primary score cache and builds
an independently versioned Secondary score cache. Published output contains
case IDs and section titles only; raw queries and section bodies never leave
local memory.

Usage:
    python -m src.evaluation.run_track_a_ablation
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence, cast

from src.config import (
    CONTEXT_DUPLICATE_THRESHOLD,
    CONTEXT_MIN_BODY_CHARS,
    RERANKER_BATCH_SIZE,
    RERANKER_FALLBACK_CACHE_DIR,
    RERANKER_FALLBACK_MAX_LENGTH,
    RERANKER_FALLBACK_MIN_SCORE,
    RERANKER_FALLBACK_MODEL,
    RERANKER_FALLBACK_MODEL_REVISION,
)
from src.evaluation.baseline_dataset import (
    BaselineCase,
    load_baseline_cases,
    validate_baseline_cases,
)
from src.evaluation.run_baseline import _case_payload, _mode_metrics, run_local_checks
from src.evaluation.run_eval import CaseResult
from src.evaluation.run_measure_tune import (
    PREPARED_CACHE_PATH,
    PreparedCase,
    _category_metrics,
    _fuse_candidates,
    _load_prepared_cache,
    _possible_fusion_candidates,
    _rerank_from_scores,
    prepare_cases,
)
from src.evaluation.track_a_closure import verify_track_a_r0_freeze
from src.evaluation.track_a_r1 import verify_r1_artifact_provenance
from src.evaluation.track_a_r3 import (
    PROJECT_ROOT,
    R3ValidationError,
    evidence_identity,
    generated_at,
    load_json,
    mean,
    selected_profile,
    sha256_file,
    validate_published_artifact,
    verify_effective_profile,
    write_versioned_pair,
)
from src.retrievers.base import ScoredChunk, load_chunks
from src.retrievers.context import ContextBuilder
from src.retrievers.reranker import LocalCrossEncoderReranker

RESULTS_JSON_PATH = PROJECT_ROOT / "track_a_ablation_results_v2.json"
RESULTS_MARKDOWN_PATH = PROJECT_ROOT / "track_a_ablation_results_v2.md"
SECONDARY_CACHE_PATH = (
    PROJECT_ROOT / ".cache" / "track-a-r3-secondary-scores-v1.json"
)

_SCHEMA_VERSION = "track-a-r3-ablation-v2"
_SECONDARY_CACHE_SCHEMA = "track-a-r3-secondary-scores-v1"
_EPSILON = 1e-12
_TOP_K = 6


@dataclass(frozen=True)
class AblationProfile:
    """One explicit A0-A7 component configuration."""

    ablation_id: str
    label: str
    candidate_k: int
    top_k: int
    min_cosine: float
    reranker_role: str
    reranker_score_gate: float | None
    context_builder_enabled: bool
    max_context_chars: int | None
    failure_mode: str

    def __post_init__(self) -> None:
        if self.ablation_id not in {f"A{index}" for index in range(8)}:
            raise R3ValidationError("Ablation ID must be A0 through A7.")
        if self.candidate_k <= 0 or self.top_k <= 0:
            raise R3ValidationError("Candidate and final result counts must be positive.")
        if self.top_k > self.candidate_k:
            raise R3ValidationError("top_k cannot exceed candidate_k.")
        if not math.isfinite(self.min_cosine):
            raise R3ValidationError("min_cosine must be finite.")
        if self.reranker_role not in {"historical", "none", "primary", "secondary"}:
            raise R3ValidationError("Unsupported reranker role.")
        if self.failure_mode not in {"normal", "primary_failed", "both_failed"}:
            raise R3ValidationError("Unsupported failure mode.")
        if self.context_builder_enabled != (self.max_context_chars is not None):
            raise R3ValidationError("Context builder and budget must be enabled together.")

    @property
    def profile_id(self) -> str:
        """Stable ID containing every behavior-affecting profile field."""
        gate = (
            "off"
            if self.reranker_score_gate is None
            else f"{self.reranker_score_gate:.2f}"
        )
        context = (
            "off"
            if self.max_context_chars is None
            else str(self.max_context_chars)
        )
        return (
            f"{self.ablation_id}-c{self.candidate_k}-k{self.top_k}"
            f"-cos{self.min_cosine:.2f}-rr{self.reranker_role}"
            f"-gate{gate}-ctx{context}-failure{self.failure_mode}"
        )


@dataclass(frozen=True)
class AblationResult:
    """Sanitized retrieval result and gates for one component profile."""

    profile: AblationProfile
    metrics: Mapping[str, float]
    category_metrics: Mapping[str, Mapping[str, float]]
    average_final_hits: float
    context_truncation_rate: float | None
    context_header_validity: float | None
    context_budget_validity: float | None
    gate_failures: tuple[str, ...]
    cases: tuple[CaseResult, ...]

    @property
    def passed_hard_gates(self) -> bool:
        return not self.gate_failures


def ablation_profiles() -> tuple[AblationProfile, ...]:
    """Return the normative A0-A7 matrix in causal component order."""
    common = {
        "top_k": _TOP_K,
        "min_cosine": 0.20,
    }
    return (
        AblationProfile(
            "A0",
            "Pre-Track-A Hybrid",
            6,
            _TOP_K,
            0.38,
            "historical",
            None,
            False,
            None,
            "normal",
        ),
        AblationProfile(
            "A1",
            "Current Hybrid; reranker and answerability off",
            6,
            reranker_role="none",
            reranker_score_gate=None,
            context_builder_enabled=False,
            max_context_chars=None,
            failure_mode="normal",
            **common,
        ),
        AblationProfile(
            "A2",
            "Candidate expansion only",
            12,
            reranker_role="none",
            reranker_score_gate=None,
            context_builder_enabled=False,
            max_context_chars=None,
            failure_mode="normal",
            **common,
        ),
        AblationProfile(
            "A3",
            "Candidate expansion and Primary reranker",
            12,
            reranker_role="primary",
            reranker_score_gate=None,
            context_builder_enabled=False,
            max_context_chars=None,
            failure_mode="normal",
            **common,
        ),
        AblationProfile(
            "A4",
            "A3 with Primary score gate",
            12,
            reranker_role="primary",
            reranker_score_gate=0.01,
            context_builder_enabled=False,
            max_context_chars=None,
            failure_mode="normal",
            **common,
        ),
        AblationProfile(
            "A5",
            "Official full pipeline",
            12,
            reranker_role="primary",
            reranker_score_gate=0.01,
            context_builder_enabled=True,
            max_context_chars=6_000,
            failure_mode="normal",
            **common,
        ),
        AblationProfile(
            "A6",
            "Primary failure with Secondary model",
            12,
            reranker_role="secondary",
            reranker_score_gate=cast(float | None, RERANKER_FALLBACK_MIN_SCORE),
            context_builder_enabled=True,
            max_context_chars=6_000,
            failure_mode="primary_failed",
            **common,
        ),
        AblationProfile(
            "A7",
            "Both rerankers fail; fail closed",
            12,
            reranker_role="primary",
            reranker_score_gate=0.01,
            context_builder_enabled=True,
            max_context_chars=6_000,
            failure_mode="both_failed",
            **common,
        ),
    )


def _secondary_cache_identity() -> dict[str, object]:
    return {
        "evidence": evidence_identity(),
        "prepared_cache_sha256": sha256_file(PREPARED_CACHE_PATH),
        "model": RERANKER_FALLBACK_MODEL,
        "revision": RERANKER_FALLBACK_MODEL_REVISION,
        "max_length": RERANKER_FALLBACK_MAX_LENGTH,
    }


def _load_secondary_scores(
    cases: Sequence[BaselineCase],
    path: Path = SECONDARY_CACHE_PATH,
) -> dict[str, dict[int, float]] | None:
    """Load metadata-only Secondary scores when full identity matches."""
    if not path.exists():
        return None
    payload = load_json(path)
    if payload.get("schema_version") != _SECONDARY_CACHE_SCHEMA:
        return None
    if payload.get("identity") != _secondary_cache_identity():
        return None
    records = payload.get("cases")
    if not isinstance(records, list):
        raise R3ValidationError("Secondary score cache is incomplete.")
    if [record.get("case_id") for record in records if isinstance(record, dict)] != [
        case["id"] for case in cases
    ]:
        raise R3ValidationError("Secondary score cache case order differs.")
    output: dict[str, dict[int, float]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("scores"), dict):
            raise R3ValidationError("Secondary score cache case is invalid.")
        scores = {
            int(index): float(score)
            for index, score in cast(dict[str, object], record["scores"]).items()
        }
        if not scores or not all(math.isfinite(score) for score in scores.values()):
            raise R3ValidationError("Secondary score cache contains invalid scores.")
        output[cast(str, record["case_id"])] = scores
    return output


def _write_secondary_scores(
    scores: Mapping[str, Mapping[int, float]],
    cases: Sequence[BaselineCase],
    path: Path = SECONDARY_CACHE_PATH,
) -> None:
    """Atomically write a raw-content-free, owner-only Secondary score cache."""
    if path.exists() and path.is_symlink():
        raise R3ValidationError("Secondary score cache must not be a symlink.")
    payload = {
        "schema_version": _SECONDARY_CACHE_SCHEMA,
        "identity": _secondary_cache_identity(),
        "cases": [
            {
                "case_id": case["id"],
                "scores": {
                    str(index): value
                    for index, value in sorted(scores[case["id"]].items())
                },
            }
            for case in cases
        ],
    }
    validate_published_artifact(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def prepare_secondary_scores(
    prepared_cases: Sequence[PreparedCase],
) -> tuple[dict[str, dict[int, float]], bool]:
    """Score the same candidate union with the pinned Secondary snapshot."""
    cases = [prepared.case for prepared in prepared_cases]
    cached = _load_secondary_scores(cases)
    if cached is not None:
        return cached, True

    reranker = LocalCrossEncoderReranker(
        model_name=RERANKER_FALLBACK_MODEL,
        model_revision=RERANKER_FALLBACK_MODEL_REVISION,
        cache_dir=RERANKER_FALLBACK_CACHE_DIR,
        batch_size=RERANKER_BATCH_SIZE,
        timeout_seconds=60,
        max_candidates=54,
        max_length=RERANKER_FALLBACK_MAX_LENGTH,
        local_files_only=True,
    )
    reranker.warmup()
    output: dict[str, dict[int, float]] = {}
    for position, prepared in enumerate(prepared_cases, start=1):
        candidates = _possible_fusion_candidates(
            prepared.case["query"],
            prepared.keyword_hits,
            prepared.dense_hits,
        )
        ranked = reranker.rerank(
            prepared.case["query"],
            candidates,
            top_k=len(candidates),
        )
        scores = {
            hit.chunk.index: cast(float, hit.reranker_score)
            for hit in ranked
        }
        if len(scores) != len(candidates):
            raise R3ValidationError("Secondary model did not score every candidate.")
        output[prepared.case["id"]] = scores
        print(
            f"Secondary scores {position:02d}/{len(prepared_cases)} "
            f"case={prepared.case['id']} candidates={len(candidates)}"
        )
    _write_secondary_scores(output, cases)
    return output, False


def _gate_failures(
    metrics: Mapping[str, float],
    categories: Mapping[str, Mapping[str, float]],
    baseline_metrics: Mapping[str, float],
    baseline_categories: Mapping[str, Mapping[str, float]],
    *,
    header_validity: float | None,
    budget_validity: float | None,
) -> tuple[str, ...]:
    failures: list[str] = []
    for metric in ("recall_at_k", "mrr"):
        if metrics[metric] + _EPSILON < baseline_metrics[metric]:
            failures.append(f"{metric}_below_pre_track_a")
    for category in ("english_answerable", "mixed_answerable", "multi_section"):
        if (
            categories[category]["recall"] + _EPSILON
            < baseline_categories[category]["recall"]
        ):
            failures.append(f"{category}_recall_below_pre_track_a")
    if (
        categories["thai_answerable"]["recall"]
        <= baseline_categories["thai_answerable"]["recall"] + _EPSILON
    ):
        failures.append("thai_recall_not_improved")
    if header_validity is not None and header_validity < 1.0:
        failures.append("context_header_validity_below_100_percent")
    if budget_validity is not None and budget_validity < 1.0:
        failures.append("context_budget_validity_below_100_percent")
    return tuple(failures)


def evaluate_current_profile(
    profile: AblationProfile,
    prepared_cases: Sequence[PreparedCase],
    secondary_scores: Mapping[str, Mapping[int, float]],
    baseline_metrics: Mapping[str, float],
    baseline_categories: Mapping[str, Mapping[str, float]],
) -> AblationResult:
    """Replay one current-code profile without provider or model calls."""
    if profile.reranker_role == "historical":
        raise R3ValidationError("Historical A0 must be loaded from R1 evidence.")
    context_builder = (
        ContextBuilder(
            max_context_chars=cast(int, profile.max_context_chars),
            duplicate_threshold=CONTEXT_DUPLICATE_THRESHOLD,
            min_body_chars=CONTEXT_MIN_BODY_CHARS,
        )
        if profile.context_builder_enabled
        else None
    )
    results: list[CaseResult] = []
    context_sizes: list[float] = []
    header_checks: list[float] = []
    budget_checks: list[float] = []
    truncation_checks: list[float] = []

    for prepared in prepared_cases:
        candidates = _fuse_candidates(
            prepared.case["query"],
            prepared.keyword_hits,
            prepared.dense_hits,
            candidate_k=profile.candidate_k,
            min_cosine=profile.min_cosine,
        )
        if profile.failure_mode == "both_failed":
            hits: list[ScoredChunk] = []
        elif profile.reranker_role == "none":
            hits = candidates[: profile.top_k]
        else:
            scores = (
                prepared.reranker_scores
                if profile.reranker_role == "primary"
                else secondary_scores[prepared.case["id"]]
            )
            hits = _rerank_from_scores(
                candidates,
                scores,
                top_k=profile.top_k,
                min_score=profile.reranker_score_gate,
            )

        final_hits = hits
        if context_builder is not None:
            original_by_index = {hit.chunk.index: hit.text for hit in hits}
            context = context_builder.build(hits)
            final_hits = list(context.hits)
            context_sizes.append(float(context.total_chars))
            header_checks.append(
                float(
                    all(
                        snippet.startswith(f"[{hit.title}]\n")
                        for hit, snippet in zip(
                            context.hits,
                            context.snippets,
                            strict=True,
                        )
                    )
                )
            )
            budget_checks.append(
                float(context.total_chars <= cast(int, profile.max_context_chars))
            )
            truncation_checks.append(
                float(
                    any(
                        hit.text != original_by_index[hit.chunk.index]
                        for hit in context.hits
                    )
                )
            )
        results.append(
            CaseResult(
                case_id=prepared.case["id"],
                category=prepared.case["category"],
                expected=tuple(prepared.case["expected_titles"]),
                retrieved=tuple(hit.title for hit in final_hits),
                latency_ms=0.0,
            )
        )

    metrics = _mode_metrics(results)
    categories = _category_metrics(results)
    header_validity = mean(header_checks) if context_builder else None
    budget_validity = mean(budget_checks) if context_builder else None
    return AblationResult(
        profile=profile,
        metrics=metrics,
        category_metrics=categories,
        average_final_hits=mean([float(len(result.retrieved)) for result in results]),
        context_truncation_rate=(
            mean(truncation_checks) if context_builder else None
        ),
        context_header_validity=header_validity,
        context_budget_validity=budget_validity,
        gate_failures=_gate_failures(
            metrics,
            categories,
            baseline_metrics,
            baseline_categories,
            header_validity=header_validity,
            budget_validity=budget_validity,
        ),
        cases=tuple(results),
    )


def historical_a0(
    profile: AblationProfile,
    r1: Mapping[str, object],
) -> AblationResult:
    """Recompute A0 metrics from R1's true historical controlled cases."""
    profiles = cast(Mapping[str, object], r1["profiles"])
    controlled = cast(
        Mapping[str, object],
        profiles["pre_track_a_controlled_top_k_6"],
    )
    retrieval = cast(Mapping[str, object], controlled["retrieval"])
    hybrid = cast(Mapping[str, object], retrieval["hybrid"])
    raw_cases = cast(Sequence[Mapping[str, object]], hybrid["cases"])
    cases = tuple(
        CaseResult(
            case_id=cast(str, case["case_id"]),
            category=cast(str, case["category"]),
            expected=tuple(cast(Sequence[str], case["expected_titles"])),
            retrieved=tuple(cast(Sequence[str], case["retrieved_titles"])),
            latency_ms=float(case["latency_ms"]),
        )
        for case in raw_cases
    )
    recorded = cast(Mapping[str, float], hybrid["metrics"])
    computed = _mode_metrics(list(cases))
    if any(
        not math.isclose(computed[key], float(recorded[key]), abs_tol=1e-9)
        for key in computed
    ):
        raise R3ValidationError("R1 A0 metrics do not reproduce from case evidence.")
    categories = _category_metrics(list(cases))
    return AblationResult(
        profile=profile,
        metrics=computed,
        category_metrics=categories,
        average_final_hits=mean([float(len(case.retrieved)) for case in cases]),
        context_truncation_rate=None,
        context_header_validity=None,
        context_budget_validity=None,
        gate_failures=(),
        cases=cases,
    )


def _result_payload(result: AblationResult) -> dict[str, object]:
    return {
        "ablation_id": result.profile.ablation_id,
        "profile_id": result.profile.profile_id,
        "label": result.profile.label,
        "config": asdict(result.profile),
        "metrics": dict(result.metrics),
        "category_metrics": {
            category: dict(metrics)
            for category, metrics in result.category_metrics.items()
        },
        "average_final_hits": result.average_final_hits,
        "context": {
            "applicable": result.profile.context_builder_enabled,
            "truncation_rate": result.context_truncation_rate,
            "header_validity": result.context_header_validity,
            "budget_validity": result.context_budget_validity,
        },
        "passed_hard_gates": result.passed_hard_gates,
        "gate_failures": list(result.gate_failures),
        "cases": [_case_payload(case) for case in result.cases],
    }


def _delta(after: AblationResult, before: AblationResult, metric: str) -> float:
    return after.metrics[metric] - before.metrics[metric]


def _render_report(
    payload: Mapping[str, object],
    results: Sequence[AblationResult],
) -> str:
    a0 = results[0]
    a5 = results[5]
    table = [
        "| ID | Configuration | Recall@6 | MRR | Not-found | Thai recall | "
        "Avg hits | Gate |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        table.append(
            f"| {result.profile.ablation_id} | {result.profile.label} | "
            f"{result.metrics['recall_at_k']:.1%} | "
            f"{result.metrics['mrr']:.3f} | "
            f"{result.metrics['not_found_discipline']:.1%} | "
            f"{result.category_metrics['thai_answerable']['recall']:.1%} | "
            f"{result.average_final_hits:.2f} | "
            f"{'PASS' if result.passed_hard_gates else 'FAIL'} |"
        )
    component_rows = [
        "| Transition | Δ Recall | Δ MRR | Δ Not-found discipline |",
        "|---|---:|---:|---:|",
    ]
    for before, after in zip(results[1:5], results[2:6], strict=True):
        component_rows.append(
            f"| {before.profile.ablation_id} → {after.profile.ablation_id} | "
            f"{_delta(after, before, 'recall_at_k'):+.1%} | "
            f"{_delta(after, before, 'mrr'):+.3f} | "
            f"{_delta(after, before, 'not_found_discipline'):+.1%} |"
        )
    return "\n".join(
        [
            "# Track A R3 — Component Ablation",
            "",
            f"- Generated at: {payload['generated_at']}",
            "- Controlled comparison: 40 frozen cases, identical corpus, "
            "`TOP_K=6`, metric version `track-a-r3-metrics-v1`.",
            "- A0 source: R1 true Pre-Track-A Hybrid controlled evidence.",
            "- A1–A7 source: the same versioned prepared dense/score cache; "
            "Secondary scores use the same candidate union.",
            "- Published boundary: no raw query, answer, prompt, snippet, "
            "document body, credential, or provider error text.",
            "",
            "## Results",
            "",
            *table,
            "",
            "## Official A5 versus A0",
            "",
            f"- Recall@6: {a0.metrics['recall_at_k']:.1%} → "
            f"{a5.metrics['recall_at_k']:.1%} "
            f"({_delta(a5, a0, 'recall_at_k'):+.1%})",
            f"- MRR: {a0.metrics['mrr']:.3f} → {a5.metrics['mrr']:.3f} "
            f"({_delta(a5, a0, 'mrr'):+.3f})",
            f"- Not-found discipline: "
            f"{a0.metrics['not_found_discipline']:.1%} → "
            f"{a5.metrics['not_found_discipline']:.1%} "
            f"({_delta(a5, a0, 'not_found_discipline'):+.1%})",
            f"- Context header validity: "
            f"{cast(float, a5.context_header_validity):.1%}",
            f"- Context budget validity: "
            f"{cast(float, a5.context_budget_validity):.1%}",
            "",
            "## Component deltas",
            "",
            *component_rows,
            "",
            "A6 is a degradation-quality measurement, not an assertion that "
            "the Secondary model is quality-equivalent. A7 intentionally loses "
            "answerable recall and demonstrates deterministic fail-closed safety.",
        ]
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-query-embeddings",
        action="store_true",
        help="Allow rebuilding the prepared cache if the verified cache is absent.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    profile_document = selected_profile()
    verify_effective_profile(profile_document)
    verify_track_a_r0_freeze()
    r1 = verify_r1_artifact_provenance()
    checks = run_local_checks()

    cases = load_baseline_cases()
    chunks = load_chunks()
    validate_baseline_cases(cases, valid_titles={chunk.title for chunk in chunks})
    cached = _load_prepared_cache(cases, chunks)
    if cached is None:
        if not args.allow_query_embeddings:
            raise R3ValidationError(
                "Prepared cache unavailable; explicit query-embedding approval "
                "is required to rebuild it."
            )
        prepared_cases, _, prepared_cache_hit = prepare_cases(cases, chunks)
    else:
        prepared_cases, _ = cached
        prepared_cache_hit = True

    secondary_scores, secondary_cache_hit = prepare_secondary_scores(prepared_cases)
    profiles = ablation_profiles()
    a0 = historical_a0(profiles[0], r1)
    baseline_metrics = a0.metrics
    baseline_categories = a0.category_metrics
    results = [
        a0,
        *(
            evaluate_current_profile(
                profile,
                prepared_cases,
                secondary_scores,
                baseline_metrics,
                baseline_categories,
            )
            for profile in profiles[1:]
        ),
    ]
    if [result.profile.ablation_id for result in results] != [
        f"A{index}" for index in range(8)
    ]:
        raise R3ValidationError("Ablation result matrix is incomplete.")

    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": generated_at(),
        "identity": evidence_identity(),
        "baseline": {
            "source": "track_a_pre_upgrade_baseline_v2.json",
            "sha256": sha256_file(PROJECT_ROOT / "track_a_pre_upgrade_baseline_v2.json"),
            "profile": "pre_track_a_controlled_top_k_6",
            "same_top_k": True,
            "same_dataset": True,
            "same_corpus": True,
            "same_embedding_model": True,
            "same_metric_definitions": True,
        },
        "selected_profile": profile_document,
        "models": {
            "secondary_model": RERANKER_FALLBACK_MODEL,
            "secondary_revision": RERANKER_FALLBACK_MODEL_REVISION,
            "secondary_threshold": RERANKER_FALLBACK_MIN_SCORE,
        },
        "data_boundary": {
            "prepared_cache_hit": prepared_cache_hit,
            "secondary_score_cache_hit": secondary_cache_hit,
            "external_embedding_request_count": 0 if prepared_cache_hit else len(cases),
            "raw_queries_stored": False,
            "document_bodies_stored": False,
            "credentials_stored": False,
        },
        "checks": [
            {
                **asdict(check),
                "passed": check.passed,
            }
            for check in checks
        ],
        "profiles": [_result_payload(result) for result in results],
        "selected_ablation_id": "A5",
        "selected_passed_retrieval_gates": results[5].passed_hard_gates,
    }
    report = _render_report(payload, results)
    write_versioned_pair(
        payload,
        report,
        json_path=RESULTS_JSON_PATH,
        markdown_path=RESULTS_MARKDOWN_PATH,
    )
    print(report.split("## Results", 1)[1].split("## Official", 1)[0].strip())
    print(f"Written {RESULTS_JSON_PATH.name}")
    print(f"Written {RESULTS_MARKDOWN_PATH.name}")
    return 0 if results[5].passed_hard_gates else 1


if __name__ == "__main__":
    raise SystemExit(main())

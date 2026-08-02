"""Run the Track A R3 answer evaluation through the real LangGraph path.

The published artifacts are metadata-only. A local owner-only review bundle
contains the raw material required for explicit Human/Domain review.

Usage:
    python -m src.evaluation.run_track_a_answer_eval \
      --allow-answer-evaluation \
      --allow-knowledge-snippets
"""

from __future__ import annotations

import argparse
import re
from dataclasses import asdict, dataclass
from typing import Callable, Mapping, Sequence, cast

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agents import get_llm
from src.agents.reporter import NOT_FOUND_SENTENCE
from src.agents.router import ROUTE_KB
from src.evaluation.baseline_dataset import (
    BaselineCase,
    load_baseline_cases,
    validate_baseline_cases,
)
from src.evaluation.track_a_closure import verify_track_a_r0_freeze
from src.evaluation.track_a_r1 import verify_r1_artifact_provenance
from src.evaluation.track_a_r3 import (
    PROJECT_ROOT,
    R3ExecutionError,
    R3ProviderError,
    R3ValidationError,
    evidence_identity,
    generated_at,
    load_json,
    mean,
    selected_profile,
    sha256_file,
    verify_effective_profile,
    write_private_review_bundle,
    write_versioned_pair,
)
from src.graph import build_graph
from src.guardrails.answer import (
    cited_titles as _guardrail_cited_titles,
    context_titles as _guardrail_context_titles,
    factual_units as _guardrail_factual_units,
)
from src.retrievers.base import ScoredChunk, load_chunks

RESULTS_JSON_PATH = PROJECT_ROOT / "track_a_answer_results_v2.json"
RESULTS_MARKDOWN_PATH = PROJECT_ROOT / "track_a_answer_results_v2.md"
ABLATION_RESULTS_PATH = PROJECT_ROOT / "track_a_ablation_results_v2.json"
PRIVATE_REVIEW_PATH = (
    PROJECT_ROOT / ".cache" / "track-a-r3-human-review-v1.json"
)

_SCHEMA_VERSION = "track-a-r3-answer-evaluation-v2"
_REVIEW_SCHEMA_VERSION = "track-a-r3-human-review-v1"
_THAI_PATTERN = re.compile(r"[\u0e00-\u0e7f]")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_FAITHFULNESS_THRESHOLD = 0.95
_RELEVANCE_THRESHOLD = 4.0
_THAI_LANGUAGE_THRESHOLD = 0.90
_NEGATIVE_EXACT_THRESHOLD = 0.90


class AtomicClaimVerdict(BaseModel):
    """Content-free model verdict for one answer claim."""

    supported: bool = Field(
        description="True only when the supplied evidence explicitly supports it."
    )
    high_risk: bool = Field(
        description=(
            "True for unsupported claims involving money, eligibility, legal, "
            "security, privacy, health, disciplinary, or employment decisions."
        )
    )


class AnswerJudgeVerdict(BaseModel):
    """One structured judge response covering all model-based R3 axes."""

    claims: list[AtomicClaimVerdict]
    relevance: float = Field(ge=1.0, le=5.0)
    completeness: float = Field(ge=1.0, le=5.0)
    language_appropriate: bool
    specific_data_discipline: bool


_JUDGE_PROMPT = """\
You are a strict evaluator for an enterprise retrieval-augmented answer.
Use only QUESTION, EVIDENCE, and FINAL RESPONSE supplied by the caller.

1. Split the response into atomic factual claims. Return only supported and
   high_risk booleans for each claim; do not repeat any claim text.
2. supported is true only when EVIDENCE explicitly states the claim.
3. high_risk is true only when an unsupported claim could affect money,
   eligibility, legal/security/privacy/health, discipline, or employment.
4. Score relevance and completeness from 1 to 5 using the available evidence.
5. language_appropriate is true when the response matches the question's
   language and is readable.
6. specific_data_discipline is false if the response invents requested data,
   converts adjacent policy text into the requested fact, or uses outside
   knowledge.

Do not use a golden answer or outside knowledge.
"""


@dataclass(frozen=True)
class DeterministicVerdict:
    """Deterministic final-answer validators for one case."""

    route_correct: bool
    expected_evidence_retrieved: bool
    no_not_found_after_expected_evidence: bool
    negative_exact_not_found: bool | None
    citation_valid: bool
    invalid_citations: tuple[str, ...]
    citation_coverage: float
    factual_unit_count: int
    cited_factual_unit_count: int
    utf8_schema_valid: bool
    thai_script_present: bool | None


@dataclass(frozen=True)
class CaseEvaluation:
    """Sanitized public case outcome."""

    case_id: str
    category: str
    language: str
    route: str
    search_attempt_count: int
    expected_titles: tuple[str, ...]
    handed_context_titles: tuple[str, ...]
    cited_titles: tuple[str, ...]
    deterministic: DeterministicVerdict
    judge: AnswerJudgeVerdict | None
    judge_failure_reasons: tuple[str, ...]


def context_titles(snippets: Sequence[str]) -> tuple[str, ...]:
    """Extract exact context headers and reject malformed snippet framing."""
    try:
        return _guardrail_context_titles(snippets)
    except ValueError:
        raise R3ValidationError(
            "Generator context contains an invalid header."
        ) from None


def cited_titles(response: str) -> tuple[str, ...]:
    """Return unique citations in their first-seen order."""
    return _guardrail_cited_titles(response)


def factual_units(response: str) -> tuple[tuple[str, bool], ...]:
    """Split response text into auditable units and mark citation coverage.

    Markdown headings and the deterministic not-found response are not factual
    units. A citation at the end of one sentence does not cover a preceding
    uncited sentence on the same line.
    """
    return _guardrail_factual_units(response)


def validate_response(
    *,
    case: BaselineCase,
    state: Mapping[str, object],
) -> DeterministicVerdict:
    """Apply every deterministic R3 answer validator."""
    response = state.get("report")
    if not isinstance(response, str):
        raise R3ValidationError("Pipeline response must be a string.")
    snippets = state.get("snippets")
    hits = state.get("hits")
    if not isinstance(snippets, list) or any(
        not isinstance(snippet, str) for snippet in snippets
    ):
        raise R3ValidationError("Pipeline snippets must be a string list.")
    if hits is None:
        hits = []
    if not isinstance(hits, list) or any(
        not isinstance(hit, ScoredChunk) for hit in hits
    ):
        raise R3ValidationError("Pipeline hits must be scored chunks.")

    available = context_titles(cast(list[str], snippets))
    citations = cited_titles(response)
    invalid = tuple(sorted(set(citations) - set(available)))
    expected = set(case["expected_titles"])
    retrieved_expected = bool(expected & set(available))
    units = factual_units(response)
    cited_count = sum(has_citation for _, has_citation in units)
    try:
        response.encode("utf-8", errors="strict")
        utf8_valid = not bool(_CONTROL_CHARACTERS.search(response))
    except UnicodeEncodeError:
        utf8_valid = False

    thai_required = case["category"] == "thai_answerable"
    return DeterministicVerdict(
        route_correct=state.get("route") == ROUTE_KB,
        expected_evidence_retrieved=retrieved_expected,
        no_not_found_after_expected_evidence=not (
            retrieved_expected and response == NOT_FOUND_SENTENCE
        ),
        negative_exact_not_found=(
            response == NOT_FOUND_SENTENCE
            if case["category"] == "negative"
            else None
        ),
        citation_valid=not invalid,
        invalid_citations=invalid,
        citation_coverage=(cited_count / len(units) if units else 1.0),
        factual_unit_count=len(units),
        cited_factual_unit_count=cited_count,
        utf8_schema_valid=utf8_valid,
        thai_script_present=(
            bool(_THAI_PATTERN.search(response)) if thai_required else None
        ),
    )


def judge_response(
    question: str,
    snippets: Sequence[str],
    response: str,
) -> AnswerJudgeVerdict:
    """Run one structured judge request for all non-deterministic axes."""
    judge = get_llm().with_structured_output(AnswerJudgeVerdict)
    try:
        verdict = judge.invoke(
            [
                SystemMessage(content=_JUDGE_PROMPT),
                HumanMessage(
                    content=(
                        f"QUESTION:\n{question}\n\nEVIDENCE:\n"
                        + "\n\n".join(snippets)
                        + f"\n\nFINAL RESPONSE:\n{response}"
                    )
                ),
            ]
        )
    except Exception:
        raise R3ProviderError(
            "Answer judge provider call failed; no quality result was recorded."
        ) from None
    if not isinstance(verdict, AnswerJudgeVerdict):
        raise R3ProviderError(
            "Answer judge returned an invalid schema; no quality result was recorded."
        )
    return verdict


def _judge_failures(
    deterministic: DeterministicVerdict,
    judge: AnswerJudgeVerdict | None,
) -> tuple[str, ...]:
    failures: list[str] = []
    if not deterministic.route_correct:
        failures.append("route_incorrect")
    if not deterministic.no_not_found_after_expected_evidence:
        failures.append("not_found_despite_expected_evidence")
    if deterministic.negative_exact_not_found is False:
        failures.append("negative_not_exact_not_found")
    if not deterministic.citation_valid:
        failures.append("invented_citation")
    if deterministic.citation_coverage < 1.0:
        failures.append("uncited_factual_unit")
    if not deterministic.utf8_schema_valid:
        failures.append("invalid_output_encoding")
    if deterministic.thai_script_present is False:
        failures.append("thai_script_missing")
    if judge is not None:
        claims = judge.claims
        faithfulness = (
            sum(claim.supported for claim in claims) / len(claims)
            if claims
            else 0.0
        )
        if faithfulness < _FAITHFULNESS_THRESHOLD:
            failures.append("judge_faithfulness_below_threshold")
        if judge.relevance < _RELEVANCE_THRESHOLD:
            failures.append("judge_relevance_below_threshold")
        if judge.completeness < _RELEVANCE_THRESHOLD:
            failures.append("judge_completeness_below_threshold")
        if not judge.language_appropriate:
            failures.append("judge_language_inappropriate")
        if not judge.specific_data_discipline:
            failures.append("judge_specific_data_discipline_failed")
        if any(not claim.supported and claim.high_risk for claim in claims):
            failures.append("unsupported_high_risk_claim")
    return tuple(dict.fromkeys(failures))


def evaluate_case(
    *,
    graph: object,
    case: BaselineCase,
    judge_fn: Callable[
        [str, Sequence[str], str],
        AnswerJudgeVerdict,
    ] = judge_response,
) -> tuple[CaseEvaluation, dict[str, object]]:
    """Run one case through the real graph and return public/private records."""
    try:
        state = graph.invoke(
            {
                "query": case["query"],
                "snippets": [],
                "report": "",
                "search_mode": "hybrid",
                "top_k": 6,
            }
        )
    except Exception:
        raise R3ProviderError(
            "End-to-end provider call failed; no quality result was recorded."
        ) from None
    if not isinstance(state, dict):
        raise R3ExecutionError("End-to-end graph returned an invalid state.")

    deterministic = validate_response(case=case, state=state)
    response = cast(str, state["report"])
    snippets = cast(list[str], state.get("snippets") or [])
    judge: AnswerJudgeVerdict | None = None
    if response != NOT_FOUND_SENTENCE:
        judge = judge_fn(case["query"], snippets, response)
    failures = _judge_failures(deterministic, judge)
    handed_titles = context_titles(snippets)
    public = CaseEvaluation(
        case_id=case["id"],
        category=case["category"],
        language=case["language"],
        route=str(state.get("route", "")),
        search_attempt_count=len(cast(list[object], state.get("search_attempts") or [])),
        expected_titles=tuple(case["expected_titles"]),
        handed_context_titles=handed_titles,
        cited_titles=cited_titles(response),
        deterministic=deterministic,
        judge=judge,
        judge_failure_reasons=failures,
    )
    private = {
        "case_id": case["id"],
        "category": case["category"],
        "language": case["language"],
        "query": case["query"],
        "snippets": snippets,
        "answer": response,
        "route": state.get("route"),
        "search_attempts": state.get("search_attempts") or [],
        "judge": None if judge is None else judge.model_dump(),
        "review_reasons": list(failures),
    }
    return public, private


def _case_payload(result: CaseEvaluation) -> dict[str, object]:
    judge = result.judge
    claim_count = len(judge.claims) if judge is not None else 0
    supported_count = (
        sum(claim.supported for claim in judge.claims) if judge is not None else 0
    )
    return {
        "case_id": result.case_id,
        "category": result.category,
        "language": result.language,
        "route": result.route,
        "search_attempt_count": result.search_attempt_count,
        "expected_titles": list(result.expected_titles),
        "handed_context_titles": list(result.handed_context_titles),
        "cited_titles": list(result.cited_titles),
        "deterministic": asdict(result.deterministic),
        "judge_metrics": (
            None
            if judge is None
            else {
                "claim_count": claim_count,
                "supported_claim_count": supported_count,
                "faithfulness": (
                    supported_count / claim_count if claim_count else 0.0
                ),
                "relevance": judge.relevance,
                "completeness": judge.completeness,
                "language_appropriate": judge.language_appropriate,
                "specific_data_discipline": judge.specific_data_discipline,
                "unsupported_high_risk_claim_count": sum(
                    not claim.supported and claim.high_risk
                    for claim in judge.claims
                ),
            }
        ),
        "judge_failure_reasons": list(result.judge_failure_reasons),
    }


def aggregate_metrics(results: Sequence[CaseEvaluation]) -> dict[str, float | int]:
    """Compute R3 answer metrics without hiding degraded responses."""
    negatives = [
        result for result in results if result.category == "negative"
    ]
    thai = [
        result for result in results if result.category == "thai_answerable"
    ]
    generated = [
        result for result in results if result.judge is not None
    ]
    generated_answerable = [
        result
        for result in generated
        if result.category != "negative"
    ]
    all_claims = [
        claim
        for result in generated
        for claim in cast(AnswerJudgeVerdict, result.judge).claims
    ]
    total_units = sum(result.deterministic.factual_unit_count for result in generated)
    cited_units = sum(
        result.deterministic.cited_factual_unit_count for result in generated
    )
    return {
        "case_count": len(results),
        "route_correctness": mean(
            [float(result.deterministic.route_correct) for result in results]
        ),
        "no_not_found_after_expected_evidence": mean(
            [
                float(result.deterministic.no_not_found_after_expected_evidence)
                for result in results
                if result.deterministic.expected_evidence_retrieved
            ]
        ),
        "negative_exact_not_found": mean(
            [
                float(cast(bool, result.deterministic.negative_exact_not_found))
                for result in negatives
            ]
        ),
        "answer_citation_validity": mean(
            [float(result.deterministic.citation_valid) for result in generated]
        ),
        "answer_citation_coverage": (
            cited_units / total_units if total_units else 1.0
        ),
        "output_schema_encoding_validity": mean(
            [float(result.deterministic.utf8_schema_valid) for result in results]
        ),
        "thai_script_appropriateness": mean(
            [
                float(cast(bool, result.deterministic.thai_script_present))
                for result in thai
            ]
        ),
        "faithfulness": mean([float(claim.supported) for claim in all_claims]),
        "answer_relevance": mean(
            [
                cast(AnswerJudgeVerdict, result.judge).relevance
                for result in generated_answerable
            ]
        ),
        "completeness": mean(
            [
                cast(AnswerJudgeVerdict, result.judge).completeness
                for result in generated_answerable
            ]
        ),
        "model_language_appropriateness": mean(
            [
                float(cast(AnswerJudgeVerdict, result.judge).language_appropriate)
                for result in generated
            ]
        ),
        "specific_data_discipline": mean(
            [
                float(
                    cast(
                        AnswerJudgeVerdict,
                        result.judge,
                    ).specific_data_discipline
                )
                for result in generated
            ]
        ),
        "unsupported_high_risk_claim_count": sum(
            not claim.supported and claim.high_risk for claim in all_claims
        ),
        "degraded_answerable_count": sum(
            result.category != "negative" and result.judge is None
            for result in results
        ),
    }


def answer_gate_failures(
    metrics: Mapping[str, float | int],
) -> tuple[str, ...]:
    """Apply the remediation plan's answer-level hard gates."""
    failures: list[str] = []
    gates = (
        ("route_correctness", 1.0),
        ("no_not_found_after_expected_evidence", 1.0),
        ("negative_exact_not_found", _NEGATIVE_EXACT_THRESHOLD),
        ("answer_citation_validity", 1.0),
        ("answer_citation_coverage", 1.0),
        ("output_schema_encoding_validity", 1.0),
        ("faithfulness", _FAITHFULNESS_THRESHOLD),
        ("answer_relevance", _RELEVANCE_THRESHOLD),
        ("thai_script_appropriateness", _THAI_LANGUAGE_THRESHOLD),
    )
    for metric, threshold in gates:
        if float(metrics[metric]) < threshold:
            failures.append(f"{metric}_below_{threshold:g}")
    if int(metrics["unsupported_high_risk_claim_count"]) != 0:
        failures.append("unsupported_high_risk_claim_count_above_0")
    return tuple(failures)


def human_review_case_ids(results: Sequence[CaseEvaluation]) -> tuple[str, ...]:
    """Select mandatory category quotas plus every automated judge failure."""
    selected: list[str] = []
    quotas = (
        ("thai_answerable", 5),
        ("negative", 5),
        ("multi_section", 3),
        ("mixed_answerable", 3),
    )
    for category, count in quotas:
        category_ids = [
            result.case_id
            for result in results
            if result.category == category
        ]
        selected.extend(category_ids[:count])
    selected.extend(
        result.case_id for result in results if result.judge_failure_reasons
    )
    return tuple(dict.fromkeys(selected))


def _render_report(
    payload: Mapping[str, object],
    results: Sequence[CaseEvaluation],
    metrics: Mapping[str, float | int],
    failures: Sequence[str],
) -> str:
    rows = [
        "| Metric | Result | Target | Gate |",
        "|---|---:|---:|---|",
        f"| Route correctness | {float(metrics['route_correctness']):.1%} | "
        f"100% | {'PASS' if float(metrics['route_correctness']) == 1 else 'FAIL'} |",
        f"| Citation validity | "
        f"{float(metrics['answer_citation_validity']):.1%} | 100% | "
        f"{'PASS' if float(metrics['answer_citation_validity']) == 1 else 'FAIL'} |",
        f"| Citation coverage | "
        f"{float(metrics['answer_citation_coverage']):.1%} | 100% | "
        f"{'PASS' if float(metrics['answer_citation_coverage']) == 1 else 'FAIL'} |",
        f"| Negative exact not-found | "
        f"{float(metrics['negative_exact_not_found']):.1%} | ≥90% | "
        f"{'PASS' if float(metrics['negative_exact_not_found']) >= .9 else 'FAIL'} |",
        f"| Faithfulness | {float(metrics['faithfulness']):.1%} | ≥95% | "
        f"{'PASS' if float(metrics['faithfulness']) >= .95 else 'FAIL'} |",
        f"| Relevance | {float(metrics['answer_relevance']):.2f}/5 | ≥4.0 | "
        f"{'PASS' if float(metrics['answer_relevance']) >= 4 else 'FAIL'} |",
        f"| Thai-script appropriateness | "
        f"{float(metrics['thai_script_appropriateness']):.1%} | ≥90% | "
        f"{'PASS' if float(metrics['thai_script_appropriateness']) >= .9 else 'FAIL'} |",
        f"| Unsupported high-risk claims | "
        f"{metrics['unsupported_high_risk_claim_count']} | 0 | "
        f"{'PASS' if int(metrics['unsupported_high_risk_claim_count']) == 0 else 'FAIL'} |",
    ]
    case_rows = [
        "| Case | Category | Route | Context titles | Citations | Automated review |",
        "|---|---|---|---:|---:|---|",
    ]
    for result in results:
        case_rows.append(
            f"| `{result.case_id}` | {result.category} | {result.route} | "
            f"{len(result.handed_context_titles)} | {len(result.cited_titles)} | "
            f"{', '.join(result.judge_failure_reasons) or 'PASS'} |"
        )
    review = cast(Mapping[str, object], payload["human_review"])
    return "\n".join(
        [
            "# Track A R3 — Final Answer Evaluation",
            "",
            f"- Generated at: {payload['generated_at']}",
            "- Pipeline: User → Router → Retriever/Translation → Hybrid + "
            "Reranker + Context → Rewrite when required → Generator → Validators.",
            "- Dataset: all 40 frozen `lean-quality-v1` cases.",
            "- One structured judge request covers faithfulness, relevance, "
            "completeness, language, and specific-data discipline.",
            "- Published evidence excludes raw queries, answers, prompts, "
            "snippets, document bodies, credentials, and provider error text.",
            "",
            "## Hard gates",
            "",
            *rows,
            "",
            f"Automated gate: **{'PASS' if not failures else 'FAIL'}**"
            + (f" — {', '.join(failures)}" if failures else ""),
            "",
            "## Human/Domain review",
            "",
            f"- Status: **{review['status']}**",
            f"- Required cases: {review['required_case_count']}",
            f"- Owner-only local bundle: `{review['private_bundle']}`",
            "- Automated/model results do not constitute Product/Business approval.",
            "",
            "## Sanitized per-case evidence",
            "",
            *case_rows,
        ]
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-answer-evaluation",
        action="store_true",
        help="Approve sending the 40 frozen questions and generated responses.",
    )
    parser.add_argument(
        "--allow-knowledge-snippets",
        action="store_true",
        help="Approve sending retrieved knowledge snippets for generation/judging.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.allow_answer_evaluation or not args.allow_knowledge_snippets:
        raise R3ExecutionError(
            "Answer evaluation requires explicit question/response and knowledge-"
            "snippet approval flags."
        )

    profile = selected_profile()
    verify_effective_profile(profile)
    verify_track_a_r0_freeze()
    verify_r1_artifact_provenance()
    ablation = load_json(ABLATION_RESULTS_PATH)
    if ablation.get("selected_ablation_id") != "A5":
        raise R3ValidationError("Ablation evidence does not select A5.")
    if ablation.get("selected_passed_retrieval_gates") is not True:
        raise R3ValidationError("Selected A5 did not pass retrieval gates.")
    if ablation.get("identity") != evidence_identity():
        raise R3ValidationError("Ablation and answer evidence identities differ.")

    cases = load_baseline_cases()
    chunks = load_chunks()
    validate_baseline_cases(cases, valid_titles={chunk.title for chunk in chunks})
    graph = build_graph()
    public_results: list[CaseEvaluation] = []
    private_results: list[dict[str, object]] = []
    for position, case in enumerate(cases, start=1):
        print(
            f"Answer evaluation {position:02d}/{len(cases)} "
            f"case={case['id']}",
            flush=True,
        )
        public, private = evaluate_case(graph=graph, case=case)
        public_results.append(public)
        private_results.append(private)

    metrics = aggregate_metrics(public_results)
    failures = answer_gate_failures(metrics)
    review_ids = human_review_case_ids(public_results)
    private_by_id = {
        cast(str, record["case_id"]): record for record in private_results
    }
    write_private_review_bundle(
        PRIVATE_REVIEW_PATH,
        {
            "schema_version": _REVIEW_SCHEMA_VERSION,
            "generated_at": generated_at(),
            "security": {
                "owner_only_permissions": True,
                "git_ignored": True,
                "contains_sensitive_evaluation_material": True,
            },
            "review_status": "PENDING_HUMAN_APPROVAL",
            "required_case_ids": list(review_ids),
            "cases": [private_by_id[case_id] for case_id in review_ids],
        },
    )

    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "generated_at": generated_at(),
        "identity": evidence_identity(),
        "ablation_evidence": {
            "path": ABLATION_RESULTS_PATH.name,
            "sha256": sha256_file(ABLATION_RESULTS_PATH),
            "selected_ablation_id": "A5",
        },
        "selected_profile": profile,
        "data_boundary": {
            "external_answer_evaluation_approved": True,
            "external_knowledge_snippets_approved": True,
            "provider_failure_count": 0,
            "raw_queries_stored_in_published_artifact": False,
            "answers_stored_in_published_artifact": False,
            "document_bodies_stored_in_published_artifact": False,
            "credentials_stored": False,
        },
        "metrics": metrics,
        "thresholds": {
            "negative_exact_not_found": _NEGATIVE_EXACT_THRESHOLD,
            "answer_citation_validity": 1.0,
            "answer_citation_coverage": 1.0,
            "faithfulness": _FAITHFULNESS_THRESHOLD,
            "answer_relevance": _RELEVANCE_THRESHOLD,
            "thai_script_appropriateness": _THAI_LANGUAGE_THRESHOLD,
            "unsupported_high_risk_claim_count": 0,
        },
        "automated_gate": {
            "passed": not failures,
            "failures": list(failures),
        },
        "human_review": {
            "status": "PENDING_HUMAN_APPROVAL",
            "required_case_count": len(review_ids),
            "required_case_ids": list(review_ids),
            "private_bundle": PRIVATE_REVIEW_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "automated_results_are_not_human_approval": True,
        },
        "cases": [_case_payload(result) for result in public_results],
    }
    report = _render_report(payload, public_results, metrics, failures)
    write_versioned_pair(
        payload,
        report,
        json_path=RESULTS_JSON_PATH,
        markdown_path=RESULTS_MARKDOWN_PATH,
    )
    print(f"Written {RESULTS_JSON_PATH.name}")
    print(f"Written {RESULTS_MARKDOWN_PATH.name}")
    print(f"Private review bundle: {PRIVATE_REVIEW_PATH}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

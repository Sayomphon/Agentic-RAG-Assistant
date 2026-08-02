"""Tests for deterministic and provider-safe Track A R3 answer evaluation."""

from __future__ import annotations

import unittest

from src.agents.reporter import NOT_FOUND_SENTENCE
from src.evaluation.run_track_a_answer_eval import (
    AnswerJudgeVerdict,
    AtomicClaimVerdict,
    R3ExecutionError,
    R3ProviderError,
    aggregate_metrics,
    evaluate_case,
    factual_units,
    human_review_case_ids,
    main,
    validate_response,
)
from src.retrievers.base import Chunk, ScoredChunk


def _case(
    *,
    case_id: str = "case-1",
    category: str = "english_answerable",
    language: str = "en",
    expected_titles: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": case_id,
        "category": category,
        "language": language,
        "query": "private evaluation question",
        "expected_titles": (
            ["Leave Policy"] if expected_titles is None else expected_titles
        ),
    }


def _hit(title: str = "Leave Policy") -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(title=title, text="Approved evidence.", index=0),
        score=1.0,
        source="hybrid",
    )


class _Graph:
    def __init__(self, state: dict[str, object] | Exception) -> None:
        self._state = state

    def invoke(self, _state: dict[str, object]) -> dict[str, object]:
        if isinstance(self._state, Exception):
            raise self._state
        return self._state


def _judge(
    _question: str,
    _snippets: object,
    _response: str,
) -> AnswerJudgeVerdict:
    return AnswerJudgeVerdict(
        claims=[AtomicClaimVerdict(supported=True, high_risk=False)],
        relevance=5,
        completeness=5,
        language_appropriate=True,
        specific_data_discipline=True,
    )


class AnswerValidatorTests(unittest.TestCase):
    def test_citation_validator_rejects_invented_title(self) -> None:
        verdict = validate_response(
            case=_case(),  # type: ignore[arg-type]
            state={
                "route": "kb_query",
                "report": "Leave is approved. [Invented Policy]",
                "snippets": ["[Leave Policy]\nApproved evidence."],
                "hits": [_hit()],
            },
        )

        self.assertFalse(verdict.citation_valid)
        self.assertEqual(verdict.invalid_citations, ("Invented Policy",))

    def test_citation_coverage_detects_uncited_factual_sentence(self) -> None:
        units = factual_units(
            "Leave is available. Manager approval is required. [Leave Policy]"
        )

        self.assertEqual(len(units), 2)
        self.assertFalse(units[0][1])
        self.assertTrue(units[1][1])

    def test_negative_validator_requires_exact_not_found(self) -> None:
        negative = _case(
            category="negative",
            expected_titles=[],
        )
        exact = validate_response(
            case=negative,  # type: ignore[arg-type]
            state={
                "route": "kb_query",
                "report": NOT_FOUND_SENTENCE,
                "snippets": [],
                "hits": [],
            },
        )
        altered = validate_response(
            case=negative,  # type: ignore[arg-type]
            state={
                "route": "kb_query",
                "report": f"{NOT_FOUND_SENTENCE} ",
                "snippets": [],
                "hits": [],
            },
        )

        self.assertTrue(exact.negative_exact_not_found)
        self.assertFalse(altered.negative_exact_not_found)

    def test_provider_failure_aborts_without_quality_result(self) -> None:
        with self.assertRaises(R3ProviderError):
            evaluate_case(
                graph=_Graph(RuntimeError("sensitive provider detail")),
                case=_case(),  # type: ignore[arg-type]
                judge_fn=_judge,
            )

    def test_external_evaluation_requires_both_approval_flags(self) -> None:
        with self.assertRaises(R3ExecutionError):
            main([])
        with self.assertRaises(R3ExecutionError):
            main(["--allow-answer-evaluation"])

    def test_public_case_aggregation_uses_content_free_judge_values(self) -> None:
        result, _ = evaluate_case(
            graph=_Graph(
                {
                    "route": "kb_query",
                    "report": "Leave is approved. [Leave Policy]",
                    "snippets": ["[Leave Policy]\nApproved evidence."],
                    "hits": [_hit()],
                    "search_attempts": ["leave"],
                }
            ),
            case=_case(),  # type: ignore[arg-type]
            judge_fn=_judge,
        )
        metrics = aggregate_metrics([result])

        self.assertEqual(metrics["answer_citation_validity"], 1.0)
        self.assertEqual(metrics["answer_citation_coverage"], 1.0)
        self.assertEqual(metrics["faithfulness"], 1.0)

    def test_human_review_quotas_include_all_automated_failures(self) -> None:
        results = []
        categories = (
            ("thai_answerable", 6),
            ("negative", 6),
            ("multi_section", 4),
            ("mixed_answerable", 4),
        )
        for category, count in categories:
            for index in range(count):
                result, _ = evaluate_case(
                    graph=_Graph(
                        {
                            "route": "kb_query",
                            "report": NOT_FOUND_SENTENCE,
                            "snippets": [],
                            "hits": [],
                            "search_attempts": [],
                        }
                    ),
                    case=_case(
                        case_id=f"{category}-{index}",
                        category=category,
                        language="th" if category == "thai_answerable" else "en",
                        expected_titles=(
                            []
                            if category == "negative"
                            else ["Leave Policy"]
                        ),
                    ),  # type: ignore[arg-type]
                    judge_fn=_judge,
                )
                results.append(result)

        selected = human_review_case_ids(results)

        self.assertGreaterEqual(
            sum(case_id.startswith("thai_answerable") for case_id in selected),
            5,
        )
        self.assertGreaterEqual(
            sum(case_id.startswith("negative") for case_id in selected),
            5,
        )
        self.assertGreaterEqual(
            sum(case_id.startswith("multi_section") for case_id in selected),
            3,
        )
        self.assertGreaterEqual(
            sum(case_id.startswith("mixed_answerable") for case_id in selected),
            3,
        )


if __name__ == "__main__":
    unittest.main()

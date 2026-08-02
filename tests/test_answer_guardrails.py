"""Tests for deterministic citation validation and bounded runtime repair."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.agents.reporter import NOT_FOUND_SENTENCE, generator_node
from src.guardrails.answer import (
    AnswerDecision,
    AnswerReasonCode,
    assess_evidence_sufficiency,
    factual_units,
    validate_answer,
    validate_citations,
)


class _SequenceLLM:
    """Return configured chat responses in order without external calls."""

    def __init__(self, *responses: str | Exception) -> None:
        self._responses = iter(responses)
        self.calls = 0

    def invoke(self, _messages: object) -> SimpleNamespace:
        self.calls += 1
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=response)


class CitationValidationTests(unittest.TestCase):
    def test_valid_fully_cited_answer_passes(self) -> None:
        result = validate_citations(
            "Leave is available. [Leave Policy]",
            ["[Leave Policy]\nEmployees receive leave."],
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.coverage, 1.0)

    def test_invented_citation_fails(self) -> None:
        result = validate_citations(
            "Leave is available. [Invented Policy]",
            ["[Leave Policy]\nEmployees receive leave."],
        )

        self.assertIn(
            AnswerReasonCode.UNKNOWN_CITATION_TITLE,
            result.reason_codes,
        )

    def test_uncited_factual_sentence_is_detected(self) -> None:
        result = validate_citations(
            "Leave is available. Approval is required. [Leave Policy]",
            ["[Leave Policy]\nLeave requires approval."],
        )

        self.assertEqual(result.factual_unit_count, 2)
        self.assertEqual(result.cited_factual_unit_count, 1)
        self.assertIn(
            AnswerReasonCode.UNCITED_FACTUAL_UNIT,
            result.reason_codes,
        )

    def test_citation_in_the_middle_does_not_cover_trailing_claim(self) -> None:
        result = validate_citations(
            "Leave is available. [Leave Policy] Approval is required.",
            ["[Leave Policy]\nLeave requires approval."],
        )

        self.assertEqual(result.factual_unit_count, 2)
        self.assertEqual(result.cited_factual_unit_count, 1)
        self.assertFalse(result.passed)

    def test_heading_and_standalone_bullet_label_are_not_factual(self) -> None:
        units = factual_units(
            "# Leave\n"
            "- Eligibility:\n"
            "- Employees receive leave. [Leave Policy]"
        )

        self.assertEqual(
            units,
            (("Employees receive leave. [Leave Policy]", True),),
        )

    def test_thai_and_mixed_sentence_boundaries_are_supported(self) -> None:
        result = validate_citations(
            "พนักงานลาได้。Manager approval is required. [Leave Policy]",
            ["[Leave Policy]\nLeave requires manager approval."],
        )

        self.assertEqual(result.factual_unit_count, 2)
        self.assertEqual(result.cited_factual_unit_count, 1)

    def test_abbreviation_does_not_create_a_false_sentence_boundary(self) -> None:
        result = validate_citations(
            "Use approved evidence, e.g. receipts. [Expense Policy]",
            ["[Expense Policy]\nApproved receipts are required."],
        )

        self.assertEqual(result.factual_unit_count, 1)
        self.assertTrue(result.passed)


class ReporterGuardrailTests(unittest.TestCase):
    @patch("src.agents.reporter.get_llm")
    def test_repairs_once_and_revalidates(self, mock_get_llm: object) -> None:
        llm = _SequenceLLM(
            "Leave is available.",
            "Leave is available. [Leave Policy]",
        )
        mock_get_llm.return_value = llm  # type: ignore[attr-defined]

        result = generator_node(
            {
                "query": "Is leave available?",
                "snippets": ["[Leave Policy]\nEmployees receive leave."],
                "report": "",
            }
        )

        self.assertEqual(result["report"], "Leave is available. [Leave Policy]")
        self.assertEqual(result["answer_decision"], "ANSWER")
        self.assertTrue(result["answer_repair_attempted"])
        self.assertEqual(llm.calls, 2)

    @patch("src.agents.reporter.get_llm")
    def test_failed_repair_fails_closed_after_one_attempt(
        self,
        mock_get_llm: object,
    ) -> None:
        llm = _SequenceLLM("Leave is available.", "Leave is available.")
        mock_get_llm.return_value = llm  # type: ignore[attr-defined]

        result = generator_node(
            {
                "query": "Is leave available?",
                "snippets": ["[Leave Policy]\nEmployees receive leave."],
                "report": "",
            }
        )

        self.assertEqual(result["report"], NOT_FOUND_SENTENCE)
        self.assertEqual(result["answer_decision"], "NOT_FOUND")
        self.assertEqual(llm.calls, 2)
        self.assertIn(
            AnswerReasonCode.ANSWER_FAIL_CLOSED.value,
            result["answer_guardrail_reason_codes"],
        )

    @patch("src.agents.reporter.get_llm")
    def test_repair_provider_failure_is_sanitized(
        self,
        mock_get_llm: object,
    ) -> None:
        llm = _SequenceLLM(
            "Leave is available.",
            RuntimeError("private provider detail"),
        )
        mock_get_llm.return_value = llm  # type: ignore[attr-defined]

        result = generator_node(
            {
                "query": "private query",
                "snippets": ["[Leave Policy]\nprivate evidence"],
                "report": "",
            }
        )

        self.assertEqual(result["report"], NOT_FOUND_SENTENCE)
        self.assertNotIn("private", repr(result))
        self.assertIn(
            AnswerReasonCode.CITATION_REPAIR_FAILED.value,
            result["answer_guardrail_reason_codes"],
        )


class HighRiskValidationTests(unittest.TestCase):
    def test_supported_exact_value_and_role_pass(self) -> None:
        result = validate_answer(
            "Claims under 20,000 THB require a line manager. "
            "[Expense Reimbursement]",
            [
                "[Expense Reimbursement]\n"
                "Claims under 20,000 THB are approved by the line manager."
            ],
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.high_risk_unit_count, 1)

    def test_numeric_value_absent_from_evidence_is_rejected(self) -> None:
        result = validate_answer(
            "Claims under 10,000 THB require a line manager. "
            "[Expense Reimbursement]",
            [
                "[Expense Reimbursement]\n"
                "Claims under 20,000 THB are approved by the line manager."
            ],
        )

        self.assertEqual(result.unsupported_high_risk_unit_count, 1)
        self.assertIn(
            AnswerReasonCode.UNSUPPORTED_HIGH_RISK_CLAIM,
            result.reason_codes,
        )

    def test_numeric_anchor_does_not_use_substring_matching(self) -> None:
        result = validate_answer(
            "The limit is 20 THB. [Expense Policy]",
            ["[Expense Policy]\nThe documented limit is 120 THB."],
        )

        self.assertIn(
            AnswerReasonCode.UNSUPPORTED_HIGH_RISK_CLAIM,
            result.reason_codes,
        )

    def test_invented_approval_role_is_rejected(self) -> None:
        result = validate_answer(
            "Claims require CFO approval. [Expense Reimbursement]",
            [
                "[Expense Reimbursement]\n"
                "Claims are approved by the line manager."
            ],
        )

        self.assertFalse(result.passed)

    def test_mixed_thai_english_role_is_checked(self) -> None:
        result = validate_answer(
            "รายการนี้ต้องให้ CFO อนุมัติ. [Expense Reimbursement]",
            [
                "[Expense Reimbursement]\n"
                "Claims are approved by the line manager."
            ],
        )

        self.assertIn(
            AnswerReasonCode.UNSUPPORTED_HIGH_RISK_CLAIM,
            result.reason_codes,
        )

    def test_role_alias_requires_a_word_boundary(self) -> None:
        result = validate_answer(
            "Requests go through Portal A. [Request Policy]",
            ["[Request Policy]\nRequests use Portal A."],
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.high_risk_unit_count, 0)


class EvidenceSufficiencyTests(unittest.TestCase):
    def test_partial_expected_evidence_allows_safe_partial_attempt(self) -> None:
        result = assess_evidence_sufficiency(
            (
                "What happens before a new employee starts, how long is "
                "probation, and when does health coverage begin?"
            ),
            [
                "[Probation Period]\nProbation lasts 119 days.",
                "[Health Benefits]\nHealth coverage begins after confirmation.",
            ],
        )

        self.assertEqual(result.decision, AnswerDecision.SAFE_PARTIAL)
        self.assertGreaterEqual(result.matched_term_count, 2)

    def test_false_positive_context_keeps_not_found(self) -> None:
        result = assess_evidence_sufficiency(
            "What is the office Wi-Fi password?",
            [
                "[IT Security]\n"
                "Account passwords must contain at least 14 characters."
            ],
        )

        self.assertEqual(result.decision, AnswerDecision.NOT_FOUND)
        self.assertTrue(result.sensitive_data_request)

    @patch("src.agents.reporter.get_llm")
    def test_not_found_with_partial_evidence_repairs_once(
        self,
        mock_get_llm: object,
    ) -> None:
        llm = _SequenceLLM(
            NOT_FOUND_SENTENCE,
            (
                "Probation lasts 119 days. [Probation Period]\n"
                "Health coverage begins after confirmation. [Health Benefits]"
            ),
        )
        mock_get_llm.return_value = llm  # type: ignore[attr-defined]

        result = generator_node(
            {
                "query": (
                    "What happens before a new employee starts, how long is "
                    "probation, and when does health coverage begin?"
                ),
                "snippets": [
                    "[Probation Period]\nProbation lasts 119 days.",
                    (
                        "[Health Benefits]\n"
                        "Health coverage begins after confirmation."
                    ),
                ],
                "report": "",
            }
        )

        self.assertEqual(result["answer_decision"], "SAFE_PARTIAL")
        self.assertTrue(result["answer_repair_attempted"])
        self.assertEqual(llm.calls, 2)


if __name__ == "__main__":
    unittest.main()

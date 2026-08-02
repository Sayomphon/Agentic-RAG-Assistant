"""Deterministic final-answer validation for grounded RAG responses.

The validator is deliberately model-free. It accepts only exact citation
titles present in the generator context and requires every factual unit to
carry its own citation. Runtime and evaluation import the same functions so
metric definitions cannot silently drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

NOT_FOUND_SENTENCE = "I could not find this information in the knowledge base."

_CITATION_PATTERN = re.compile(r"\[([^\[\]\n]+)\]")
_HEADER_PATTERN = re.compile(r"^\[([^\[\]\n]+)\]\n")
_MARKDOWN_PREFIX = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_SENTENCE_BOUNDARY = re.compile(
    r"(?:(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+|"
    r"(?<=[。！？])\s*|(?<=\])\s+)(?=[^\s\[])",
    flags=re.IGNORECASE,
)
_TERMINAL_CITATIONS = re.compile(r"(?:\s*\[[^\[\]\n]+\])+\s*$")
_STRUCTURAL_LABEL = re.compile(r"[^.!?。！？]{1,80}:")
_NUMBER_PATTERN = re.compile(
    r"(?<![\w])[\d๐-๙][\d๐-๙,]*(?:\.[\d๐-๙]+)?%?"
)
_IDENTIFIER_PATTERN = re.compile(r"\b[A-Z]{2,}-\d+\b")
_ENGLISH_TERM_PATTERN = re.compile(r"[a-z0-9]+")
_MAX_ANSWER_CHARS = 12_000

_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "line_manager": ("line manager", "ผู้จัดการสายงาน"),
    "manager": ("manager", "ผู้จัดการ"),
    "department_head": ("department head", "หัวหน้าแผนก", "หัวหน้าฝ่าย"),
    "finance": ("finance", "ฝ่ายการเงิน"),
    "cfo": ("cfo", "chief financial officer", "ประธานเจ้าหน้าที่ฝ่ายการเงิน"),
    "managing_director": (
        "managing director",
        "กรรมการผู้จัดการ",
    ),
    "human_resources": ("human resources", "hr", "ฝ่ายทรัพยากรบุคคล"),
    "legal": ("legal team", "ฝ่ายกฎหมาย"),
}
_HIGH_RISK_TERMS = frozenset(
    {
        "approval",
        "approve",
        "authority",
        "budget",
        "compliance",
        "deadline",
        "eligible",
        "eligibility",
        "health",
        "legal",
        "medical",
        "money",
        "personal data",
        "privacy",
        "salary",
        "security",
        "termination",
        "วงเงิน",
        "อนุมัติ",
        "กฎหมาย",
        "ข้อมูลส่วนบุคคล",
        "ความปลอดภัย",
        "สุขภาพ",
    }
)
_QUERY_STOP_WORDS = frozenset(
    {
        "about",
        "and",
        "apply",
        "are",
        "before",
        "begin",
        "does",
        "employee",
        "for",
        "from",
        "happen",
        "how",
        "is",
        "long",
        "new",
        "of",
        "on",
        "the",
        "to",
        "what",
        "when",
        "who",
        "with",
    }
)
_POLICY_INTENT_TERMS = frozenset(
    {
        "deadline",
        "length",
        "minimum",
        "policy",
        "process",
        "report",
        "requirement",
        "rule",
    }
)
_SECRET_TERMS = frozenset(
    {
        "credential",
        "key",
        "password",
        "secret",
        "token",
    }
)
_SENSITIVE_QUERY_PATTERNS = (
    re.compile(r"\b(?:ceo|executive)\b.*\bsalary\b"),
    re.compile(r"\b(?:employee|customer)\b.*\b(?:address|card number)s?\b"),
    re.compile(r"\b(?:acquisition plan|biometric record|board minute)s?\b"),
    re.compile(r"\b(?:medical diagnosis|performance rating)s?\b"),
)


class AnswerDecision(str, Enum):
    """Runtime answerability decision made before output is released."""

    ANSWER = "ANSWER"
    SAFE_PARTIAL = "SAFE_PARTIAL"
    NOT_FOUND = "NOT_FOUND"


class AnswerReasonCode(str, Enum):
    """Stable content-free reason codes safe for state and telemetry."""

    EMPTY_ANSWER = "EMPTY_ANSWER"
    INVALID_CONTEXT_HEADER = "INVALID_CONTEXT_HEADER"
    UNKNOWN_CITATION_TITLE = "UNKNOWN_CITATION_TITLE"
    UNCITED_FACTUAL_UNIT = "UNCITED_FACTUAL_UNIT"
    UNSUPPORTED_HIGH_RISK_CLAIM = "UNSUPPORTED_HIGH_RISK_CLAIM"
    NOT_FOUND_WITH_SUFFICIENT_EVIDENCE = (
        "NOT_FOUND_WITH_SUFFICIENT_EVIDENCE"
    )
    ANSWER_TOO_LONG = "ANSWER_TOO_LONG"
    CITATION_REPAIR_FAILED = "CITATION_REPAIR_FAILED"
    ANSWER_FAIL_CLOSED = "ANSWER_FAIL_CLOSED"


@dataclass(frozen=True)
class CitationValidation:
    """One immutable citation-validation result."""

    available_titles: tuple[str, ...]
    cited_titles: tuple[str, ...]
    invalid_citations: tuple[str, ...]
    factual_unit_count: int
    cited_factual_unit_count: int
    reason_codes: tuple[AnswerReasonCode, ...]

    @property
    def coverage(self) -> float:
        """Return factual-unit citation coverage on a zero-safe scale."""
        if not self.factual_unit_count:
            return 1.0
        return self.cited_factual_unit_count / self.factual_unit_count

    @property
    def passed(self) -> bool:
        """Return whether the answer is safe to leave the citation boundary."""
        return not self.reason_codes


@dataclass(frozen=True)
class AnswerValidation:
    """Combined citation and deterministic high-risk support result."""

    citation: CitationValidation
    high_risk_unit_count: int
    unsupported_high_risk_unit_count: int
    reason_codes: tuple[AnswerReasonCode, ...]

    @property
    def passed(self) -> bool:
        """Return whether every deterministic answer gate passed."""
        return not self.reason_codes


@dataclass(frozen=True)
class EvidenceSufficiency:
    """Content-free evidence-sufficiency outcome for a generated not-found."""

    decision: AnswerDecision
    answerability_score: float
    required_term_count: int
    matched_term_count: int
    available_title_count: int
    sensitive_data_request: bool


def context_titles(snippets: Sequence[str]) -> tuple[str, ...]:
    """Extract exact allowlisted titles from framed generator snippets.

    Raises:
        ValueError: A snippet does not begin with the required ``[title]``
            header or repeats a title. Duplicate titles are rejected because
            they make claim-to-evidence mapping ambiguous.
    """
    titles: list[str] = []
    for snippet in snippets:
        match = _HEADER_PATTERN.match(snippet)
        if match is None:
            raise ValueError("Generator context contains an invalid header.")
        title = match.group(1)
        if title in titles:
            raise ValueError("Generator context contains a duplicate header.")
        titles.append(title)
    return tuple(titles)


def cited_titles(response: str) -> tuple[str, ...]:
    """Return unique citation titles in first-seen order."""
    return tuple(dict.fromkeys(_CITATION_PATTERN.findall(response)))


def factual_units(response: str) -> tuple[tuple[str, bool], ...]:
    """Split an answer into auditable units and mark citation coverage.

    Markdown headings, stand-alone bullet labels, and the deterministic
    not-found response are structural rather than factual. A citation on the
    final sentence of a paragraph never covers an earlier sentence.
    """
    if response == NOT_FOUND_SENTENCE:
        return ()

    output: list[tuple[str, bool]] = []
    for raw_line in response.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = _MARKDOWN_PREFIX.sub("", line)
        if _STRUCTURAL_LABEL.fullmatch(line):
            continue
        for sentence in _SENTENCE_BOUNDARY.split(line):
            unit = sentence.strip()
            if not unit or not _CITATION_PATTERN.sub("", unit).strip():
                continue
            output.append((unit, bool(_TERMINAL_CITATIONS.search(unit))))
    return tuple(output)


def validate_citations(
    answer: str,
    snippets: Sequence[str],
) -> CitationValidation:
    """Validate citation titles and per-factual-unit coverage.

    Invalid context fails closed instead of attempting to infer a title.
    Answer content is never included in the returned reason codes.
    """
    reasons: list[AnswerReasonCode] = []
    try:
        available = context_titles(snippets)
    except ValueError:
        available = ()
        reasons.append(AnswerReasonCode.INVALID_CONTEXT_HEADER)

    citations = cited_titles(answer)
    invalid = tuple(sorted(set(citations) - set(available)))
    units = factual_units(answer)
    cited_count = sum(has_citation for _, has_citation in units)

    if not answer.strip() or (answer != NOT_FOUND_SENTENCE and not units):
        reasons.append(AnswerReasonCode.EMPTY_ANSWER)
    if len(answer) > _MAX_ANSWER_CHARS:
        reasons.append(AnswerReasonCode.ANSWER_TOO_LONG)
    if invalid:
        reasons.append(AnswerReasonCode.UNKNOWN_CITATION_TITLE)
    if cited_count != len(units):
        reasons.append(AnswerReasonCode.UNCITED_FACTUAL_UNIT)

    return CitationValidation(
        available_titles=available,
        cited_titles=citations,
        invalid_citations=invalid,
        factual_unit_count=len(units),
        cited_factual_unit_count=cited_count,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _normalize_digits(text: str) -> str:
    """Normalize Thai/Arabic digits and presentation separators."""
    translated = text.translate(
        str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
    )
    return translated.replace(",", "").lower()


def _roles(text: str) -> frozenset[str]:
    """Return canonical approval roles named in one text."""
    normalized = text.casefold()

    def contains(alias: str) -> bool:
        folded = alias.casefold()
        if folded.isascii():
            return bool(
                re.search(
                    rf"(?<!\w){re.escape(folded)}(?!\w)",
                    normalized,
                )
            )
        return folded in normalized

    return frozenset(
        role
        for role, aliases in _ROLE_ALIASES.items()
        if any(contains(alias) for alias in aliases)
    )


def _context_sections(snippets: Sequence[str]) -> dict[str, str]:
    """Return exact title-to-body mappings after strict framing validation."""
    titles = context_titles(snippets)
    return {
        title: snippet.split("\n", 1)[1]
        for title, snippet in zip(titles, snippets, strict=True)
    }


def _high_risk_support(
    answer: str,
    snippets: Sequence[str],
) -> tuple[int, int]:
    """Count high-risk units and units with unsupported exact anchors."""
    try:
        sections = _context_sections(snippets)
    except ValueError:
        return 0, 0

    high_risk_count = 0
    unsupported_count = 0
    for unit, _ in factual_units(answer):
        claim = _CITATION_PATTERN.sub("", unit).strip()
        numbers = tuple(
            _normalize_digits(value)
            for value in _NUMBER_PATTERN.findall(claim)
        )
        identifiers = tuple(_IDENTIFIER_PATTERN.findall(claim.upper()))
        roles = _roles(claim)
        normalized_claim = claim.casefold()
        classified = bool(
            numbers
            or identifiers
            or roles
            or any(term in normalized_claim for term in _HIGH_RISK_TERMS)
        )
        if not classified:
            continue

        high_risk_count += 1
        evidence = "\n".join(
            sections.get(title, "")
            for title in _CITATION_PATTERN.findall(unit)
        )
        evidence_numbers = frozenset(
            _normalize_digits(value)
            for value in _NUMBER_PATTERN.findall(evidence)
        )
        evidence_identifiers = frozenset(
            identifier.casefold()
            for identifier in _IDENTIFIER_PATTERN.findall(evidence.upper())
        )
        evidence_roles = _roles(evidence)
        unsupported = (
            any(number not in evidence_numbers for number in numbers)
            or any(
                identifier.casefold() not in evidence_identifiers
                for identifier in identifiers
            )
            or not roles.issubset(evidence_roles)
        )
        unsupported_count += int(unsupported)

    return high_risk_count, unsupported_count


def validate_answer(
    answer: str,
    snippets: Sequence[str],
) -> AnswerValidation:
    """Apply citation and exact-anchor high-risk validation."""
    citation = validate_citations(answer, snippets)
    high_risk_count, unsupported_count = _high_risk_support(answer, snippets)
    reasons = list(citation.reason_codes)
    if unsupported_count:
        reasons.append(AnswerReasonCode.UNSUPPORTED_HIGH_RISK_CLAIM)
    return AnswerValidation(
        citation=citation,
        high_risk_unit_count=high_risk_count,
        unsupported_high_risk_unit_count=unsupported_count,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _query_terms(query: str) -> tuple[str, ...]:
    """Return stable English content terms for sufficiency assessment."""
    normalized: list[str] = []
    for token in _ENGLISH_TERM_PATTERN.findall(query.casefold()):
        if len(token) > 4 and token.endswith("ing"):
            token = token[:-3]
        elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        if len(token) >= 3 and token not in _QUERY_STOP_WORDS:
            normalized.append(token)
    return tuple(dict.fromkeys(normalized))


def _is_sensitive_data_request(query: str, terms: frozenset[str]) -> bool:
    """Identify requests where false-positive evidence must never trigger repair."""
    normalized = query.casefold()
    if any(pattern.search(normalized) for pattern in _SENSITIVE_QUERY_PATTERNS):
        return True
    return bool(terms & _SECRET_TERMS) and not bool(
        terms & _POLICY_INTENT_TERMS
    )


def is_high_risk_query(query: str) -> bool:
    """Return whether a query falls into an enterprise high-risk domain."""
    normalized = query.casefold()
    return any(term in normalized for term in _HIGH_RISK_TERMS)


def is_multi_section_query(query: str) -> bool:
    """Conservatively recognize compound intents unsafe for Secondary quality."""
    normalized = query.casefold()
    connectors = len(re.findall(r"\b(?:and|plus|also)\b|และ|,", normalized))
    return connectors >= 2


def assess_evidence_sufficiency(
    query: str,
    snippets: Sequence[str],
) -> EvidenceSufficiency:
    """Decide whether a generated not-found merits one safe-partial attempt.

    This is intentionally conservative. It requires multiple content-bearing
    query terms to appear in valid context and suppresses repair for concrete
    secret or sensitive-data requests. Non-empty context alone is never enough.
    """
    try:
        titles = context_titles(snippets)
    except ValueError:
        titles = ()
    terms = _query_terms(query)
    term_set = frozenset(terms)
    sensitive = _is_sensitive_data_request(query, term_set)
    evidence_terms = frozenset(_query_terms(" ".join(snippets)))
    matched = tuple(term for term in terms if term in evidence_terms)
    score = len(matched) / len(terms) if terms else 0.0
    safe_partial = (
        not sensitive
        and bool(titles)
        and len(matched) >= 2
        and score >= 0.35
    )
    return EvidenceSufficiency(
        decision=(
            AnswerDecision.SAFE_PARTIAL
            if safe_partial
            else AnswerDecision.NOT_FOUND
        ),
        answerability_score=score,
        required_term_count=len(terms),
        matched_term_count=len(matched),
        available_title_count=len(titles),
        sensitive_data_request=sensitive,
    )

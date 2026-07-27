"""Versioned evaluation dataset contract for Track A baseline measurements.

The dataset is deliberately stored as JSON rather than executable Python so
reviewers can inspect and version it independently from the evaluation code.
Validation fails closed: malformed cases, duplicate IDs, missing categories,
or labels that do not exist in the corpus stop the baseline before any paid
model call is made.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, TypedDict, cast

DATASET_VERSION = "lean-quality-v1"
DATASET_PATH = (
    Path(__file__).resolve().parent / "datasets" / "lean_quality_v1.json"
)
MANIFEST_PATH = DATASET_PATH.with_suffix(".manifest.json")

REQUIRED_CATEGORY_COUNTS: dict[str, int] = {
    "english_answerable": 10,
    "thai_answerable": 10,
    "mixed_answerable": 5,
    "negative": 10,
    "multi_section": 5,
}
ALLOWED_LANGUAGES = frozenset({"en", "th", "mixed"})


class BaselineCase(TypedDict):
    """One human-labelled retrieval case."""

    id: str
    category: str
    language: str
    query: str
    expected_titles: list[str]


def file_sha256(path: Path) -> str:
    """Return a streaming SHA-256 fingerprint without loading a file at once."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_baseline_cases(path: Path = DATASET_PATH) -> list[BaselineCase]:
    """Load the Track A dataset and reject invalid top-level JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Baseline dataset must be a JSON array.")
    return cast(list[BaselineCase], payload)


def validate_baseline_cases(
    cases: Iterable[BaselineCase],
    *,
    valid_titles: set[str] | None = None,
) -> dict[str, int]:
    """Validate schema, quotas, labels, and return the category distribution."""
    materialized = list(cases)
    seen_ids: set[str] = set()
    category_counts: Counter[str] = Counter()

    for position, case in enumerate(materialized, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Case {position} must be a JSON object.")
        required_fields = {"id", "category", "language", "query", "expected_titles"}
        if set(case) != required_fields:
            missing = sorted(required_fields - set(case))
            extra = sorted(set(case) - required_fields)
            raise ValueError(
                f"Case {position} has invalid fields; missing={missing}, extra={extra}."
            )

        case_id = case["id"].strip()
        category = case["category"]
        language = case["language"]
        query = case["query"].strip()
        expected_titles = case["expected_titles"]

        if not case_id or case_id in seen_ids:
            raise ValueError(f"Case ID must be non-empty and unique: {case_id!r}.")
        seen_ids.add(case_id)

        if category not in REQUIRED_CATEGORY_COUNTS:
            raise ValueError(f"Case {case_id!r} has unknown category {category!r}.")
        if language not in ALLOWED_LANGUAGES:
            raise ValueError(f"Case {case_id!r} has unknown language {language!r}.")
        if not query:
            raise ValueError(f"Case {case_id!r} has an empty query.")
        if not isinstance(expected_titles, list) or any(
            not isinstance(title, str) or not title.strip()
            for title in expected_titles
        ):
            raise ValueError(f"Case {case_id!r} has invalid expected_titles.")
        if len(expected_titles) != len(set(expected_titles)):
            raise ValueError(f"Case {case_id!r} repeats an expected title.")
        if category == "negative" and expected_titles:
            raise ValueError(f"Negative case {case_id!r} must have no expected title.")
        if category != "negative" and not expected_titles:
            raise ValueError(f"Answerable case {case_id!r} needs an expected title.")
        if category == "multi_section" and len(expected_titles) < 2:
            raise ValueError(f"Multi-section case {case_id!r} needs at least two titles.")

        if valid_titles is not None:
            unknown_titles = sorted(set(expected_titles) - valid_titles)
            if unknown_titles:
                raise ValueError(
                    f"Case {case_id!r} references unknown titles: {unknown_titles}."
                )
        category_counts[category] += 1

    for category, minimum in REQUIRED_CATEGORY_COUNTS.items():
        actual = category_counts[category]
        if actual < minimum:
            raise ValueError(
                f"Category {category!r} requires at least {minimum} cases; found {actual}."
            )

    return {
        category: category_counts[category]
        for category in REQUIRED_CATEGORY_COUNTS
    }

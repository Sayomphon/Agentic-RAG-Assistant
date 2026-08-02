"""Shared contracts and security controls for Track A R3 evidence.

Published evidence is intentionally metadata-only. Raw evaluation queries,
answers, prompts, snippets, document bodies, credentials, and provider error
messages must remain outside versioned artifacts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

from src.config import (
    CANDIDATE_K,
    HYBRID_MIN_COSINE,
    MAX_CONTEXT_CHARS,
    RERANKER_BATCH_SIZE,
    RERANKER_ENABLED,
    RERANKER_FAILURE_POLICY,
    RERANKER_FALLBACK_ENABLED,
    RERANKER_FALLBACK_MIN_SCORE,
    RERANKER_MIN_SCORE,
    RERANKER_TIMEOUT_SECONDS,
    SEARCH_MODE,
    TOP_K,
)
from src.evaluation.baseline_dataset import DATASET_PATH, file_sha256
from src.evaluation.run_baseline import corpus_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = (
    PROJECT_ROOT
    / "src"
    / "evaluation"
    / "configs"
    / "track_a_balanced_v1.json"
)
R1_RESULTS_PATH = PROJECT_ROOT / "track_a_pre_upgrade_baseline_v2.json"
R3_METRIC_VERSION = "track-a-r3-metrics-v1"
R3_DATASET_CASE_COUNT = 40

_MAX_JSON_BYTES = 8_000_000
_SECRET_PATTERN = re.compile(
    r"\b(?:sk-|gho_|github_pat_)[A-Za-z0-9_-]{8,}\b"
)
_FORBIDDEN_PUBLISHED_FIELDS = frozenset(
    {
        "access_token",
        "answer",
        "api_key",
        "document_body",
        "openai_api_key",
        "password",
        "prompt",
        "query",
        "raw_environment",
        "raw_exception",
        "refresh_token",
        "secret",
        "snippet",
        "snippets",
        "token",
    }
)


class R3ValidationError(ValueError):
    """Raised when R3 inputs or evidence violate the frozen contract."""


class R3ExecutionError(RuntimeError):
    """Raised for a sanitized execution failure."""


class R3ProviderError(R3ExecutionError):
    """Raised when an external provider call fails.

    The original exception is deliberately not exposed in this boundary.
    """


def reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject ambiguous JSON instead of silently accepting the final key."""
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise R3ValidationError(f"JSON repeats key {key!r}.")
        output[key] = value
    return output


def load_json(path: Path, *, max_bytes: int = _MAX_JSON_BYTES) -> dict[str, object]:
    """Load a bounded UTF-8 JSON object with duplicate-key protection."""
    if not path.is_file() or path.is_symlink():
        raise R3ValidationError(f"Required regular file is unavailable: {path}.")
    content = path.read_bytes()
    if len(content) > max_bytes:
        raise R3ValidationError(f"JSON input exceeds the safe size limit: {path}.")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R3ValidationError(f"Invalid UTF-8 JSON input: {path}.") from exc
    if not isinstance(value, dict):
        raise R3ValidationError(f"JSON root must be an object: {path}.")
    return cast(dict[str, object], value)


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mean(values: Sequence[float]) -> float:
    """Return an arithmetic mean, using zero for an empty sequence."""
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], quantile: float) -> float:
    """Return a deterministic linearly interpolated percentile."""
    if not 0.0 <= quantile <= 1.0:
        raise R3ValidationError("quantile must be within [0, 1].")
    if not values:
        return 0.0
    if not all(math.isfinite(value) for value in values):
        raise R3ValidationError("percentile input contains a non-finite value.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def normalized_rss_mb(raw_value: float, system: str | None = None) -> float:
    """Normalize ``ru_maxrss`` to MiB on macOS and Linux."""
    if not math.isfinite(raw_value) or raw_value < 0:
        raise R3ValidationError("RSS value must be finite and non-negative.")
    runtime = platform.system() if system is None else system
    divisor = 1024 * 1024 if runtime == "Darwin" else 1024
    return raw_value / divisor


def environment_identity() -> dict[str, object]:
    """Return non-secret runtime identity suitable for published evidence."""
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def generated_at() -> str:
    """Return a timezone-aware second-resolution timestamp."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def selected_profile() -> dict[str, object]:
    """Load and verify the reviewed selected-profile document."""
    profile = load_json(PROFILE_PATH)
    required = {
        "schema_version",
        "profile_id",
        "search_mode",
        "candidate_k",
        "top_k",
        "hybrid_min_cosine",
        "reranker_enabled",
        "reranker_min_score",
        "reranker_batch_size",
        "reranker_timeout_seconds",
        "reranker_failure_policy",
        "secondary_enabled",
        "secondary_min_score",
        "max_context_chars",
    }
    if set(profile) != required:
        raise R3ValidationError("Selected profile fields are incomplete or unknown.")
    if profile["schema_version"] != "track-a-runtime-profile-v1":
        raise R3ValidationError("Selected profile schema is unsupported.")
    if profile["profile_id"] != "track_a_balanced_v1":
        raise R3ValidationError("Selected profile ID is unsupported.")
    return profile


def verify_effective_profile(profile: Mapping[str, object]) -> None:
    """Fail closed when the evaluation process differs from the profile."""
    effective = {
        "search_mode": SEARCH_MODE,
        "candidate_k": CANDIDATE_K,
        "top_k": TOP_K,
        "hybrid_min_cosine": HYBRID_MIN_COSINE,
        "reranker_enabled": RERANKER_ENABLED,
        "reranker_min_score": RERANKER_MIN_SCORE,
        "reranker_batch_size": RERANKER_BATCH_SIZE,
        "reranker_timeout_seconds": RERANKER_TIMEOUT_SECONDS,
        "reranker_failure_policy": RERANKER_FAILURE_POLICY,
        "secondary_enabled": RERANKER_FALLBACK_ENABLED,
        "secondary_min_score": RERANKER_FALLBACK_MIN_SCORE,
        "max_context_chars": MAX_CONTEXT_CHARS,
    }
    mismatches = sorted(
        key for key, value in effective.items() if value != profile[key]
    )
    if mismatches:
        raise R3ValidationError(
            "Effective runtime differs from the selected profile: "
            + ", ".join(mismatches)
            + "."
        )


def evidence_identity() -> dict[str, object]:
    """Return the common dataset/corpus/metric identity for all R3 runners."""
    corpus = corpus_snapshot()
    return {
        "metric_version": R3_METRIC_VERSION,
        "dataset": {
            "path": DATASET_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": file_sha256(DATASET_PATH),
            "case_count": R3_DATASET_CASE_COUNT,
        },
        "corpus": {
            "sha256": corpus["sha256"],
            "section_count": corpus["section_count"],
        },
        "top_k": 6,
        "selected_profile": {
            "path": PROFILE_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256_file(PROFILE_PATH),
        },
    }


def _walk_published(value: object, label: str = "artifact") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_PUBLISHED_FIELDS:
                raise R3ValidationError(
                    f"Published evidence contains forbidden field {label}.{key}."
                )
            _walk_published(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_published(child, f"{label}[{index}]")
    elif isinstance(value, str) and _SECRET_PATTERN.search(value):
        raise R3ValidationError(
            f"Published evidence contains a credential-like value at {label}."
        )


def validate_published_artifact(value: Mapping[str, object]) -> None:
    """Enforce the R0 data boundary before any evidence file is written."""
    _walk_published(dict(value))


def validate_new_output_paths(*paths: Path) -> None:
    """Reject aliases, symlinks, and overwrites of versioned evidence."""
    resolved = [path.resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise R3ValidationError("Evidence outputs must use distinct paths.")
    for path in paths:
        if path.exists():
            if path.is_symlink():
                raise R3ValidationError(f"Refusing symlink output: {path}.")
            raise FileExistsError(
                f"Refusing to overwrite versioned R3 evidence: {path}."
            )
        if path.parent.resolve() != PROJECT_ROOT.resolve():
            raise R3ValidationError("Published R3 evidence must stay at project root.")


def write_versioned_pair(
    payload: Mapping[str, object],
    markdown: str,
    *,
    json_path: Path,
    markdown_path: Path,
) -> None:
    """Atomically publish a new sanitized JSON/Markdown evidence pair."""
    validate_published_artifact(payload)
    validate_new_output_paths(json_path, markdown_path)
    json_bytes = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    markdown_bytes = (markdown.rstrip() + "\n").encode("utf-8")
    temporary_paths: list[Path] = []
    try:
        for destination, content in (
            (json_path, json_bytes),
            (markdown_path, markdown_bytes),
        ):
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                delete=False,
            ) as handle:
                handle.write(content)
                temporary = Path(handle.name)
            temporary.chmod(0o600)
            temporary_paths.append(temporary)
        temporary_paths[0].replace(json_path)
        temporary_paths[1].replace(markdown_path)
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)


def write_private_review_bundle(path: Path, payload: Mapping[str, object]) -> None:
    """Write local review material under `.cache` with owner-only access."""
    cache_root = (PROJECT_ROOT / ".cache").resolve()
    resolved_parent = path.parent.resolve()
    if cache_root != resolved_parent and cache_root not in resolved_parent.parents:
        raise R3ValidationError("Private review material must stay under .cache.")
    if path.exists() and path.is_symlink():
        raise R3ValidationError("Private review output must not be a symlink.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)

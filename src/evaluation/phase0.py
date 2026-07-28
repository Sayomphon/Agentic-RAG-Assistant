"""Enterprise Phase 0 manifest and reproducibility contract.

Phase 0 reuses the human-labelled Track A dataset rather than copying it.
This module freezes the post-Track-A source tree, corpus, complete non-secret
runtime configuration, model identifiers, and Retriever contract as a new
Enterprise baseline identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence, cast

from src.config import (
    CANDIDATE_K,
    CONTEXT_DUPLICATE_THRESHOLD,
    CONTEXT_MIN_BODY_CHARS,
    DENSE_WEIGHT,
    EMBEDDING_MODEL,
    FUSION_METHOD,
    HYBRID_MIN_COSINE,
    MAX_CONTEXT_CHARS,
    MAX_SEARCH_ATTEMPTS,
    MIN_COSINE,
    MIN_MATCHED_TERMS,
    MIN_RELATIVE_SCORE,
    MIN_SCORE,
    MODEL_NAME,
    RERANKER_BATCH_SIZE,
    RERANKER_ENABLED,
    RERANKER_LOCAL_FILES_ONLY,
    RERANKER_MAX_CANDIDATES,
    RERANKER_MAX_LENGTH,
    RERANKER_MIN_SCORE,
    RERANKER_MODEL,
    RERANKER_MODEL_REVISION,
    RERANKER_TIMEOUT_SECONDS,
    RRF_K,
    TEMPERATURE,
    THAI_TOKENIZER_ENABLED,
    TITLE_BOOST,
    TOP_K,
)
from src.evaluation.baseline_dataset import (
    DATASET_PATH,
    DATASET_VERSION,
    BaselineCase,
    file_sha256,
    validate_baseline_cases,
)
from src.evaluation.baseline_support import (
    PROJECT_ROOT,
    corpus_snapshot,
)
from src.retrievers.base import RETRIEVER_CONTRACT_VERSION, load_chunks

PHASE0_BASELINE_ID = "enterprise-phase0-v1"
PHASE0_SCHEMA_VERSION = "enterprise-phase0-manifest-v1"
PHASE0_MANIFEST_PATH = (
    Path(__file__).resolve().parent
    / "datasets"
    / "enterprise_phase0_v1.manifest.json"
)
PHASE0_RESULTS_JSON_PATH = PROJECT_ROOT / "phase0_baseline_results.json"
PHASE0_RESULTS_MARKDOWN_PATH = PROJECT_ROOT / "phase0_baseline_results.md"

_SOURCE_FILES = (
    Path(".env.example"),
    Path("app.py"),
    Path("main.py"),
    Path("requirements-dev.txt"),
    Path("requirements.txt"),
    Path("docs/RETRIEVER_CONTRACT.md"),
)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_MAX_MANIFEST_BYTES = 1_000_000
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "baseline_id",
    "created_at",
    "retriever_contract_version",
    "dataset",
    "corpus",
    "source_tree",
    "runtime_config",
    "evaluation_policy",
}
_RUNTIME_CONFIG_FIELDS = {
    "serving",
    "keyword",
    "dense",
    "fusion",
    "reranker",
    "context",
    "generation",
}
_FORBIDDEN_SECRET_FIELDS = {
    "access_token",
    "api_key",
    "openai_api_key",
    "password",
    "refresh_token",
    "secret",
}


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject ambiguous JSON objects instead of silently keeping the last key."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Phase 0 manifest repeats JSON key {key!r}.")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"{label} must be a JSON object with string keys.")
    return cast(dict[str, object], value)


def _require_exact_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} fields are invalid; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}."
        )


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer.")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _HASH_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _safe_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty path.")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must stay within the project.")
    return value


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{label} must be a list of non-empty strings.")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must not contain duplicates.")
    return cast(list[str], value)


def _distribution(
    value: object,
    *,
    case_count: int,
    label: str,
) -> dict[str, object]:
    distribution = _mapping(value, label)
    if not distribution or any(
        not key.strip() or type(count) is not int or count <= 0
        for key, count in distribution.items()
    ):
        raise ValueError(f"{label} must contain positive integer counts.")
    if sum(cast(int, count) for count in distribution.values()) != case_count:
        raise ValueError(f"{label} counts must sum to dataset.case_count.")
    return distribution


def _validate_snapshot(
    value: object,
    *,
    label: str,
    file_count_field: str,
    item_count_field: str | None = None,
) -> dict[str, object]:
    snapshot = _mapping(value, label)
    required = {
        "algorithm",
        "sha256",
        file_count_field,
        "total_bytes",
    }
    if item_count_field is not None:
        required.add(item_count_field)
    files_field = "source_files" if label == "corpus" else "files"
    required.add(files_field)
    _require_exact_fields(snapshot, required, label)

    if snapshot["algorithm"] != (
        "sha256(length-prefixed-relative-path-and-bytes-v1)"
    ):
        raise ValueError(f"{label}.algorithm is unsupported.")
    _sha256(snapshot["sha256"], f"{label}.sha256")
    file_count = _positive_int(
        snapshot[file_count_field],
        f"{label}.{file_count_field}",
    )
    _positive_int(snapshot["total_bytes"], f"{label}.total_bytes")
    files = _string_list(snapshot[files_field], f"{label}.{files_field}")
    if files != sorted(files) or len(files) != file_count:
        raise ValueError(
            f"{label}.{files_field} must be sorted and match {file_count_field}."
        )
    for position, path in enumerate(files):
        _safe_relative_path(path, f"{label}.{files_field}[{position}]")
    if item_count_field is not None:
        _positive_int(
            snapshot[item_count_field],
            f"{label}.{item_count_field}",
        )
    return snapshot


def _all_mapping_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            *(str(key).lower() for key in value),
            *(
                nested
                for child in value.values()
                for nested in _all_mapping_keys(child)
            ),
        }
    if isinstance(value, list):
        return {
            nested
            for child in value
            for nested in _all_mapping_keys(child)
        }
    return set()


def validate_frozen_phase0_manifest(
    value: object,
) -> dict[str, object]:
    """Validate historical artifact integrity without reading current sources."""
    manifest = _mapping(value, "manifest")
    _require_exact_fields(manifest, _TOP_LEVEL_FIELDS, "manifest")
    if manifest["schema_version"] != PHASE0_SCHEMA_VERSION:
        raise ValueError("manifest.schema_version is unsupported.")
    if manifest["baseline_id"] != PHASE0_BASELINE_ID:
        raise ValueError("manifest.baseline_id is unsupported.")
    try:
        date.fromisoformat(str(manifest["created_at"]))
    except ValueError as exc:
        raise ValueError("manifest.created_at must be an ISO date.") from exc
    contract_version = manifest["retriever_contract_version"]
    if not isinstance(contract_version, str) or not _SEMVER_PATTERN.fullmatch(
        contract_version
    ):
        raise ValueError("manifest.retriever_contract_version must be SemVer.")

    dataset = _mapping(manifest["dataset"], "dataset")
    _require_exact_fields(
        dataset,
        {
            "version",
            "file",
            "sha256",
            "case_count",
            "category_distribution",
            "language_distribution",
        },
        "dataset",
    )
    if not isinstance(dataset["version"], str) or not dataset["version"].strip():
        raise ValueError("dataset.version must be a non-empty string.")
    _safe_relative_path(dataset["file"], "dataset.file")
    _sha256(dataset["sha256"], "dataset.sha256")
    case_count = _positive_int(dataset["case_count"], "dataset.case_count")
    _distribution(
        dataset["category_distribution"],
        case_count=case_count,
        label="dataset.category_distribution",
    )
    _distribution(
        dataset["language_distribution"],
        case_count=case_count,
        label="dataset.language_distribution",
    )

    _validate_snapshot(
        manifest["corpus"],
        label="corpus",
        file_count_field="source_file_count",
        item_count_field="section_count",
    )
    _validate_snapshot(
        manifest["source_tree"],
        label="source_tree",
        file_count_field="file_count",
    )

    runtime_config = _mapping(manifest["runtime_config"], "runtime_config")
    _require_exact_fields(
        runtime_config,
        _RUNTIME_CONFIG_FIELDS,
        "runtime_config",
    )
    for section_name, section in runtime_config.items():
        if not _mapping(section, f"runtime_config.{section_name}"):
            raise ValueError(
                f"runtime_config.{section_name} must not be empty."
            )

    policy = _mapping(manifest["evaluation_policy"], "evaluation_policy")
    _require_exact_fields(
        policy,
        {
            "default_modes",
            "external_modes",
            "top_k",
            "query_embeddings_require_explicit_flag",
            "answer_evaluation_requires_explicit_flag",
            "reports_store_raw_queries",
            "reports_store_document_bodies",
        },
        "evaluation_policy",
    )
    default_modes = _string_list(
        policy["default_modes"],
        "evaluation_policy.default_modes",
    )
    external_modes = _string_list(
        policy["external_modes"],
        "evaluation_policy.external_modes",
    )
    if set(default_modes) & set(external_modes):
        raise ValueError("Evaluation mode groups must be disjoint.")
    _positive_int(policy["top_k"], "evaluation_policy.top_k")
    for field in (
        "query_embeddings_require_explicit_flag",
        "answer_evaluation_requires_explicit_flag",
    ):
        if policy[field] is not True:
            raise ValueError(f"evaluation_policy.{field} must be true.")
    for field in (
        "reports_store_raw_queries",
        "reports_store_document_bodies",
    ):
        if policy[field] is not False:
            raise ValueError(f"evaluation_policy.{field} must be false.")

    secret_fields = _all_mapping_keys(manifest) & _FORBIDDEN_SECRET_FIELDS
    if secret_fields:
        raise ValueError(
            f"Manifest contains forbidden secret fields: {sorted(secret_fields)}."
        )
    return manifest


def load_frozen_phase0_manifest(
    path: Path = PHASE0_MANIFEST_PATH,
) -> dict[str, object]:
    """Load and structurally validate the historical manifest only."""
    if not path.is_file():
        raise FileNotFoundError(f"Phase 0 manifest not found: {path}.")
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("Phase 0 manifest exceeds the safe size limit.")
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    return validate_frozen_phase0_manifest(payload)


def phase0_config_snapshot() -> dict[str, object]:
    """Return every non-secret setting that can affect Phase 0 behavior."""
    return {
        "serving": {
            "top_k": TOP_K,
            "candidate_k": CANDIDATE_K,
            "max_search_attempts": MAX_SEARCH_ATTEMPTS,
            "max_context_chars": MAX_CONTEXT_CHARS,
        },
        "keyword": {
            "min_score": MIN_SCORE,
            "min_matched_terms": MIN_MATCHED_TERMS,
            "min_relative_score": MIN_RELATIVE_SCORE,
            "title_boost": TITLE_BOOST,
            "thai_tokenizer_enabled": THAI_TOKENIZER_ENABLED,
        },
        "dense": {
            "embedding_model": EMBEDDING_MODEL,
            "min_cosine": MIN_COSINE,
            "hybrid_min_cosine": HYBRID_MIN_COSINE,
        },
        "fusion": {
            "method": FUSION_METHOD,
            "rrf_k": RRF_K,
            "dense_weight": DENSE_WEIGHT,
        },
        "reranker": {
            "enabled": RERANKER_ENABLED,
            "model": RERANKER_MODEL,
            "model_revision": RERANKER_MODEL_REVISION,
            "batch_size": RERANKER_BATCH_SIZE,
            "timeout_seconds": RERANKER_TIMEOUT_SECONDS,
            "max_candidates": RERANKER_MAX_CANDIDATES,
            "max_length": RERANKER_MAX_LENGTH,
            "min_score": RERANKER_MIN_SCORE,
            "local_files_only": RERANKER_LOCAL_FILES_ONLY,
        },
        "context": {
            "duplicate_threshold": CONTEXT_DUPLICATE_THRESHOLD,
            "min_body_chars": CONTEXT_MIN_BODY_CHARS,
        },
        "generation": {
            "model": MODEL_NAME,
            "temperature": TEMPERATURE,
        },
    }


def _phase0_source_files() -> list[Path]:
    """Return the auditable source set covered by the Phase 0 fingerprint."""
    dynamic_files = [
        *PROJECT_ROOT.glob("src/**/*.py"),
        *PROJECT_ROOT.glob("tests/**/*.py"),
    ]
    fixed_files = [PROJECT_ROOT / path for path in _SOURCE_FILES]
    files = sorted(
        {path.resolve() for path in [*fixed_files, *dynamic_files] if path.is_file()},
        key=lambda path: path.relative_to(PROJECT_ROOT).as_posix(),
    )
    if not files:
        raise RuntimeError("Phase 0 source fingerprint has no input files.")
    return files


def source_tree_snapshot() -> dict[str, object]:
    """Hash code, tests, contract docs, and dependency/config templates."""
    digest = hashlib.sha256()
    files = _phase0_source_files()
    total_bytes = 0
    relative_names: list[str] = []

    for path in files:
        relative_name = path.relative_to(PROJECT_ROOT).as_posix()
        content = path.read_bytes()
        encoded_name = relative_name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        relative_names.append(relative_name)
        total_bytes += len(content)

    return {
        "algorithm": "sha256(length-prefixed-relative-path-and-bytes-v1)",
        "sha256": digest.hexdigest(),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": relative_names,
    }


def expected_phase0_manifest(
    cases: Sequence[BaselineCase],
) -> dict[str, object]:
    """Build the exact immutable identity expected by the Phase 0 runner."""
    chunks = load_chunks()
    category_distribution = validate_baseline_cases(
        cases,
        valid_titles={chunk.title for chunk in chunks},
    )
    language_distribution: dict[str, int] = {}
    for case in cases:
        language = case["language"]
        language_distribution[language] = (
            language_distribution.get(language, 0) + 1
        )

    return {
        "schema_version": PHASE0_SCHEMA_VERSION,
        "baseline_id": PHASE0_BASELINE_ID,
        "created_at": "2026-07-28",
        "retriever_contract_version": RETRIEVER_CONTRACT_VERSION,
        "dataset": {
            "version": DATASET_VERSION,
            "file": DATASET_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": file_sha256(DATASET_PATH),
            "case_count": len(cases),
            "category_distribution": category_distribution,
            "language_distribution": language_distribution,
        },
        "corpus": corpus_snapshot(),
        "source_tree": source_tree_snapshot(),
        "runtime_config": phase0_config_snapshot(),
        "evaluation_policy": {
            "default_modes": ["keyword"],
            "external_modes": ["semantic", "hybrid"],
            "top_k": TOP_K,
            "query_embeddings_require_explicit_flag": True,
            "answer_evaluation_requires_explicit_flag": True,
            "reports_store_raw_queries": False,
            "reports_store_document_bodies": False,
        },
    }


def write_phase0_manifest(
    cases: Sequence[BaselineCase],
    *,
    path: Path = PHASE0_MANIFEST_PATH,
) -> dict[str, object]:
    """Create the manifest once; refuse to overwrite frozen evidence."""
    if path.exists():
        raise FileExistsError(
            f"Phase 0 manifest already exists: {path}. "
            "Version a new baseline instead of overwriting it."
        )
    payload = expected_phase0_manifest(cases)
    validate_frozen_phase0_manifest(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return payload


def verify_phase0_manifest(
    cases: Sequence[BaselineCase],
    *,
    path: Path = PHASE0_MANIFEST_PATH,
) -> dict[str, object]:
    """Fail closed when frozen code, data, corpus, or config has changed."""
    recorded = load_frozen_phase0_manifest(path)
    current = expected_phase0_manifest(cases)
    if recorded != current:
        raise ValueError(
            "Phase 0 manifest does not match the current source tree, dataset, "
            "corpus, contract, or runtime config. Review the change and create "
            "a new version; never overwrite the frozen baseline."
        )
    return recorded

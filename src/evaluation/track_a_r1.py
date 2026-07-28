"""R1 comparative baseline orchestration and evidence validation.

The current branch owns orchestration, validation, comparison, and artifact
writing. Retrieval itself runs in an isolated detached worktree at
``5e8537b`` through ``legacy_step1_worker.py``. This separation preserves the
historical implementation and prevents the old runner from overwriting
versioned evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

from src.evaluation.baseline_support import (
    PROJECT_ROOT,
    run_contract_check,
    run_local_checks,
)
from src.evaluation.track_a_closure import (
    TRACK_A_CLOSURE_MANIFEST_PATH,
    load_track_a_closure_manifest,
    verify_track_a_r0_freeze,
    verify_track_a_r0_repository_state,
)

R1_SCHEMA_VERSION = "track-a-pre-upgrade-baseline-v2"
R1_BASELINE_ID = "track-a-pre-upgrade-v2"
R1_RESULTS_JSON_PATH = PROJECT_ROOT / "track_a_pre_upgrade_baseline_v2.json"
R1_RESULTS_MARKDOWN_PATH = PROJECT_ROOT / "track_a_pre_upgrade_baseline_v2.md"
LEGACY_WORKER_PATH = (
    PROJECT_ROOT / "src" / "evaluation" / "legacy_step1_worker.py"
)
PHASE0_RESULTS_PATH = PROJECT_ROOT / "phase0_baseline_results.json"

_WORKER_SCHEMA_VERSION = "track-a-legacy-step1-worker-v1"
_MAX_JSON_BYTES = 2_000_000
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")
_SUPPORTED_MODES = ("keyword", "semantic", "hybrid")
_REQUIRED_METRICS = {
    "hit_rate_at_k",
    "recall_at_k",
    "mrr",
    "false_positive_rate",
    "not_found_discipline",
    "latency_avg_ms",
    "latency_p50_ms",
    "latency_p95_ms",
}
_CASE_FIELDS = {
    "case_id",
    "category",
    "expected_titles",
    "retrieved_titles",
    "hit",
    "recall",
    "reciprocal_rank",
    "false_positive",
    "latency_ms",
}
_FORBIDDEN_FIELDS = {
    "access_token",
    "api_key",
    "document_body",
    "openai_api_key",
    "password",
    "prompt",
    "query",
    "raw_environment",
    "refresh_token",
    "secret",
}
_WORKER_ENV_ALLOWLIST = {
    "ALL_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "NO_PROXY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "TMPDIR",
}
_LEGACY_CONFIG = {
    "DENSE_WEIGHT": "0.5",
    "EMBEDDING_MODEL": "text-embedding-3-small",
    "FUSION_METHOD": "rrf",
    "KB_PATH": "knowledge_base.txt",
    "MAX_SEARCH_ATTEMPTS": "3",
    "MIN_COSINE": "0.38",
    "MIN_MATCHED_TERMS": "2",
    "MIN_RELATIVE_SCORE": "0.55",
    "MIN_SCORE": "2.0",
    "MODEL_NAME": "gpt-5-mini",
    "RRF_K": "60",
    "SEARCH_MODE": "keyword",
    "TEMPERATURE": "0",
    "TITLE_BOOST": "1.5",
    "TOP_K": "4",
}


class R1ValidationError(ValueError):
    """Raised when evidence is structurally invalid or not comparable."""


class R1ExecutionError(RuntimeError):
    """Raised for a sanitized local/provider execution failure."""


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise R1ValidationError(f"R1 evidence repeats JSON key {key!r}.")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise R1ValidationError(
            f"{label} must be a JSON object with string keys."
        )
    return cast(dict[str, object], value)


def _require_exact_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise R1ValidationError(
            f"{label} fields are invalid; "
            f"missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}."
        )


def _finite_number(value: object, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise R1ValidationError(f"{label} must be a finite number.")
    return float(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_digest_record(
    value: object,
    *,
    label: str,
    expected_path: str | None = None,
) -> dict[str, object]:
    record = _mapping(value, label)
    _require_exact_fields(record, {"path", "sha256"}, label)
    path = record["path"]
    if not isinstance(path, str) or not path.strip():
        raise R1ValidationError(f"{label}.path must be non-empty.")
    parsed_path = Path(path)
    if parsed_path.is_absolute() or ".." in parsed_path.parts:
        raise R1ValidationError(f"{label}.path must stay within the project.")
    if expected_path is not None and path != expected_path:
        raise R1ValidationError(f"{label}.path is unsupported.")
    digest = record["sha256"]
    if not isinstance(digest, str) or not _HASH_PATTERN.fullmatch(digest):
        raise R1ValidationError(f"{label}.sha256 must be SHA-256.")
    return record


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


def _load_json_bytes(content: bytes, label: str) -> dict[str, object]:
    if len(content) > _MAX_JSON_BYTES:
        raise R1ValidationError(f"{label} exceeds the safe size limit.")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R1ValidationError(f"{label} is not valid UTF-8 JSON.") from exc
    return _mapping(value, label)


def _validate_metrics(value: object, label: str) -> dict[str, object]:
    metrics = _mapping(value, label)
    _require_exact_fields(metrics, _REQUIRED_METRICS, label)
    for name, metric in metrics.items():
        number = _finite_number(metric, f"{label}.{name}")
        if name.startswith("latency_"):
            if number < 0:
                raise R1ValidationError(f"{label}.{name} must be non-negative.")
        elif not 0.0 <= number <= 1.0:
            raise R1ValidationError(f"{label}.{name} must be within [0, 1].")
    return metrics


def _validate_case(
    value: object,
    *,
    label: str,
    top_k: int,
) -> dict[str, object]:
    case = _mapping(value, label)
    _require_exact_fields(case, _CASE_FIELDS, label)
    case_id = case["case_id"]
    category = case["category"]
    if not isinstance(case_id, str) or not case_id.strip():
        raise R1ValidationError(f"{label}.case_id must be non-empty.")
    if not isinstance(category, str) or not category.strip():
        raise R1ValidationError(f"{label}.category must be non-empty.")
    for field in ("expected_titles", "retrieved_titles"):
        titles = case[field]
        if not isinstance(titles, list) or any(
            not isinstance(title, str) or not title.strip() for title in titles
        ):
            raise R1ValidationError(f"{label}.{field} is invalid.")
        if len(titles) != len(set(titles)):
            raise R1ValidationError(f"{label}.{field} contains duplicates.")
    retrieved = cast(list[str], case["retrieved_titles"])
    if len(retrieved) > top_k:
        raise R1ValidationError(f"{label}.retrieved_titles exceeds top_k.")
    for field in ("hit", "false_positive"):
        if type(case[field]) is not bool:
            raise R1ValidationError(f"{label}.{field} must be boolean.")
    for field in ("recall", "reciprocal_rank"):
        metric = case[field]
        if metric is not None:
            number = _finite_number(metric, f"{label}.{field}")
            if not 0.0 <= number <= 1.0:
                raise R1ValidationError(
                    f"{label}.{field} must be within [0, 1]."
                )
    if _finite_number(case["latency_ms"], f"{label}.latency_ms") < 0:
        raise R1ValidationError(f"{label}.latency_ms must be non-negative.")

    expected = cast(list[str], case["expected_titles"])
    computed_hit = any(title in retrieved for title in expected)
    computed_false_positive = not expected and bool(retrieved)
    if case["hit"] is not computed_hit:
        raise R1ValidationError(f"{label}.hit is inconsistent with titles.")
    if case["false_positive"] is not computed_false_positive:
        raise R1ValidationError(
            f"{label}.false_positive is inconsistent with titles."
        )
    if expected:
        if case["recall"] is None or case["reciprocal_rank"] is None:
            raise R1ValidationError(
                f"{label} answerable metrics must not be null."
            )
        computed_recall = (
            sum(title in retrieved for title in expected) / len(expected)
        )
        computed_rank = 0.0
        for rank, title in enumerate(retrieved, start=1):
            if title in expected:
                computed_rank = 1.0 / rank
                break
        if not math.isclose(
            float(cast(float, case["recall"])),
            computed_recall,
            abs_tol=1e-12,
        ):
            raise R1ValidationError(
                f"{label}.recall is inconsistent with titles."
            )
        if not math.isclose(
            float(cast(float, case["reciprocal_rank"])),
            computed_rank,
            abs_tol=1e-12,
        ):
            raise R1ValidationError(
                f"{label}.reciprocal_rank is inconsistent with titles."
            )
    elif case["recall"] is not None or case["reciprocal_rank"] is not None:
        raise R1ValidationError(
            f"{label} negative metrics must be null."
        )
    return case


def _validate_health(value: object, label: str) -> dict[str, object]:
    health = _mapping(value, label)
    _require_exact_fields(
        health,
        {
            "implementation",
            "source",
            "query_failure_count",
            "fallback_count",
        },
        label,
    )
    for field in ("implementation", "source"):
        if not isinstance(health[field], str) or not health[field]:
            raise R1ValidationError(f"{label}.{field} must be non-empty.")
    for field in ("query_failure_count", "fallback_count"):
        if health[field] != 0:
            raise R1ValidationError(
                f"{label}.{field} must be zero for official evidence."
            )
    return health


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _metrics_from_cases(
    cases: Sequence[Mapping[str, object]],
) -> dict[str, float]:
    answerable = [
        case for case in cases if cast(list[str], case["expected_titles"])
    ]
    negatives = [
        case for case in cases if not cast(list[str], case["expected_titles"])
    ]
    latencies = [float(case["latency_ms"]) for case in cases]
    false_positive_rate = (
        sum(bool(case["false_positive"]) for case in negatives)
        / len(negatives)
    )
    return {
        "hit_rate_at_k": (
            sum(bool(case["hit"]) for case in answerable) / len(answerable)
        ),
        "recall_at_k": (
            sum(float(case["recall"]) for case in answerable)
            / len(answerable)
        ),
        "mrr": (
            sum(float(case["reciprocal_rank"]) for case in answerable)
            / len(answerable)
        ),
        "false_positive_rate": false_positive_rate,
        "not_found_discipline": 1.0 - false_positive_rate,
        "latency_avg_ms": sum(latencies) / len(latencies),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


def _require_numeric_mappings_equal(
    recorded: Mapping[str, object],
    computed: Mapping[str, object],
    label: str,
) -> None:
    if set(recorded) != set(computed):
        raise R1ValidationError(f"{label} fields are inconsistent.")
    for field in recorded:
        recorded_value = recorded[field]
        computed_value = computed[field]
        if isinstance(computed_value, dict):
            if not isinstance(recorded_value, dict):
                raise R1ValidationError(f"{label}.{field} is inconsistent.")
            _require_numeric_mappings_equal(
                recorded_value,
                computed_value,
                f"{label}.{field}",
            )
            continue
        if type(computed_value) is int:
            if recorded_value != computed_value:
                raise R1ValidationError(f"{label}.{field} is inconsistent.")
            continue
        if not math.isclose(
            _finite_number(recorded_value, f"{label}.{field}"),
            float(computed_value),
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise R1ValidationError(f"{label}.{field} is inconsistent.")


def _validate_retrieval(
    value: object,
    *,
    label: str,
    top_k: int,
) -> dict[str, object]:
    retrieval = _mapping(value, label)
    if tuple(retrieval) != _SUPPORTED_MODES:
        raise R1ValidationError(
            f"{label} must contain keyword, semantic, and hybrid in order."
        )
    reference_ids: list[str] | None = None
    for mode in _SUPPORTED_MODES:
        mode_result = _mapping(retrieval[mode], f"{label}.{mode}")
        _require_exact_fields(
            mode_result,
            {"health", "metrics", "category_metrics", "cases"},
            f"{label}.{mode}",
        )
        _validate_health(mode_result["health"], f"{label}.{mode}.health")
        _validate_metrics(mode_result["metrics"], f"{label}.{mode}.metrics")
        categories = _mapping(
            mode_result["category_metrics"],
            f"{label}.{mode}.category_metrics",
        )
        if not categories:
            raise R1ValidationError(
                f"{label}.{mode}.category_metrics must not be empty."
            )
        cases = mode_result["cases"]
        if not isinstance(cases, list) or len(cases) != 40:
            raise R1ValidationError(
                f"{label}.{mode}.cases must contain 40 cases."
            )
        validated = [
            _validate_case(
                case,
                label=f"{label}.{mode}.cases[{index}]",
                top_k=top_k,
            )
            for index, case in enumerate(cases)
        ]
        case_ids = [cast(str, case["case_id"]) for case in validated]
        if len(case_ids) != len(set(case_ids)):
            raise R1ValidationError(f"{label}.{mode} repeats case IDs.")
        if reference_ids is None:
            reference_ids = case_ids
        elif case_ids != reference_ids:
            raise R1ValidationError(
                f"{label}.{mode} case order differs from keyword."
            )
        _require_numeric_mappings_equal(
            cast(Mapping[str, object], mode_result["metrics"]),
            _metrics_from_cases(validated),
            f"{label}.{mode}.metrics",
        )
        _require_numeric_mappings_equal(
            categories,
            _category_metrics_from_cases(validated),
            f"{label}.{mode}.category_metrics",
        )
    return retrieval


def validate_legacy_worker_payload(
    value: object,
    *,
    expected_top_k: int,
    require_checks: bool,
) -> dict[str, object]:
    """Validate one black-box result before it enters official evidence."""
    payload = _mapping(value, "worker")
    _require_exact_fields(
        payload,
        {
            "schema_version",
            "top_k",
            "manifest",
            "environment",
            "corpus_embedding_cache",
            "checks",
            "retrieval",
        },
        "worker",
    )
    if payload["schema_version"] != _WORKER_SCHEMA_VERSION:
        raise R1ValidationError("worker.schema_version is unsupported.")
    if payload["top_k"] != expected_top_k:
        raise R1ValidationError("worker.top_k does not match the request.")

    closure_manifest = load_track_a_closure_manifest()
    frozen = cast(
        Mapping[str, object],
        closure_manifest["frozen_inputs"],
    )
    frozen_dataset = cast(Mapping[str, object], frozen["dataset"])
    frozen_corpus = cast(Mapping[str, object], frozen["corpus"])
    manifest = _mapping(payload["manifest"], "worker.manifest")
    if manifest.get("dataset_sha256") != cast(
        Mapping[str, object],
        frozen_dataset["file"],
    )["sha256"]:
        raise R1ValidationError("worker dataset SHA-256 does not match R0.")
    worker_corpus = _mapping(manifest.get("corpus"), "worker.manifest.corpus")
    if worker_corpus.get("sha256") != frozen_corpus["sha256"]:
        raise R1ValidationError("worker corpus SHA-256 does not match R0.")
    if manifest.get("embedding_model") != "text-embedding-3-small":
        raise R1ValidationError("worker embedding model is unsupported.")

    cache = _mapping(
        payload["corpus_embedding_cache"],
        "worker.corpus_embedding_cache",
    )
    _require_exact_fields(
        cache,
        {"ready", "file_name", "corpus_api_call_allowed"},
        "worker.corpus_embedding_cache",
    )
    if cache["ready"] is not True or cache["corpus_api_call_allowed"] is not False:
        raise R1ValidationError(
            "worker must use a ready cache without corpus API permission."
        )

    checks = payload["checks"]
    if not isinstance(checks, list):
        raise R1ValidationError("worker.checks must be a list.")
    if require_checks:
        names = {
            check.get("name")
            for check in checks
            if isinstance(check, dict) and check.get("passed") is True
        }
        if names != {"unit_tests", "keyword_regression"}:
            raise R1ValidationError("worker local checks are incomplete.")
    elif checks:
        raise R1ValidationError("worker checks must run only once.")

    _validate_retrieval(
        payload["retrieval"],
        label="worker.retrieval",
        top_k=expected_top_k,
    )
    forbidden = _all_mapping_keys(payload) & _FORBIDDEN_FIELDS
    if forbidden:
        raise R1ValidationError(
            f"worker contains forbidden fields: {sorted(forbidden)}."
        )
    if _SECRET_PATTERN.search(json.dumps(payload, ensure_ascii=False)):
        raise R1ValidationError("worker contains a credential-like value.")
    return payload


def _run_git(
    arguments: Sequence[str],
    *,
    cwd: Path = PROJECT_ROOT,
) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise R1ExecutionError("A required Git identity check failed.")
    return result.stdout.strip()


def verify_legacy_worktree(
    legacy_root: Path,
    legacy_python: Path,
    *,
    expected_commit: str,
) -> None:
    """Require an exact detached, clean historical worktree and its venv."""
    root = legacy_root.resolve()
    if not root.is_dir():
        raise R1ValidationError("Legacy worktree does not exist.")
    top_level = Path(_run_git(["rev-parse", "--show-toplevel"], cwd=root))
    if top_level.resolve() != root:
        raise R1ValidationError("Legacy path is not the Git worktree root.")
    if _run_git(["rev-parse", "HEAD"], cwd=root) != expected_commit:
        raise R1ValidationError("Legacy worktree is at the wrong commit.")
    branch = _run_git(["branch", "--show-current"], cwd=root)
    if branch:
        raise R1ValidationError("Legacy worktree must be detached.")
    if _run_git(
        ["status", "--porcelain", "--untracked-files=all"],
        cwd=root,
    ):
        raise R1ValidationError("Legacy worktree must be clean.")

    python_path = legacy_python.absolute()
    try:
        python_path.relative_to(root)
    except ValueError as exc:
        raise R1ValidationError(
            "Legacy Python must belong to the isolated worktree."
        ) from exc
    if not python_path.is_file():
        raise R1ValidationError("Legacy Python executable does not exist.")


def _worker_environment(legacy_root: Path) -> dict[str, str]:
    """Build an allowlisted environment with frozen retrieval settings."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in _WORKER_ENV_ALLOWLIST and value
    }
    if "OPENAI_API_KEY" not in environment:
        raise R1ExecutionError("No approved OpenAI API credential is available.")
    environment.update(_LEGACY_CONFIG)
    environment.update(
        {
            "EMBEDDING_CACHE_DIR": str((PROJECT_ROOT / ".cache").resolve()),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": str(legacy_root.resolve()),
        }
    )
    return environment


def _run_legacy_worker(
    *,
    legacy_root: Path,
    legacy_python: Path,
    top_k: int,
    run_checks: bool,
) -> dict[str, object]:
    arguments = [
        str(legacy_python.absolute()),
        str(LEGACY_WORKER_PATH),
        "--top-k",
        str(top_k),
    ]
    if run_checks:
        arguments.append("--run-local-checks")
    result = subprocess.run(
        arguments,
        cwd=legacy_root,
        env=_worker_environment(legacy_root),
        check=False,
        capture_output=True,
        timeout=900,
    )
    if result.returncode != 0:
        raise R1ExecutionError(
            f"Legacy baseline worker failed for top_k={top_k}; "
            "no quality artifact was written."
        )
    payload = _load_json_bytes(result.stdout, f"legacy worker top_k={top_k}")
    return validate_legacy_worker_payload(
        payload,
        expected_top_k=top_k,
        require_checks=run_checks,
    )


def _category_metrics_from_cases(
    cases: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, float | int]]:
    categories = tuple(
        dict.fromkeys(cast(str, case["category"]) for case in cases)
    )
    output: dict[str, dict[str, float | int]] = {}
    for category in categories:
        selected = [
            case for case in cases if case["category"] == category
        ]
        if category == "negative":
            false_positive_rate = (
                sum(bool(case["false_positive"]) for case in selected)
                / len(selected)
            )
            output[category] = {
                "case_count": len(selected),
                "false_positive_rate": false_positive_rate,
                "not_found_discipline": 1.0 - false_positive_rate,
            }
            continue
        output[category] = {
            "case_count": len(selected),
            "hit_rate_at_k": (
                sum(bool(case["hit"]) for case in selected) / len(selected)
            ),
            "recall_at_k": (
                sum(float(case["recall"]) for case in selected)
                / len(selected)
            ),
            "mrr": (
                sum(float(case["reciprocal_rank"]) for case in selected)
                / len(selected)
            ),
        }
    return output


def _immutable_artifact_digest(
    closure_manifest: Mapping[str, object],
    relative_path: str,
) -> str:
    artifacts = cast(
        Sequence[Mapping[str, object]],
        closure_manifest["immutable_artifacts"],
    )
    for artifact in artifacts:
        if artifact["path"] == relative_path:
            return cast(str, artifact["sha256"])
    raise R1ValidationError(
        f"R0 does not freeze required artifact {relative_path}."
    )


def _load_post_track_a_profile(
    closure_manifest: Mapping[str, object],
) -> dict[str, object]:
    expected_digest = _immutable_artifact_digest(
        closure_manifest,
        "phase0_baseline_results.json",
    )
    if _sha256_file(PHASE0_RESULTS_PATH) != expected_digest:
        raise R1ValidationError("Enterprise Phase 0 evidence was modified.")
    phase0 = _load_json_bytes(
        PHASE0_RESULTS_PATH.read_bytes(),
        "Enterprise Phase 0 evidence",
    )
    if phase0.get("schema_version") != (
        "enterprise-phase0-baseline-report-v1"
    ):
        raise R1ValidationError("Enterprise Phase 0 schema is unsupported.")
    manifest = _mapping(phase0.get("manifest"), "phase0.manifest")
    dataset = _mapping(manifest.get("dataset"), "phase0.manifest.dataset")
    corpus = _mapping(manifest.get("corpus"), "phase0.manifest.corpus")
    frozen = cast(
        Mapping[str, object],
        closure_manifest["frozen_inputs"],
    )
    frozen_dataset = cast(Mapping[str, object], frozen["dataset"])
    frozen_corpus = cast(Mapping[str, object], frozen["corpus"])
    if dataset.get("sha256") != cast(
        Mapping[str, object],
        frozen_dataset["file"],
    )["sha256"]:
        raise R1ValidationError("Phase 0 dataset does not match R0.")
    if corpus.get("sha256") != frozen_corpus["sha256"]:
        raise R1ValidationError("Phase 0 corpus does not match R0.")

    retrieval = _mapping(phase0.get("retrieval"), "phase0.retrieval")
    sanitized: dict[str, object] = {}
    for mode in _SUPPORTED_MODES:
        result = _mapping(retrieval.get(mode), f"phase0.retrieval.{mode}")
        health = _mapping(
            result.get("health"),
            f"phase0.retrieval.{mode}.health",
        )
        if health.get("query_failure_count") != 0:
            raise R1ValidationError(f"Phase 0 {mode} has provider failures.")
        if health.get("reranker_fallback_count") != 0:
            raise R1ValidationError(f"Phase 0 {mode} has reranker fallback.")
        metrics = _validate_metrics(
            result.get("metrics"),
            f"phase0.retrieval.{mode}.metrics",
        )
        raw_cases = result.get("cases")
        if not isinstance(raw_cases, list) or len(raw_cases) != 40:
            raise R1ValidationError(f"Phase 0 {mode} must have 40 cases.")
        cases = [
            _validate_case(
                case,
                label=f"phase0.retrieval.{mode}.cases[{index}]",
                top_k=6,
            )
            for index, case in enumerate(raw_cases)
        ]
        sanitized[mode] = {
            "health": {
                "implementation": health.get("implementation"),
                "source": health.get("source"),
                "query_failure_count": 0,
                "fallback_count": 0,
            },
            "metrics": metrics,
            "category_metrics": _category_metrics_from_cases(cases),
            "cases": cases,
        }

    repository = cast(
        Mapping[str, object],
        closure_manifest["repository"],
    )
    runtime_config = _mapping(
        manifest.get("runtime_config"),
        "phase0.manifest.runtime_config",
    )
    return {
        "source_commit": repository["base_commit"],
        "top_k": 6,
        "evidence": {
            "path": "phase0_baseline_results.json",
            "sha256": expected_digest,
        },
        "runtime_config": runtime_config,
        "retrieval": sanitized,
    }


def _pre_profile(
    worker: Mapping[str, object],
    *,
    source_commit: str,
) -> dict[str, object]:
    manifest = _mapping(worker["manifest"], "worker.manifest")
    return {
        "source_commit": source_commit,
        "top_k": worker["top_k"],
        "runtime_config": manifest["retrieval_config"],
        "environment": worker["environment"],
        "checks": worker["checks"],
        "retrieval": worker["retrieval"],
    }


def _metric_deltas(
    pre_profile: Mapping[str, object],
    post_profile: Mapping[str, object],
) -> dict[str, dict[str, float]]:
    pre_retrieval = cast(
        Mapping[str, Mapping[str, object]],
        pre_profile["retrieval"],
    )
    post_retrieval = cast(
        Mapping[str, Mapping[str, object]],
        post_profile["retrieval"],
    )
    output: dict[str, dict[str, float]] = {}
    for mode in _SUPPORTED_MODES:
        pre_metrics = cast(
            Mapping[str, float],
            pre_retrieval[mode]["metrics"],
        )
        post_metrics = cast(
            Mapping[str, float],
            post_retrieval[mode]["metrics"],
        )
        output[mode] = {
            metric: float(post_metrics[metric]) - float(pre_metrics[metric])
            for metric in sorted(_REQUIRED_METRICS)
        }
    return output


def _comparison(
    *,
    pre_id: str,
    pre_profile: Mapping[str, object],
    post_id: str,
    post_profile: Mapping[str, object],
) -> dict[str, object]:
    pre_top_k = cast(int, pre_profile["top_k"])
    post_top_k = cast(int, post_profile["top_k"])
    return {
        "pre_profile": pre_id,
        "post_profile": post_id,
        "same_dataset": True,
        "same_corpus": True,
        "same_embedding_model": True,
        "same_metric_definitions": True,
        "same_top_k": pre_top_k == post_top_k,
        "pre_top_k": pre_top_k,
        "post_top_k": post_top_k,
        "metric_delta_post_minus_pre": _metric_deltas(
            pre_profile,
            post_profile,
        ),
    }


def _git_blob_digest(commit: str, relative_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise R1ExecutionError("Cannot read a required frozen Git object.")
    return _sha256_bytes(result.stdout)


def _safe_check_payload(scope: str, check: object) -> dict[str, object]:
    payload = asdict(check)
    payload["passed"] = bool(getattr(check, "passed"))
    return {"scope": scope, **payload}


def build_r1_artifact(
    *,
    legacy_root: Path,
    legacy_python: Path,
    query_embeddings_approved: bool,
) -> dict[str, object]:
    """Run R1 only after local gates and explicit external-data approval."""
    if not query_embeddings_approved:
        raise R1ExecutionError(
            "R1 semantic/hybrid evaluation requires explicit approval."
        )
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    closure_manifest = verify_track_a_r0_freeze()
    verify_track_a_r0_repository_state(closure_manifest)
    repository = cast(
        Mapping[str, object],
        closure_manifest["repository"],
    )
    pre_upgrade_commit = cast(str, repository["pre_upgrade_commit"])
    verify_legacy_worktree(
        legacy_root,
        legacy_python,
        expected_commit=pre_upgrade_commit,
    )

    current_checks = [
        *run_local_checks(),
        run_contract_check(),
    ]
    pre_default_worker = _run_legacy_worker(
        legacy_root=legacy_root,
        legacy_python=legacy_python,
        top_k=4,
        run_checks=True,
    )
    pre_controlled_worker = _run_legacy_worker(
        legacy_root=legacy_root,
        legacy_python=legacy_python,
        top_k=6,
        run_checks=False,
    )
    post_profile = _load_post_track_a_profile(closure_manifest)
    pre_default = _pre_profile(
        pre_default_worker,
        source_commit=pre_upgrade_commit,
    )
    pre_controlled = _pre_profile(
        pre_controlled_worker,
        source_commit=pre_upgrade_commit,
    )

    source_commit = _run_git(["rev-parse", "HEAD"])
    worker_digest = _git_blob_digest(
        source_commit,
        "src/evaluation/legacy_step1_worker.py",
    )
    profiles = {
        "pre_track_a_operational_default": pre_default,
        "pre_track_a_controlled_top_k_6": pre_controlled,
        "post_track_a_selected_top_k_6": post_profile,
    }
    checks = [
        *(
            _safe_check_payload("current", check)
            for check in current_checks
        ),
        *(
            {"scope": "legacy", **cast(dict[str, object], check)}
            for check in cast(list[object], pre_default_worker["checks"])
        ),
    ]
    artifact = {
        "schema_version": R1_SCHEMA_VERSION,
        "baseline_id": R1_BASELINE_ID,
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "provenance": {
            "evaluation_commit": source_commit,
            "pre_upgrade_commit": pre_upgrade_commit,
            "post_track_a_commit": repository["base_commit"],
            "working_tree_clean": True,
            "legacy_worktree_clean": True,
            "dataset_sha256": cast(
                Mapping[str, object],
                cast(
                    Mapping[str, object],
                    closure_manifest["frozen_inputs"],
                )["dataset"],
            )["file"]["sha256"],
            "corpus_sha256": cast(
                Mapping[str, object],
                closure_manifest["frozen_inputs"],
            )["corpus"]["sha256"],
            "requirements": [
                {
                    "path": "requirements-dev.txt",
                    "sha256": _git_blob_digest(
                        pre_upgrade_commit,
                        "requirements-dev.txt",
                    ),
                },
                {
                    "path": "requirements.txt",
                    "sha256": _git_blob_digest(
                        pre_upgrade_commit,
                        "requirements.txt",
                    ),
                },
            ],
            "worker": {
                "path": "src/evaluation/legacy_step1_worker.py",
                "sha256": worker_digest,
            },
            "closure_manifest": {
                "path": TRACK_A_CLOSURE_MANIFEST_PATH.relative_to(
                    PROJECT_ROOT
                ).as_posix(),
                "sha256": _sha256_file(TRACK_A_CLOSURE_MANIFEST_PATH),
            },
            "commands": [
                "venv/bin/python -m src.evaluation.run_track_a_closure "
                "--run-r1 --legacy-worktree <detached-worktree> "
                "--legacy-python <detached-worktree>/venv/bin/python "
                "--allow-query-embeddings",
                "<legacy-python> <remediation-root>/src/evaluation/"
                "legacy_step1_worker.py --top-k 4 --run-local-checks",
                "<legacy-python> <remediation-root>/src/evaluation/"
                "legacy_step1_worker.py --top-k 6",
            ],
            "provider_failure_count": 0,
            "fallback_count": 0,
        },
        "data_boundary": {
            "query_embeddings_approved": True,
            "corpus_embedding_cache_ready": True,
            "corpus_embeddings_approved": False,
            "answer_evaluation_approved": False,
            "raw_queries_stored": False,
            "document_bodies_stored": False,
            "prompts_stored": False,
            "credentials_stored": False,
        },
        "checks": checks,
        "profiles": profiles,
        "comparisons": {
            "operational_default": _comparison(
                pre_id="pre_track_a_operational_default",
                pre_profile=pre_default,
                post_id="post_track_a_selected_top_k_6",
                post_profile=post_profile,
            ),
            "controlled_top_k_6": _comparison(
                pre_id="pre_track_a_controlled_top_k_6",
                pre_profile=pre_controlled,
                post_id="post_track_a_selected_top_k_6",
                post_profile=post_profile,
            ),
        },
    }
    return validate_r1_artifact(artifact)


def validate_r1_artifact(value: object) -> dict[str, object]:
    """Fail closed on incomplete, degraded, or incomparable R1 evidence."""
    artifact = _mapping(value, "artifact")
    _require_exact_fields(
        artifact,
        {
            "schema_version",
            "baseline_id",
            "generated_at",
            "provenance",
            "data_boundary",
            "checks",
            "profiles",
            "comparisons",
        },
        "artifact",
    )
    if artifact["schema_version"] != R1_SCHEMA_VERSION:
        raise R1ValidationError("artifact.schema_version is unsupported.")
    if artifact["baseline_id"] != R1_BASELINE_ID:
        raise R1ValidationError("artifact.baseline_id is unsupported.")
    try:
        datetime.fromisoformat(str(artifact["generated_at"]))
    except ValueError as exc:
        raise R1ValidationError(
            "artifact.generated_at must be ISO-8601."
        ) from exc

    provenance = _mapping(artifact["provenance"], "artifact.provenance")
    _require_exact_fields(
        provenance,
        {
            "evaluation_commit",
            "pre_upgrade_commit",
            "post_track_a_commit",
            "working_tree_clean",
            "legacy_worktree_clean",
            "dataset_sha256",
            "corpus_sha256",
            "requirements",
            "worker",
            "closure_manifest",
            "commands",
            "provider_failure_count",
            "fallback_count",
        },
        "artifact.provenance",
    )
    for field in (
        "evaluation_commit",
        "pre_upgrade_commit",
        "post_track_a_commit",
    ):
        commit = provenance[field]
        if not isinstance(commit, str) or not _COMMIT_PATTERN.fullmatch(commit):
            raise R1ValidationError(
                f"artifact.provenance.{field} must be a full Git commit."
            )
    for field in ("dataset_sha256", "corpus_sha256"):
        digest = provenance[field]
        if not isinstance(digest, str) or not _HASH_PATTERN.fullmatch(digest):
            raise R1ValidationError(
                f"artifact.provenance.{field} must be SHA-256."
            )
    for field in ("working_tree_clean", "legacy_worktree_clean"):
        if provenance[field] is not True:
            raise R1ValidationError(f"artifact.provenance.{field} must be true.")
    for field in ("provider_failure_count", "fallback_count"):
        if provenance[field] != 0:
            raise R1ValidationError(f"artifact.provenance.{field} must be zero.")
    commands = provenance["commands"]
    if (
        not isinstance(commands, list)
        or not commands
        or any(
            not isinstance(command, str) or not command.strip()
            for command in commands
        )
        or len(commands) != len(set(commands))
    ):
        raise R1ValidationError("artifact.provenance.commands is required.")
    requirements = provenance["requirements"]
    if not isinstance(requirements, list) or len(requirements) != 2:
        raise R1ValidationError(
            "artifact.provenance.requirements must contain two files."
        )
    requirement_records = [
        _validate_digest_record(
            requirement,
            label=f"artifact.provenance.requirements[{index}]",
        )
        for index, requirement in enumerate(requirements)
    ]
    requirement_paths = [
        cast(str, requirement["path"])
        for requirement in requirement_records
    ]
    if requirement_paths != ["requirements-dev.txt", "requirements.txt"]:
        raise R1ValidationError(
            "artifact.provenance.requirements paths are invalid."
        )
    _validate_digest_record(
        provenance["worker"],
        label="artifact.provenance.worker",
        expected_path="src/evaluation/legacy_step1_worker.py",
    )
    closure_record = _validate_digest_record(
        provenance["closure_manifest"],
        label="artifact.provenance.closure_manifest",
        expected_path=(
            "src/evaluation/datasets/track_a_closure_v2.manifest.json"
        ),
    )

    closure_manifest = load_track_a_closure_manifest()
    repository = cast(
        Mapping[str, object],
        closure_manifest["repository"],
    )
    frozen = cast(
        Mapping[str, object],
        closure_manifest["frozen_inputs"],
    )
    frozen_dataset = cast(Mapping[str, object], frozen["dataset"])
    frozen_corpus = cast(Mapping[str, object], frozen["corpus"])
    if provenance["pre_upgrade_commit"] != repository["pre_upgrade_commit"]:
        raise R1ValidationError("Pre-upgrade commit does not match R0.")
    if provenance["post_track_a_commit"] != repository["base_commit"]:
        raise R1ValidationError("Post-Track-A commit does not match R0.")
    if provenance["dataset_sha256"] != cast(
        Mapping[str, object],
        frozen_dataset["file"],
    )["sha256"]:
        raise R1ValidationError("Dataset SHA-256 does not match R0.")
    if provenance["corpus_sha256"] != frozen_corpus["sha256"]:
        raise R1ValidationError("Corpus SHA-256 does not match R0.")
    if closure_record["sha256"] != _sha256_file(
        TRACK_A_CLOSURE_MANIFEST_PATH
    ):
        raise R1ValidationError("Closure manifest SHA-256 is inconsistent.")

    boundary = _mapping(artifact["data_boundary"], "artifact.data_boundary")
    expected_boundary = {
        "query_embeddings_approved": True,
        "corpus_embedding_cache_ready": True,
        "corpus_embeddings_approved": False,
        "answer_evaluation_approved": False,
        "raw_queries_stored": False,
        "document_bodies_stored": False,
        "prompts_stored": False,
        "credentials_stored": False,
    }
    if boundary != expected_boundary:
        raise R1ValidationError("artifact.data_boundary is invalid.")

    checks = artifact["checks"]
    if not isinstance(checks, list) or len(checks) != 5:
        raise R1ValidationError("artifact.checks must contain five gates.")
    if any(
        not isinstance(check, dict) or check.get("passed") is not True
        for check in checks
    ):
        raise R1ValidationError("All artifact checks must pass.")
    check_names = {
        (check.get("scope"), check.get("name"))
        for check in checks
        if isinstance(check, dict)
    }
    expected_checks = {
        ("current", "unit_tests"),
        ("current", "keyword_regression"),
        ("current", "retriever_contract"),
        ("legacy", "unit_tests"),
        ("legacy", "keyword_regression"),
    }
    if check_names != expected_checks:
        raise R1ValidationError("Artifact verification checks are incomplete.")

    profiles = _mapping(artifact["profiles"], "artifact.profiles")
    expected_profiles = {
        "pre_track_a_operational_default",
        "pre_track_a_controlled_top_k_6",
        "post_track_a_selected_top_k_6",
    }
    if set(profiles) != expected_profiles:
        raise R1ValidationError("artifact.profiles are incomplete.")
    expected_top_k = {
        "pre_track_a_operational_default": 4,
        "pre_track_a_controlled_top_k_6": 6,
        "post_track_a_selected_top_k_6": 6,
    }
    pre_upgrade_commit = cast(str, provenance["pre_upgrade_commit"])
    post_track_a_commit = cast(str, provenance["post_track_a_commit"])
    for profile_id, top_k in expected_top_k.items():
        profile = _mapping(
            profiles[profile_id],
            f"artifact.profiles.{profile_id}",
        )
        if profile_id.startswith("pre_track_a"):
            _require_exact_fields(
                profile,
                {
                    "source_commit",
                    "top_k",
                    "runtime_config",
                    "environment",
                    "checks",
                    "retrieval",
                },
                f"artifact.profiles.{profile_id}",
            )
            if profile["source_commit"] != pre_upgrade_commit:
                raise R1ValidationError(
                    f"{profile_id}.source_commit is inconsistent."
                )
        else:
            _require_exact_fields(
                profile,
                {
                    "source_commit",
                    "top_k",
                    "evidence",
                    "runtime_config",
                    "retrieval",
                },
                f"artifact.profiles.{profile_id}",
            )
            if profile["source_commit"] != post_track_a_commit:
                raise R1ValidationError(
                    f"{profile_id}.source_commit is inconsistent."
                )
            _validate_digest_record(
                profile["evidence"],
                label=f"artifact.profiles.{profile_id}.evidence",
                expected_path="phase0_baseline_results.json",
            )
        if profile.get("top_k") != top_k:
            raise R1ValidationError(f"{profile_id}.top_k is invalid.")
        runtime_config = profile.get("runtime_config")
        if not isinstance(runtime_config, dict) or not runtime_config:
            raise R1ValidationError(
                f"{profile_id}.runtime_config must not be empty."
            )
        _validate_retrieval(
            profile.get("retrieval"),
            label=f"artifact.profiles.{profile_id}.retrieval",
            top_k=top_k,
        )

    comparisons = _mapping(
        artifact["comparisons"],
        "artifact.comparisons",
    )
    if set(comparisons) != {"operational_default", "controlled_top_k_6"}:
        raise R1ValidationError("artifact.comparisons are incomplete.")
    operational = _mapping(
        comparisons["operational_default"],
        "artifact.comparisons.operational_default",
    )
    controlled = _mapping(
        comparisons["controlled_top_k_6"],
        "artifact.comparisons.controlled_top_k_6",
    )
    for comparison, label in (
        (operational, "operational_default"),
        (controlled, "controlled_top_k_6"),
    ):
        _require_exact_fields(
            comparison,
            {
                "pre_profile",
                "post_profile",
                "same_dataset",
                "same_corpus",
                "same_embedding_model",
                "same_metric_definitions",
                "same_top_k",
                "pre_top_k",
                "post_top_k",
                "metric_delta_post_minus_pre",
            },
            f"artifact.comparisons.{label}",
        )
        for field in (
            "same_dataset",
            "same_corpus",
            "same_embedding_model",
            "same_metric_definitions",
        ):
            if comparison.get(field) is not True:
                raise R1ValidationError(
                    f"artifact.comparisons.{label}.{field} must be true."
                )
    if operational.get("same_top_k") is not False:
        raise R1ValidationError("Operational comparison must report TOP_K delta.")
    if controlled.get("same_top_k") is not True:
        raise R1ValidationError("Controlled comparison must use the same TOP_K.")
    if controlled.get("pre_top_k") != 6 or controlled.get("post_top_k") != 6:
        raise R1ValidationError("Controlled TOP_K must equal 6.")

    expected_comparison_profiles = {
        "operational_default": (
            "pre_track_a_operational_default",
            "post_track_a_selected_top_k_6",
        ),
        "controlled_top_k_6": (
            "pre_track_a_controlled_top_k_6",
            "post_track_a_selected_top_k_6",
        ),
    }
    for label, comparison in (
        ("operational_default", operational),
        ("controlled_top_k_6", controlled),
    ):
        expected_pre, expected_post = expected_comparison_profiles[label]
        if (
            comparison["pre_profile"] != expected_pre
            or comparison["post_profile"] != expected_post
        ):
            raise R1ValidationError(
                f"artifact.comparisons.{label} profile references are invalid."
            )
        recorded_deltas = _mapping(
            comparison["metric_delta_post_minus_pre"],
            f"artifact.comparisons.{label}.metric_delta_post_minus_pre",
        )
        expected_deltas = _metric_deltas(
            cast(Mapping[str, object], profiles[expected_pre]),
            cast(Mapping[str, object], profiles[expected_post]),
        )
        _require_numeric_mappings_equal(
            recorded_deltas,
            expected_deltas,
            f"artifact.comparisons.{label}.metric_delta_post_minus_pre",
        )

    forbidden = _all_mapping_keys(artifact) & _FORBIDDEN_FIELDS
    if forbidden:
        raise R1ValidationError(
            f"artifact contains forbidden fields: {sorted(forbidden)}."
        )
    serialized = json.dumps(artifact, ensure_ascii=False)
    if _SECRET_PATTERN.search(serialized):
        raise R1ValidationError("artifact contains a credential-like value.")
    return artifact


def load_r1_artifact(
    path: Path = R1_RESULTS_JSON_PATH,
) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"R1 artifact not found: {path}.")
    return validate_r1_artifact(_load_json_bytes(path.read_bytes(), "R1 artifact"))


def verify_r1_artifact_provenance(
    path: Path = R1_RESULTS_JSON_PATH,
) -> dict[str, object]:
    """Verify recorded file identities against Git and frozen local evidence."""
    artifact = load_r1_artifact(path)
    provenance = cast(Mapping[str, object], artifact["provenance"])
    pre_upgrade_commit = cast(str, provenance["pre_upgrade_commit"])
    evaluation_commit = cast(str, provenance["evaluation_commit"])

    requirements = cast(
        Sequence[Mapping[str, object]],
        provenance["requirements"],
    )
    for requirement in requirements:
        relative_path = cast(str, requirement["path"])
        if requirement["sha256"] != _git_blob_digest(
            pre_upgrade_commit,
            relative_path,
        ):
            raise R1ValidationError(
                f"Legacy dependency identity does not match {relative_path}."
            )
    worker = cast(Mapping[str, object], provenance["worker"])
    if worker["sha256"] != _git_blob_digest(
        evaluation_commit,
        cast(str, worker["path"]),
    ):
        raise R1ValidationError("Legacy worker identity does not match Git.")

    profiles = cast(
        Mapping[str, Mapping[str, object]],
        artifact["profiles"],
    )
    post_profile = profiles["post_track_a_selected_top_k_6"]
    evidence = cast(Mapping[str, object], post_profile["evidence"])
    evidence_path = PROJECT_ROOT / cast(str, evidence["path"])
    if _sha256_file(evidence_path) != evidence["sha256"]:
        raise R1ValidationError("Post-Track-A evidence identity does not match.")
    return artifact


def _percent(value: object) -> str:
    return f"{float(value):.1%}"


def _metrics_table(profile: Mapping[str, object]) -> str:
    retrieval = cast(
        Mapping[str, Mapping[str, object]],
        profile["retrieval"],
    )
    lines = [
        "| mode | hit@k | recall@k | MRR | not-found | p50 | p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in _SUPPORTED_MODES:
        metrics = cast(Mapping[str, object], retrieval[mode]["metrics"])
        lines.append(
            f"| {mode} | {_percent(metrics['hit_rate_at_k'])} | "
            f"{_percent(metrics['recall_at_k'])} | "
            f"{float(metrics['mrr']):.3f} | "
            f"{_percent(metrics['not_found_discipline'])} | "
            f"{float(metrics['latency_p50_ms']):.1f} ms | "
            f"{float(metrics['latency_p95_ms']):.1f} ms |"
        )
    return "\n".join(lines)


def _hybrid_delta_table(comparisons: Mapping[str, object]) -> str:
    lines = [
        "| comparison | pre TOP_K | post TOP_K | Δ recall | Δ MRR | "
        "Δ not-found | Δ p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for comparison_id in ("operational_default", "controlled_top_k_6"):
        comparison = cast(
            Mapping[str, object],
            comparisons[comparison_id],
        )
        deltas = cast(
            Mapping[str, Mapping[str, float]],
            comparison["metric_delta_post_minus_pre"],
        )["hybrid"]
        lines.append(
            f"| {comparison_id} | {comparison['pre_top_k']} | "
            f"{comparison['post_top_k']} | "
            f"{deltas['recall_at_k']:+.1%} | {deltas['mrr']:+.3f} | "
            f"{deltas['not_found_discipline']:+.1%} | "
            f"{deltas['latency_p95_ms']:+.1f} ms |"
        )
    return "\n".join(lines)


def render_r1_report(artifact: Mapping[str, object]) -> str:
    profiles = cast(
        Mapping[str, Mapping[str, object]],
        artifact["profiles"],
    )
    provenance = cast(Mapping[str, object], artifact["provenance"])
    comparisons = cast(Mapping[str, object], artifact["comparisons"])
    return "\n".join(
        [
            "# Track A R1 — Pre-Upgrade Comparative Baseline v2",
            "",
            f"- Generated at: `{artifact['generated_at']}`",
            f"- Evaluation commit: `{provenance['evaluation_commit']}`",
            f"- Pre-Track-A commit: `{provenance['pre_upgrade_commit']}`",
            f"- Post-Track-A commit: `{provenance['post_track_a_commit']}`",
            f"- Dataset SHA-256: `{provenance['dataset_sha256']}`",
            f"- Corpus SHA-256: `{provenance['corpus_sha256']}`",
            "- Provider failures: `0`",
            "- Unexpected fallbacks: `0`",
            "",
            "## Pre-Track-A operational default — TOP_K=4",
            "",
            _metrics_table(profiles["pre_track_a_operational_default"]),
            "",
            "## Pre-Track-A controlled profile — TOP_K=6",
            "",
            _metrics_table(profiles["pre_track_a_controlled_top_k_6"]),
            "",
            "## Post-Track-A selected profile — TOP_K=6",
            "",
            _metrics_table(profiles["post_track_a_selected_top_k_6"]),
            "",
            "## Hybrid before/after deltas",
            "",
            _hybrid_delta_table(comparisons),
            "",
            "Operational comparison answers whether deployed defaults improved. "
            "Controlled comparison fixes TOP_K=6 to isolate the Track A quality "
            "pipeline from the context-count increase.",
            "",
            "## Verification and data boundary",
            "",
            "- Current and legacy worktrees were clean before external calls.",
            "- The legacy runtime was detached at the recorded commit and used "
            "a separate virtual environment.",
            "- Dataset, corpus, dependency, worker, and historical Phase 0 "
            "identities are pinned by SHA-256.",
            "- The existing corpus embedding cache was required; rebuilding it "
            "through the API was not permitted.",
            "- Published artifacts contain case IDs, labels, retrieved titles, "
            "metrics, and allowlisted environment metadata only.",
            "- Raw queries, document bodies, prompts, credentials, and raw "
            "environment variables are excluded.",
            "",
        ]
    )


def _write_pair_without_overwrite(
    json_content: bytes,
    markdown_content: bytes,
    *,
    json_path: Path = R1_RESULTS_JSON_PATH,
    markdown_path: Path = R1_RESULTS_MARKDOWN_PATH,
) -> None:
    """Atomically publish both artifacts and never replace existing evidence."""
    if json_path.exists() or markdown_path.exists():
        raise FileExistsError(
            "R1 evidence already exists. Version a new artifact; "
            "never overwrite official evidence."
        )
    temporary_json = json_path.with_name(f".{json_path.name}.{os.getpid()}.tmp")
    temporary_markdown = markdown_path.with_name(
        f".{markdown_path.name}.{os.getpid()}.tmp"
    )
    created: list[Path] = []
    try:
        for path, content in (
            (temporary_json, json_content),
            (temporary_markdown, markdown_content),
        ):
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
        os.link(temporary_json, json_path)
        created.append(json_path)
        os.link(temporary_markdown, markdown_path)
        created.append(markdown_path)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        temporary_json.unlink(missing_ok=True)
        temporary_markdown.unlink(missing_ok=True)


def write_r1_artifacts(
    artifact: Mapping[str, object],
    *,
    json_path: Path = R1_RESULTS_JSON_PATH,
    markdown_path: Path = R1_RESULTS_MARKDOWN_PATH,
) -> None:
    validated = validate_r1_artifact(dict(artifact))
    json_content = (
        json.dumps(validated, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    markdown_content = render_r1_report(validated).encode("utf-8")
    _write_pair_without_overwrite(
        json_content,
        markdown_content,
        json_path=json_path,
        markdown_path=markdown_path,
    )

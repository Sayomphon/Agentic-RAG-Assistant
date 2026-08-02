"""Track A closure freeze manifest and R0 reproducibility controls.

R0 records identities from the reviewed ``fd3ac95`` baseline instead of the
mutable remediation worktree. Verification reads committed bytes directly
from Git, so later remediation changes cannot silently redefine historical
inputs or evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, cast

from src.evaluation.baseline_support import PROJECT_ROOT

TRACK_A_CLOSURE_ID = "track-a-closure-v2"
TRACK_A_CLOSURE_SCHEMA_VERSION = "track-a-closure-freeze-v1"
TRACK_A_CLOSURE_MANIFEST_PATH = (
    Path(__file__).resolve().parent
    / "datasets"
    / "track_a_closure_v2.manifest.json"
)
TRACK_A_CLOSURE_REPORT_PATH = PROJECT_ROOT / "track_a_closure_report_v2.md"

_MAX_MANIFEST_BYTES = 1_000_000
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_CORPUS_HASH_ALGORITHM = (
    "sha256(length-prefixed-relative-path-and-bytes-v1)"
)
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "closure_id",
    "created_at",
    "repository",
    "governance",
    "frozen_inputs",
    "immutable_artifacts",
    "planned_artifacts",
}
_FORBIDDEN_SECRET_FIELDS = {
    "access_token",
    "api_key",
    "openai_api_key",
    "password",
    "refresh_token",
    "secret",
}
_MAX_EVIDENCE_BYTES = 20_000_000
_R4_JSON_EVIDENCE = {
    "R1 comparative baseline": PROJECT_ROOT
    / "track_a_pre_upgrade_baseline_v2.json",
    "R3 ablation": PROJECT_ROOT / "track_a_ablation_results_v2.json",
    "R3 answer evaluation": PROJECT_ROOT
    / "track_a_answer_results_v2.json",
    "R3 performance": PROJECT_ROOT / "track_a_performance_results_v2.json",
    "Selected profile": PROJECT_ROOT
    / "src/evaluation/configs/track_a_balanced_v1.json",
}
_R4_DECISION_RECORD_PATH = PROJECT_ROOT / "docs/TRACK_A_DECISION_RECORD.md"
_PHASE0_V2_MANIFEST_PATH = (
    PROJECT_ROOT
    / "src/evaluation/datasets/enterprise_phase0_v2.manifest.json"
)
_PHASE0_V2_RESULTS_PATH = PROJECT_ROOT / "phase0_v2_baseline_results.json"


@dataclass(frozen=True)
class ClosureGate:
    """One auditable, fail-closed Track A closure decision."""

    name: str
    passed: bool
    evidence: str


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject ambiguous JSON instead of accepting the last duplicate key."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(
                f"Track A closure manifest repeats JSON key {key!r}."
            )
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
            f"missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}."
        )


def _non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


def _safe_relative_path(value: object, label: str) -> str:
    raw_path = _non_empty_string(value, label)
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must stay within the project.")
    return raw_path


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _HASH_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer.")
    return value


def _file_identity(value: object, label: str) -> dict[str, object]:
    identity = _mapping(value, label)
    _require_exact_fields(identity, {"path", "sha256", "bytes"}, label)
    _safe_relative_path(identity["path"], f"{label}.path")
    _digest(identity["sha256"], f"{label}.sha256")
    _positive_int(identity["bytes"], f"{label}.bytes")
    return identity


def _file_identity_list(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list.")
    identities = [
        _file_identity(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    ]
    paths = [cast(str, identity["path"]) for identity in identities]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ValueError(f"{label} paths must be sorted and unique.")
    return identities


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list.")
    values = [
        _safe_relative_path(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    ]
    if values != sorted(values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be sorted and unique.")
    return values


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


def validate_track_a_closure_manifest(
    value: object,
) -> dict[str, object]:
    """Structurally validate the immutable R0 freeze record."""
    manifest = _mapping(value, "manifest")
    _require_exact_fields(manifest, _TOP_LEVEL_FIELDS, "manifest")
    if manifest["schema_version"] != TRACK_A_CLOSURE_SCHEMA_VERSION:
        raise ValueError("manifest.schema_version is unsupported.")
    if manifest["closure_id"] != TRACK_A_CLOSURE_ID:
        raise ValueError("manifest.closure_id is unsupported.")
    try:
        date.fromisoformat(str(manifest["created_at"]))
    except ValueError as exc:
        raise ValueError("manifest.created_at must be an ISO date.") from exc

    repository = _mapping(manifest["repository"], "repository")
    _require_exact_fields(
        repository,
        {"base_commit", "pre_upgrade_commit", "remediation_branch"},
        "repository",
    )
    for field in ("base_commit", "pre_upgrade_commit"):
        value = repository[field]
        if not isinstance(value, str) or not _COMMIT_PATTERN.fullmatch(value):
            raise ValueError(f"repository.{field} must be a full Git commit.")
    _non_empty_string(
        repository["remediation_branch"],
        "repository.remediation_branch",
    )

    governance = _mapping(manifest["governance"], "governance")
    _require_exact_fields(
        governance,
        {
            "plan",
            "official_evaluation_requires_clean_worktree",
            "historical_artifacts_must_not_be_overwritten",
            "published_artifacts_exclude_secrets",
            "published_artifacts_exclude_raw_queries",
            "published_artifacts_exclude_document_bodies",
        },
        "governance",
    )
    _file_identity(governance["plan"], "governance.plan")
    for field in set(governance) - {"plan"}:
        if governance[field] is not True:
            raise ValueError(f"governance.{field} must be true.")

    frozen = _mapping(manifest["frozen_inputs"], "frozen_inputs")
    _require_exact_fields(
        frozen,
        {
            "dataset",
            "corpus",
            "dependencies",
            "runtime_configuration",
            "retriever_contract",
            "prompt_sources",
            "models",
        },
        "frozen_inputs",
    )
    dataset = _mapping(frozen["dataset"], "frozen_inputs.dataset")
    _require_exact_fields(
        dataset,
        {"version", "case_count", "file", "manifest"},
        "frozen_inputs.dataset",
    )
    _non_empty_string(dataset["version"], "frozen_inputs.dataset.version")
    _positive_int(dataset["case_count"], "frozen_inputs.dataset.case_count")
    _file_identity(dataset["file"], "frozen_inputs.dataset.file")
    _file_identity(dataset["manifest"], "frozen_inputs.dataset.manifest")

    corpus = _mapping(frozen["corpus"], "frozen_inputs.corpus")
    _require_exact_fields(
        corpus,
        {"algorithm", "sha256", "section_count", "file"},
        "frozen_inputs.corpus",
    )
    if corpus["algorithm"] != _CORPUS_HASH_ALGORITHM:
        raise ValueError("frozen_inputs.corpus.algorithm is unsupported.")
    _digest(corpus["sha256"], "frozen_inputs.corpus.sha256")
    _positive_int(
        corpus["section_count"],
        "frozen_inputs.corpus.section_count",
    )
    _file_identity(corpus["file"], "frozen_inputs.corpus.file")

    _file_identity_list(frozen["dependencies"], "frozen_inputs.dependencies")
    _file_identity_list(
        frozen["runtime_configuration"],
        "frozen_inputs.runtime_configuration",
    )
    _file_identity_list(
        frozen["prompt_sources"],
        "frozen_inputs.prompt_sources",
    )

    contract = _mapping(
        frozen["retriever_contract"],
        "frozen_inputs.retriever_contract",
    )
    _require_exact_fields(
        contract,
        {"version", "file"},
        "frozen_inputs.retriever_contract",
    )
    version = contract["version"]
    if not isinstance(version, str) or not _SEMVER_PATTERN.fullmatch(version):
        raise ValueError(
            "frozen_inputs.retriever_contract.version must be SemVer."
        )
    _file_identity(
        contract["file"],
        "frozen_inputs.retriever_contract.file",
    )

    models = _mapping(frozen["models"], "frozen_inputs.models")
    _require_exact_fields(
        models,
        {
            "embedding",
            "generator",
            "primary_reranker",
            "secondary_reranker",
        },
        "frozen_inputs.models",
    )
    for name in ("embedding", "generator"):
        model = _mapping(models[name], f"frozen_inputs.models.{name}")
        _require_exact_fields(
            model,
            {"model"},
            f"frozen_inputs.models.{name}",
        )
        _non_empty_string(
            model["model"],
            f"frozen_inputs.models.{name}.model",
        )
    primary = _mapping(
        models["primary_reranker"],
        "frozen_inputs.models.primary_reranker",
    )
    _require_exact_fields(
        primary,
        {"model", "revision"},
        "frozen_inputs.models.primary_reranker",
    )
    _non_empty_string(
        primary["model"],
        "frozen_inputs.models.primary_reranker.model",
    )
    revision = primary["revision"]
    if not isinstance(revision, str) or not _COMMIT_PATTERN.fullmatch(revision):
        raise ValueError(
            "frozen_inputs.models.primary_reranker.revision "
            "must be an immutable revision."
        )
    secondary = _mapping(
        models["secondary_reranker"],
        "frozen_inputs.models.secondary_reranker",
    )
    _require_exact_fields(
        secondary,
        {"status", "owner", "required_before_official_evaluation"},
        "frozen_inputs.models.secondary_reranker",
    )
    if secondary["status"] != "not-configured-at-r0":
        raise ValueError(
            "Secondary reranker identity must reflect the R0 baseline."
        )
    _non_empty_string(
        secondary["owner"],
        "frozen_inputs.models.secondary_reranker.owner",
    )
    if secondary["required_before_official_evaluation"] is not True:
        raise ValueError(
            "Secondary reranker must be resolved before official evaluation."
        )

    _file_identity_list(
        manifest["immutable_artifacts"],
        "immutable_artifacts",
    )
    _string_list(manifest["planned_artifacts"], "planned_artifacts")

    forbidden = _all_mapping_keys(manifest) & _FORBIDDEN_SECRET_FIELDS
    if forbidden:
        raise ValueError(
            f"Manifest contains forbidden secret fields: {sorted(forbidden)}."
        )
    return manifest


def load_track_a_closure_manifest(
    path: Path = TRACK_A_CLOSURE_MANIFEST_PATH,
) -> dict[str, object]:
    """Load the R0 record with duplicate-key and size protections."""
    if not path.is_file():
        raise FileNotFoundError(f"Track A closure manifest not found: {path}.")
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("Track A closure manifest exceeds the safe size limit.")
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    return validate_track_a_closure_manifest(payload)


def _git_file_bytes(commit: str, relative_path: str) -> bytes:
    """Read one path from the frozen commit without invoking a shell."""
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Cannot read frozen Git object {commit}:{relative_path}."
        )
    return result.stdout


def _identity_groups(
    manifest: Mapping[str, object],
) -> Iterable[Mapping[str, object]]:
    frozen = cast(Mapping[str, object], manifest["frozen_inputs"])
    dataset = cast(Mapping[str, object], frozen["dataset"])
    corpus = cast(Mapping[str, object], frozen["corpus"])
    contract = cast(Mapping[str, object], frozen["retriever_contract"])
    yield cast(Mapping[str, object], dataset["file"])
    yield cast(Mapping[str, object], dataset["manifest"])
    yield cast(Mapping[str, object], corpus["file"])
    yield from cast(list[Mapping[str, object]], frozen["dependencies"])
    yield from cast(
        list[Mapping[str, object]],
        frozen["runtime_configuration"],
    )
    yield cast(Mapping[str, object], contract["file"])
    yield from cast(list[Mapping[str, object]], frozen["prompt_sources"])
    yield from cast(
        list[Mapping[str, object]],
        manifest["immutable_artifacts"],
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _snapshot_sha256(
    files: Iterable[tuple[str, bytes]],
) -> str:
    digest = hashlib.sha256()
    for relative_path, content in files:
        encoded_path = relative_path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def verify_track_a_r0_freeze(
    path: Path = TRACK_A_CLOSURE_MANIFEST_PATH,
) -> dict[str, object]:
    """Verify every frozen file against bytes from the reviewed base commit."""
    manifest = load_track_a_closure_manifest(path)
    repository = cast(Mapping[str, object], manifest["repository"])
    base_commit = cast(str, repository["base_commit"])

    checked_paths: set[str] = set()
    for identity in _identity_groups(manifest):
        relative_path = cast(str, identity["path"])
        if relative_path in checked_paths:
            continue
        checked_paths.add(relative_path)
        content = _git_file_bytes(base_commit, relative_path)
        if len(content) != identity["bytes"]:
            raise ValueError(
                f"Frozen byte count does not match {relative_path}."
            )
        if _sha256(content) != identity["sha256"]:
            raise ValueError(f"Frozen SHA-256 does not match {relative_path}.")

    frozen = cast(Mapping[str, object], manifest["frozen_inputs"])
    corpus = cast(Mapping[str, object], frozen["corpus"])
    corpus_file = cast(Mapping[str, object], corpus["file"])
    corpus_path = cast(str, corpus_file["path"])
    corpus_bytes = _git_file_bytes(base_commit, corpus_path)
    snapshot_digest = _snapshot_sha256([(corpus_path, corpus_bytes)])
    if snapshot_digest != corpus["sha256"]:
        raise ValueError("Frozen corpus snapshot SHA-256 does not match.")

    governance = cast(Mapping[str, object], manifest["governance"])
    plan = cast(Mapping[str, object], governance["plan"])
    plan_path = PROJECT_ROOT / cast(str, plan["path"])
    plan_content = plan_path.read_bytes()
    if (
        len(plan_content) != plan["bytes"]
        or _sha256(plan_content) != plan["sha256"]
    ):
        raise ValueError("Track A closure plan identity does not match.")
    return manifest


def verify_track_a_r0_repository_state(
    manifest: Mapping[str, object],
) -> None:
    """Require the approved branch, committed R0 work, and a clean worktree."""
    repository = cast(Mapping[str, object], manifest["repository"])
    expected_branch = cast(str, repository["remediation_branch"])
    base_commit = cast(str, repository["base_commit"])

    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if branch != expected_branch:
        raise ValueError(
            f"R0 must run on {expected_branch!r}; current branch is {branch!r}."
        )

    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_commit, "HEAD"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )
    if ancestry.returncode != 0:
        raise ValueError("R0 base commit is not an ancestor of HEAD.")

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise ValueError("Official R0 verification requires a clean worktree.")


def _load_r4_json(path: Path, label: str) -> dict[str, object]:
    """Load one bounded evidence artifact and reject ambiguous JSON."""
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}.")
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link.")
    if path.stat().st_size > _MAX_EVIDENCE_BYTES:
        raise ValueError(f"{label} exceeds the safe evidence size limit.")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON.") from exc
    return _mapping(payload, label)


def _nested_mapping(
    value: Mapping[str, object],
    field: str,
    label: str,
) -> dict[str, object]:
    if field not in value:
        raise ValueError(f"{label}.{field} is required.")
    return _mapping(value[field], f"{label}.{field}")


def _nested_list(
    value: Mapping[str, object],
    field: str,
    label: str,
) -> list[object]:
    result = value.get(field)
    if not isinstance(result, list):
        raise ValueError(f"{label}.{field} must be a JSON array.")
    return result


def _artifact_identity(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": _sha256(content),
        "bytes": len(content),
    }


def _decision_field(content: str, label: str) -> str:
    prefix = f"- {label}:"
    matches = [
        line.removeprefix(prefix).strip().replace("`", "")
        for line in content.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1 or not matches[0]:
        raise ValueError(
            f"Decision Record must contain exactly one {label!r} field."
        )
    return matches[0]


def _load_r4_decision() -> tuple[dict[str, str], dict[str, object]]:
    path = _R4_DECISION_RECORD_PATH
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(
            "Track A Decision Record is missing or is not a regular file."
        )
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("Track A Decision Record exceeds the safe size limit.")
    content = path.read_text(encoding="utf-8")
    fields = {
        "recommendation": _decision_field(content, "Recommendation"),
        "technical_evidence": _decision_field(
            content,
            "Technical evidence status",
        ),
        "automated_gate": _decision_field(
            content,
            "Automated closure gate",
        ),
        "human_review": _decision_field(content, "Human/Domain review"),
        "product_decision": _decision_field(
            content,
            "Product/Business decision",
        ),
        "r4_authorization": _decision_field(
            content,
            "R4 closure authorization",
        ),
    }
    return fields, _artifact_identity(path)


def _verify_current_historical_artifacts(
    manifest: Mapping[str, object],
) -> int:
    identities = cast(
        list[Mapping[str, object]],
        manifest["immutable_artifacts"],
    )
    for identity in identities:
        relative_path = cast(str, identity["path"])
        path = PROJECT_ROOT / relative_path
        if not path.is_file() or path.is_symlink():
            raise ValueError(
                f"Historical artifact is missing or unsafe: {relative_path}."
            )
        content = path.read_bytes()
        if (
            len(content) != identity["bytes"]
            or _sha256(content) != identity["sha256"]
        ):
            raise ValueError(
                f"Historical artifact was modified: {relative_path}."
            )

    phase0_v1_manifest_path = (
        PROJECT_ROOT
        / "src/evaluation/datasets/enterprise_phase0_v1.manifest.json"
    )
    phase0_v1_report_path = PROJECT_ROOT / "phase0_baseline_results.json"
    phase0_manifest = _load_r4_json(
        phase0_v1_manifest_path,
        "Enterprise Phase 0 v1 manifest",
    )
    phase0_report = _load_r4_json(
        phase0_v1_report_path,
        "Enterprise Phase 0 v1 report",
    )
    if phase0_report.get("manifest") != phase0_manifest:
        raise ValueError(
            "Enterprise Phase 0 v1 manifest and embedded report differ."
        )
    return len(identities) + 1


def _validate_r4_identity(
    r1: Mapping[str, object],
    ablation: Mapping[str, object],
    answer: Mapping[str, object],
    performance: Mapping[str, object],
    profile_path: Path,
) -> dict[str, object]:
    identities = [
        _nested_mapping(ablation, "identity", "ablation"),
        _nested_mapping(answer, "identity", "answer"),
        _nested_mapping(performance, "identity", "performance"),
    ]
    canonical = identities[0]
    if any(identity != canonical for identity in identities[1:]):
        raise ValueError(
            "R3 dataset, corpus, profile, metric, or TOP_K identities differ."
        )

    provenance = _nested_mapping(r1, "provenance", "R1")
    dataset = _nested_mapping(canonical, "dataset", "R3.identity")
    corpus = _nested_mapping(canonical, "corpus", "R3.identity")
    profile = _nested_mapping(canonical, "selected_profile", "R3.identity")
    if provenance.get("dataset_sha256") != dataset.get("sha256"):
        raise ValueError("R1 and R3 dataset identities differ.")
    if provenance.get("corpus_sha256") != corpus.get("sha256"):
        raise ValueError("R1 and R3 corpus identities differ.")
    if profile.get("sha256") != _artifact_identity(profile_path)["sha256"]:
        raise ValueError("Selected profile SHA-256 does not match R3 evidence.")
    if canonical.get("top_k") != 6:
        raise ValueError("R4 controlled comparison requires TOP_K=6.")
    return canonical


def _r1_gate(r1: Mapping[str, object]) -> ClosureGate:
    if r1.get("schema_version") != "track-a-pre-upgrade-baseline-v2":
        raise ValueError("R1 schema_version is unsupported.")
    checks = _nested_list(r1, "checks", "R1")
    checks_passed = bool(checks) and all(
        isinstance(check, Mapping) and check.get("passed") is True
        for check in checks
    )
    comparison = _nested_mapping(
        _nested_mapping(r1, "comparisons", "R1"),
        "controlled_top_k_6",
        "R1.comparisons",
    )
    controlled = all(
        comparison.get(field) is True
        for field in (
            "same_dataset",
            "same_corpus",
            "same_embedding_model",
            "same_metric_definitions",
            "same_top_k",
        )
    )
    provenance = _nested_mapping(r1, "provenance", "R1")
    healthy = (
        provenance.get("provider_failure_count") == 0
        and provenance.get("fallback_count") == 0
        and provenance.get("working_tree_clean") is True
        and provenance.get("legacy_worktree_clean") is True
    )
    passed = checks_passed and controlled and healthy
    return ClosureGate(
        "R1 apples-to-apples evidence",
        passed,
        "Local/legacy checks pass, TOP_K=6 identities match, "
        "provider failures=0, fallback=0.",
    )


def _profile_by_id(
    ablation: Mapping[str, object],
    ablation_id: str,
) -> dict[str, object]:
    profiles = _nested_list(ablation, "profiles", "ablation")
    matches = [
        _mapping(profile, f"ablation.profiles[{index}]")
        for index, profile in enumerate(profiles)
        if isinstance(profile, Mapping)
        and profile.get("ablation_id") == ablation_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Ablation must contain exactly one {ablation_id}.")
    return matches[0]


def _scenario_by_id(
    performance: Mapping[str, object],
    scenario_id: str,
) -> dict[str, object]:
    scenarios = _nested_list(performance, "scenarios", "performance")
    matches = [
        _mapping(scenario, f"performance.scenarios[{index}]")
        for index, scenario in enumerate(scenarios)
        if isinstance(scenario, Mapping)
        and scenario.get("scenario_id") == scenario_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Performance evidence must contain exactly one {scenario_id}."
        )
    return matches[0]


def _runtime_safety_gate(
    performance: Mapping[str, object],
) -> ClosureGate:
    primary_fallback = _scenario_by_id(
        performance,
        "primary_timeout_secondary",
    )
    both_fail = _scenario_by_id(performance, "both_fail_closed")
    concurrent = _scenario_by_id(performance, "concurrent_busy")
    scenarios = (primary_fallback, both_fail, concurrent)
    passed = (
        primary_fallback.get("secondary_usage_rate") == 1.0
        and both_fail.get("fail_closed") is True
        and all(
            scenario.get("unhandled_exception_count") == 0
            and scenario.get("within_overall_timeout") is True
            for scenario in scenarios
        )
    )
    return ClosureGate(
        "R2 runtime safety",
        passed,
        "Primary timeout uses Secondary; both failures fail closed; "
        "failure/concurrency paths have no unhandled exception.",
    )


def _phase0_v2_gate() -> tuple[ClosureGate, dict[str, object] | None]:
    if not _PHASE0_V2_MANIFEST_PATH.is_file() or not (
        _PHASE0_V2_RESULTS_PATH.is_file()
    ):
        return (
            ClosureGate(
                "Enterprise Phase 0 v2 checkpoint",
                False,
                "Versioned manifest and three-mode result are not both present.",
            ),
            None,
        )
    manifest = _load_r4_json(
        _PHASE0_V2_MANIFEST_PATH,
        "Enterprise Phase 0 v2 manifest",
    )
    report = _load_r4_json(
        _PHASE0_V2_RESULTS_PATH,
        "Enterprise Phase 0 v2 report",
    )
    retrieval = _nested_mapping(report, "retrieval", "Phase 0 v2 report")
    checks = _nested_list(report, "checks", "Phase 0 v2 report")
    passed = (
        manifest.get("baseline_id") == "enterprise-phase0-v2"
        and report.get("schema_version")
        == "enterprise-phase0-baseline-report-v2"
        and report.get("baseline_id") == "enterprise-phase0-v2"
        and report.get("manifest") == manifest
        and set(retrieval) == {"keyword", "semantic", "hybrid"}
        and bool(checks)
        and all(
            isinstance(check, Mapping) and check.get("passed") is True
            for check in checks
        )
    )
    return (
        ClosureGate(
            "Enterprise Phase 0 v2 checkpoint",
            passed,
            "Versioned manifest/report match; Keyword/Semantic/Hybrid and "
            "all local gates are present.",
        ),
        report,
    )


def build_track_a_r4_assessment(
    *,
    generated_at: str | None = None,
) -> dict[str, object]:
    """Build the R4 decision from versioned evidence without trusting prose."""
    r0_manifest = verify_track_a_r0_freeze()
    immutable_count = _verify_current_historical_artifacts(r0_manifest)
    artifacts = {
        label: _load_r4_json(path, label)
        for label, path in _R4_JSON_EVIDENCE.items()
    }
    r1 = artifacts["R1 comparative baseline"]
    ablation = artifacts["R3 ablation"]
    answer = artifacts["R3 answer evaluation"]
    performance = artifacts["R3 performance"]
    profile_path = _R4_JSON_EVIDENCE["Selected profile"]

    if ablation.get("schema_version") != "track-a-r3-ablation-v2":
        raise ValueError("R3 ablation schema_version is unsupported.")
    if answer.get("schema_version") != "track-a-r3-answer-evaluation-v2":
        raise ValueError("R3 answer schema_version is unsupported.")
    if performance.get("schema_version") != "track-a-r3-performance-v2":
        raise ValueError("R3 performance schema_version is unsupported.")

    identity = _validate_r4_identity(
        r1,
        ablation,
        answer,
        performance,
        profile_path,
    )
    a0 = _profile_by_id(ablation, "A0")
    a5 = _profile_by_id(ablation, "A5")
    a6 = _profile_by_id(ablation, "A6")
    answer_gate = _nested_mapping(answer, "automated_gate", "answer")
    performance_gate = _nested_mapping(
        performance,
        "performance_gate",
        "performance",
    )
    human_review = _nested_mapping(answer, "human_review", "answer")
    decision, decision_identity = _load_r4_decision()
    phase0_gate, phase0_report = _phase0_v2_gate()

    gates = [
        ClosureGate(
            "R0 historical evidence immutability",
            True,
            f"{immutable_count} frozen identities match reviewed evidence.",
        ),
        _r1_gate(r1),
        ClosureGate(
            "R3 retrieval quality",
            ablation.get("selected_passed_retrieval_gates") is True
            and a5.get("passed_hard_gates") is True,
            "A5 passes controlled retrieval, language, context-header, "
            "and context-budget gates.",
        ),
        _runtime_safety_gate(performance),
        ClosureGate(
            "R3 final-answer quality",
            answer_gate.get("passed") is True,
            "Automated end-to-end answer hard gate.",
        ),
        ClosureGate(
            "R3 performance",
            performance_gate.get("passed") is True,
            "Warm retrieval and Primary local reranker latency guardrails.",
        ),
        ClosureGate(
            "Human/Domain review",
            human_review.get("status") == "APPROVED"
            and decision["human_review"] == "APPROVED",
            str(human_review.get("status", "missing")),
        ),
        ClosureGate(
            "Product/Business approval",
            decision["product_decision"] == "APPROVED",
            decision["product_decision"],
        ),
        ClosureGate(
            "R3 decision authorization",
            decision["recommendation"]
            in {"APPROVE", "APPROVE_WITH_ACCEPTED_RISK"}
            and decision["r4_authorization"] == "granted",
            f"{decision['recommendation']}; "
            f"authorization={decision['r4_authorization']}.",
        ),
        phase0_gate,
    ]
    all_passed = all(gate.passed for gate in gates)
    status = (
        decision["recommendation"]
        if all_passed
        and decision["recommendation"]
        in {"APPROVE", "APPROVE_WITH_ACCEPTED_RISK"}
        else "NOT_APPROVED"
    )

    evidence_bundle = [
        _artifact_identity(path)
        for path in _R4_JSON_EVIDENCE.values()
    ]
    evidence_bundle.append(decision_identity)
    if _PHASE0_V2_MANIFEST_PATH.is_file():
        evidence_bundle.append(_artifact_identity(_PHASE0_V2_MANIFEST_PATH))
    if _PHASE0_V2_RESULTS_PATH.is_file():
        evidence_bundle.append(_artifact_identity(_PHASE0_V2_RESULTS_PATH))
    evidence_bundle.sort(key=lambda item: cast(str, item["path"]))

    return {
        "generated_at": generated_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "selected_profile": "track_a_balanced_v1",
        "selected_profile_state": "measured_candidate_not_promoted",
        "identity": identity,
        "metrics": {
            "pre_track_a": _nested_mapping(a0, "metrics", "A0"),
            "post_track_a": _nested_mapping(a5, "metrics", "A5"),
            "secondary": _nested_mapping(a6, "metrics", "A6"),
            "answer": _nested_mapping(answer, "metrics", "answer"),
            "performance_gate": performance_gate,
        },
        "gates": [
            {
                "name": gate.name,
                "passed": gate.passed,
                "evidence": gate.evidence,
            }
            for gate in gates
        ],
        "decision": decision,
        "accepted_risks": [],
        "parent_plan_update_eligible": status
        in {"APPROVE", "APPROVE_WITH_ACCEPTED_RISK"},
        "next_track": (
            "Enterprise Phase 1"
            if status in {"APPROVE", "APPROVE_WITH_ACCEPTED_RISK"}
            else "Additional Track A remediation"
        ),
        "phase0_v2_present": phase0_report is not None,
        "evidence_bundle": evidence_bundle,
    }


def _percent(value: object) -> str:
    if not isinstance(value, (int, float)):
        raise ValueError("Expected a numeric metric.")
    return f"{float(value) * 100:.2f}%"


def render_track_a_closure_report(
    assessment: Mapping[str, object],
) -> str:
    """Render a sanitized, aggregate-only R4 closure report."""
    metrics = _nested_mapping(assessment, "metrics", "assessment")
    pre = _nested_mapping(metrics, "pre_track_a", "assessment.metrics")
    post = _nested_mapping(metrics, "post_track_a", "assessment.metrics")
    secondary = _nested_mapping(
        metrics,
        "secondary",
        "assessment.metrics",
    )
    answer = _nested_mapping(metrics, "answer", "assessment.metrics")
    performance_gate = _nested_mapping(
        metrics,
        "performance_gate",
        "assessment.metrics",
    )
    gates = _nested_list(assessment, "gates", "assessment")
    evidence_bundle = _nested_list(
        assessment,
        "evidence_bundle",
        "assessment",
    )
    decision = _nested_mapping(assessment, "decision", "assessment")

    gate_rows = [
        "| Gate | ผล | Evidence |",
        "|---|---|---|",
    ]
    for index, raw_gate in enumerate(gates):
        gate = _mapping(raw_gate, f"assessment.gates[{index}]")
        gate_rows.append(
            f"| {gate['name']} | "
            f"{'PASS' if gate['passed'] is True else 'FAIL'} | "
            f"{gate['evidence']} |"
        )

    evidence_rows = [
        "| Artifact | SHA-256 | Bytes |",
        "|---|---|---:|",
    ]
    for index, raw_identity in enumerate(evidence_bundle):
        identity = _mapping(
            raw_identity,
            f"assessment.evidence_bundle[{index}]",
        )
        evidence_rows.append(
            f"| `{identity['path']}` | `{identity['sha256']}` | "
            f"{identity['bytes']} |"
        )

    answer_failures = ", ".join(
        cast(list[str], performance_gate.get("failures", []))
    )
    return "\n".join(
        [
            "# Track A Closure Report v2",
            "",
            f"- Generated at: {assessment['generated_at']}",
            f"- Track A Status: `{assessment['status']}`",
            "- Closure policy: fail closed; ไม่อนุมัติจากผลเฉลี่ยเมื่อมี "
            "Blocking Gate ใดล้มเหลว",
            f"- Selected Profile: `{assessment['selected_profile']}` "
            "(measured candidate; not promoted)",
            f"- Next Track: `{assessment['next_track']}`",
            "",
            "## 1. Executive Summary",
            "",
            "R0–R3 สร้างหลักฐานเชิงเทคนิคครบและ Retrieval quality ดีขึ้นชัดเจน "
            "แต่ Track A ยังปิดไม่ได้ เพราะ End-to-end Answer Gate, Performance "
            "Gate, Human/Domain review, Product/Business approval และ R3 "
            "authorization ยังไม่ผ่านครบ การสร้าง Enterprise Phase 0 v2 "
            "เป็นเพียง technical checkpoint และไม่อนุญาตให้เริ่ม Phase 1.",
            "",
            "## 2. Scope and Environment",
            "",
            "- Dataset: `lean-quality-v1`, 40 cases, controlled `TOP_K=6`",
            "- Corpus: `knowledge_base.txt`, 54 sections",
            "- Architecture: Keyword + Dense Hybrid → Candidate Expansion "
            "→ Primary/Secondary Reranker → Answerability Gate → Context Builder "
            "→ LangGraph answer pipeline → Validators",
            "- Published report contains aggregate metrics, IDs, hashes, and "
            "stable reason codes only; no raw query, answer, prompt, credential, "
            "or document body.",
            "",
            "## 3. Pre/Post Architecture and Retrieval Quality",
            "",
            "| Metric | Pre-Track-A A0 | Post-Track-A A5 | Delta |",
            "|---|---:|---:|---:|",
            f"| Recall@6 | {_percent(pre['recall_at_k'])} | "
            f"{_percent(post['recall_at_k'])} | "
            f"{_percent(float(post['recall_at_k']) - float(pre['recall_at_k']))} |",
            f"| MRR | {float(pre['mrr']):.3f} | "
            f"{float(post['mrr']):.3f} | "
            f"{float(post['mrr']) - float(pre['mrr']):+.3f} |",
            f"| Not-found discipline | "
            f"{_percent(pre['not_found_discipline'])} | "
            f"{_percent(post['not_found_discipline'])} | "
            f"{_percent(float(post['not_found_discipline']) - float(pre['not_found_discipline']))} |",
            "",
            "Ablation ยืนยันว่า Primary Reranker เพิ่ม Recall/MRR และ Score Gate "
            "ลด False Positive มากที่สุดในมิติ Safety ส่วน Context Builder "
            "รักษา Context header/budget validity ที่ 100%. Secondary path "
            f"มี Recall {_percent(secondary['recall_at_k'])} แต่ยังไม่ผ่าน "
            "Multi-section non-regression จึงคงเป็น emergency degradation path.",
            "",
            "## 4. End-to-end Answer Quality",
            "",
            "| Metric | Result | Required |",
            "|---|---:|---:|",
            f"| Answer citation validity | "
            f"{_percent(answer['answer_citation_validity'])} | 100% |",
            f"| Answer citation coverage | "
            f"{_percent(answer['answer_citation_coverage'])} | 100% |",
            f"| Negative exact not-found | "
            f"{_percent(answer['negative_exact_not_found'])} | ≥90% |",
            f"| Faithfulness | {_percent(answer['faithfulness'])} | ≥95% |",
            f"| Answer relevance | {float(answer['answer_relevance']):.2f}/5 "
            "| ≥4.0/5 |",
            f"| Unsupported high-risk claims | "
            f"{answer['unsupported_high_risk_claim_count']} | 0 |",
            "",
            "Blocking findings: citation coverage ต่ำกว่า 100%, มีหนึ่ง "
            "answerable case ตอบ not-found ทั้งที่มี expected evidence และมี "
            "unsupported high-risk claim หนึ่งรายการ.",
            "",
            "## 5. Performance, RAM, and Failure Behavior",
            "",
            "- Primary warm retrieval p95: 4,727 ms (target ≤3,000 ms)",
            "- Primary local reranker p95: 4,203 ms (target ≤2,000 ms)",
            "- Peak RSS: 2,160 MiB (target ≤6,144 MiB; pass)",
            "- Primary timeout → Secondary: no unhandled exception",
            "- Primary + Secondary failure → deterministic fail closed",
            "- Concurrent Busy path: bounded and no unhandled exception",
            f"- Performance failures: `{answer_failures or 'none'}`",
            "",
            "## 6. Closure Gates",
            "",
            *gate_rows,
            "",
            "## 7. Risk Acceptance and Governance",
            "",
            f"- R3 recommendation: `{decision['recommendation']}`",
            f"- Human/Domain review: `{decision['human_review']}`",
            f"- Product/Business decision: `{decision['product_decision']}`",
            f"- R4 authorization: `{decision['r4_authorization']}`",
            "- Accepted Risks: `none`",
            "- Parent Plan completion status was not updated because Closure "
            "authorization is not granted.",
            "",
            "## 8. Known Limitations and Required Remediation",
            "",
            "1. เพิ่ม deterministic citation-coverage validator พร้อม bounded "
            "repair และ fail-closed policy.",
            "2. แก้ unsupported mixed-language high-risk claim และ "
            "retrieved-evidence/not-found contradiction.",
            "3. ลด Primary latency หรือใช้ conditional reranking แล้ว rerun "
            "quality/performance gates.",
            "4. Tune Secondary-specific threshold สำหรับ Multi-section.",
            "5. ทำ Human/Domain review 20 cases และบันทึก Product/Business decision.",
            "",
            "## 9. Evidence Bundle",
            "",
            *evidence_rows,
            "",
            "## 10. Final Decision",
            "",
            f"```text\nTrack A Status: {assessment['status']}\n"
            f"Selected Profile: {assessment['selected_profile']} "
            "(candidate only)\n"
            "Accepted Risks: none\n"
            f"Next Track: {assessment['next_track']}\n```",
            "",
        ]
    )


def write_track_a_closure_report(
    assessment: Mapping[str, object],
    *,
    path: Path = TRACK_A_CLOSURE_REPORT_PATH,
) -> None:
    """Atomically write the versioned R4 report to a regular project file."""
    resolved_parent = path.parent.resolve()
    if resolved_parent != PROJECT_ROOT.resolve():
        raise ValueError("Track A closure report must stay at the project root.")
    if path.exists() and path.is_symlink():
        raise ValueError("Track A closure report must not be a symbolic link.")
    content = render_track_a_closure_report(assessment)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.unlink(missing_ok=True)
    try:
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)

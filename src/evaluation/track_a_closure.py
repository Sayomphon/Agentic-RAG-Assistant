"""Track A closure freeze manifest and R0 reproducibility controls.

R0 records identities from the reviewed ``fd3ac95`` baseline instead of the
mutable remediation worktree. Verification reads committed bytes directly
from Git, so later remediation changes cannot silently redefine historical
inputs or evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import date
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

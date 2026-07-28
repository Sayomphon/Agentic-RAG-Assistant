"""Local-only lifecycle commands for Track A closure."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from src.evaluation.track_a_closure import (
    verify_track_a_r0_freeze,
    verify_track_a_r0_repository_state,
)
from src.evaluation.track_a_r1 import (
    R1ExecutionError,
    R1ValidationError,
    build_r1_artifact,
    verify_r1_artifact_provenance,
    write_r1_artifacts,
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Track A closure lifecycle controls."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--verify-r0-freeze",
        action="store_true",
        help="Verify frozen R0 identities against the reviewed Git baseline.",
    )
    action.add_argument(
        "--run-r1",
        action="store_true",
        help="Run and write the official R1 comparative baseline.",
    )
    action.add_argument(
        "--verify-r1-artifact",
        action="store_true",
        help="Validate the existing R1 JSON artifact without external calls.",
    )
    parser.add_argument(
        "--require-clean-worktree",
        action="store_true",
        help="Also require the approved branch, ancestry, and clean worktree.",
    )
    parser.add_argument(
        "--legacy-worktree",
        type=Path,
        help="Detached worktree at the frozen Pre-Track-A commit.",
    )
    parser.add_argument(
        "--legacy-python",
        type=Path,
        help="Python executable in the isolated legacy virtual environment.",
    )
    parser.add_argument(
        "--allow-query-embeddings",
        action="store_true",
        help="Approve sending the 40 evaluation queries for embeddings.",
    )
    args = parser.parse_args(argv)
    if args.require_clean_worktree and not args.verify_r0_freeze:
        parser.error(
            "--require-clean-worktree requires --verify-r0-freeze."
        )
    if args.run_r1 and (
        args.legacy_worktree is None or args.legacy_python is None
    ):
        parser.error(
            "--run-r1 requires --legacy-worktree and --legacy-python."
        )
    if not args.run_r1 and (
        args.legacy_worktree is not None
        or args.legacy_python is not None
        or args.allow_query_embeddings
    ):
        parser.error("R1 execution options require --run-r1.")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verify_r0_freeze:
        manifest = verify_track_a_r0_freeze()
        if args.require_clean_worktree:
            verify_track_a_r0_repository_state(manifest)
        print(
            f"Verified {manifest['closure_id']} R0 freeze "
            f"at {manifest['repository']['base_commit']}."
        )
        return 0
    if args.verify_r1_artifact:
        artifact = verify_r1_artifact_provenance()
        print(
            f"Verified {artifact['baseline_id']} at "
            f"{artifact['provenance']['evaluation_commit']}."
        )
        return 0

    try:
        artifact = build_r1_artifact(
            legacy_root=args.legacy_worktree,
            legacy_python=args.legacy_python,
            query_embeddings_approved=args.allow_query_embeddings,
        )
        write_r1_artifacts(artifact)
    except (R1ExecutionError, R1ValidationError, FileExistsError) as exc:
        print(f"R1 failed: {exc}", file=sys.stderr)
        return 1
    print("Written track_a_pre_upgrade_baseline_v2.json")
    print("Written track_a_pre_upgrade_baseline_v2.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

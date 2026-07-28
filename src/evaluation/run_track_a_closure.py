"""Local-only lifecycle commands for Track A closure."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from src.evaluation.track_a_closure import (
    verify_track_a_r0_freeze,
    verify_track_a_r0_repository_state,
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Track A closure lifecycle controls."
    )
    parser.add_argument(
        "--verify-r0-freeze",
        action="store_true",
        help="Verify frozen R0 identities against the reviewed Git baseline.",
    )
    parser.add_argument(
        "--require-clean-worktree",
        action="store_true",
        help="Also require the approved branch, ancestry, and clean worktree.",
    )
    args = parser.parse_args(argv)
    if not args.verify_r0_freeze:
        parser.error("--verify-r0-freeze is required.")
    if args.require_clean_worktree and not args.verify_r0_freeze:
        parser.error(
            "--require-clean-worktree requires --verify-r0-freeze."
        )
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = verify_track_a_r0_freeze()
    if args.require_clean_worktree:
        verify_track_a_r0_repository_state(manifest)
    print(
        f"Verified {manifest['closure_id']} R0 freeze "
        f"at {manifest['repository']['base_commit']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

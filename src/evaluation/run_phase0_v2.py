"""Create and verify the post-remediation Enterprise Phase 0 v2 checkpoint.

The execution and security boundaries are shared with ``run_phase0``. This
module changes only immutable schema/file identities, so later baseline
versions do not duplicate retrieval, health, or reporting behavior.

Usage:
    python -m src.evaluation.run_phase0_v2 --initialize-manifest
    python -m src.evaluation.run_phase0_v2 --verify-manifest-only
    python -m src.evaluation.run_phase0_v2
    python -m src.evaluation.run_phase0_v2 \
        --modes keyword semantic hybrid --allow-query-embeddings
"""

from __future__ import annotations

from collections.abc import Sequence

from src.evaluation.phase0 import PHASE0_V2_SPEC
from src.evaluation.run_phase0 import main as run_phase0


def main(argv: Sequence[str] | None = None) -> int:
    """Run Phase 0 with the immutable v2 identity and output paths."""
    return run_phase0(argv, spec=PHASE0_V2_SPEC)


if __name__ == "__main__":
    raise SystemExit(main())

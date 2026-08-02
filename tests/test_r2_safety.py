"""Tests for the offline R2 real-model benchmark boundary."""

from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from io import StringIO

from src.evaluation.run_r2_safety import (
    _fixture_hits,
    _model_specs,
    _percentile,
    parse_args,
)


class R2SafetyBenchmarkTests(unittest.TestCase):
    def test_secondary_identity_is_immutable_and_separate(self) -> None:
        primary = _model_specs()["primary"]
        secondary = _model_specs()["secondary"]

        self.assertNotEqual(primary.model, secondary.model)
        self.assertNotEqual(primary.cache_dir, secondary.cache_dir)
        self.assertRegex(primary.revision, r"^[0-9a-f]{40}$")
        self.assertEqual(
            secondary.revision,
            "2cfc18c9415c912f9d8155881c133215df768a70",
        )

    def test_synthetic_fixture_is_bounded_and_contains_no_project_content(
        self,
    ) -> None:
        hits = _fixture_hits(3)
        serialized = repr(hits).lower()

        self.assertEqual(len(hits), 3)
        self.assertNotIn("knowledge_base.txt", serialized)
        self.assertTrue(
            all(
                hit.source_file == "r2-synthetic-fixture.txt"
                for hit in hits
            )
        )

    def test_percentile_is_deterministic(self) -> None:
        self.assertEqual(_percentile([], 0.95), 0.0)
        self.assertAlmostEqual(_percentile([30.0, 10.0, 20.0], 0.50), 20.0)

    def test_model_argument_is_required_and_bounded(self) -> None:
        self.assertEqual(parse_args(["--model", "secondary"]).model, "secondary")
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["--model", "unapproved"])


if __name__ == "__main__":
    unittest.main()

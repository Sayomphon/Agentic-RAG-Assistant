"""Tests for strict, security-relevant configuration parsing."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.config import _env_optional_float


class OptionalFloatConfigTests(unittest.TestCase):
    def test_missing_or_blank_value_uses_the_reviewed_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_env_optional_float("TEST_GATE", 0.01), 0.01)
        with patch.dict(os.environ, {"TEST_GATE": "  "}, clear=True):
            self.assertEqual(_env_optional_float("TEST_GATE", 0.01), 0.01)

    def test_explicit_disable_sentinel_returns_none(self) -> None:
        for value in ("none", "off", "disabled"):
            with self.subTest(value=value):
                with patch.dict(
                    os.environ,
                    {"TEST_GATE": value},
                    clear=True,
                ):
                    self.assertIsNone(
                        _env_optional_float("TEST_GATE", 0.01)
                    )

    def test_non_finite_value_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"TEST_GATE": "nan"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "finite"):
                _env_optional_float("TEST_GATE", 0.01)


if __name__ == "__main__":
    unittest.main()

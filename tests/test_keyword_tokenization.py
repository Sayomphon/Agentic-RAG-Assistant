"""Tests for deterministic Thai-aware lexical tokenization."""

from __future__ import annotations

import unittest

from src.retrievers.keyword import (
    _normalize_query,
    _tokenize,
    has_english_search_terms,
)


class KeywordTokenizationTests(unittest.TestCase):
    """Thai support must not change the established English search path."""

    def test_thai_query_produces_deterministic_tokens(self) -> None:
        query = "พนักงานทำงานจากที่บ้านได้สัปดาห์ละกี่วัน"

        first = _tokenize(query)
        second = _tokenize(query)

        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertTrue(all(token.strip() for token in first))

    def test_mixed_script_query_keeps_both_languages(self) -> None:
        tokens = _normalize_query("ขอ work from home สัปดาห์ละกี่วัน")

        self.assertIn("remote", tokens)
        self.assertIn("work", tokens)
        self.assertTrue(any(any("\u0e00" <= char <= "\u0e7f" for char in token)
                            for token in tokens))

    def test_english_normalization_does_not_regress(self) -> None:
        self.assertEqual(
            _normalize_query("Can I work from home?"),
            ["remote", "work"],
        )
        self.assertEqual(
            _normalize_query("Vacation policies"),
            ["annual", "leave"],
        )

    def test_thai_tokens_do_not_disable_agent_translation(self) -> None:
        self.assertFalse(has_english_search_terms("ลาบวชได้กี่วัน"))
        self.assertTrue(has_english_search_terms("ขั้นตอน work from home"))


if __name__ == "__main__":
    unittest.main()

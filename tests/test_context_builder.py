"""Tests for compact, citation-preserving generator context construction."""

from __future__ import annotations

import unittest

from src.retrievers.base import Chunk, ScoredChunk
from src.retrievers.context import ContextBuilder


def _hit(index: int, title: str, text: str) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(title=title, text=text, index=index),
        score=1.0 - index / 10,
        source="hybrid",
    )


class ContextBuilderTests(unittest.TestCase):
    def test_removes_exact_duplicates_and_keeps_best_ranked_hit(self) -> None:
        builder = ContextBuilder(max_context_chars=1000, min_body_chars=5)
        hits = [
            _hit(0, "Primary", "Remote work requires manager approval."),
            _hit(1, "Duplicate", " Remote   work requires manager approval. "),
        ]

        context = builder.build(hits)

        self.assertEqual([hit.title for hit in context.hits], ["Primary"])
        self.assertEqual(
            context.snippets,
            ("[Primary]\nRemote work requires manager approval.",),
        )

    def test_prefers_diverse_evidence_over_near_duplicate_content(self) -> None:
        builder = ContextBuilder(
            max_context_chars=2000,
            duplicate_threshold=0.85,
            min_body_chars=5,
        )
        first = (
            "Employees may work remotely two days per week with manager "
            "approval through the HR portal."
        )
        hits = [
            _hit(0, "Remote Work", first),
            _hit(1, "Remote Work Copy", f"{first} Additional footer."),
            _hit(2, "VPN Usage", "Remote access requires the approved VPN client."),
        ]

        context = builder.build(hits)

        self.assertEqual(
            [hit.title for hit in context.hits],
            ["Remote Work", "VPN Usage"],
        )

    def test_enforces_total_budget_and_preserves_citation_header(self) -> None:
        builder = ContextBuilder(max_context_chars=80, min_body_chars=10)
        context = builder.build(
            [_hit(0, "Policy", "word " * 50)]
        )

        self.assertEqual(len(context.hits), 1)
        self.assertTrue(context.snippets[0].startswith("[Policy]\n"))
        self.assertLessEqual(context.total_chars, 80)
        self.assertEqual(context.total_chars, len(context.snippets[0]))
        self.assertEqual(context.hits[0].as_snippet(), context.snippets[0])
        self.assertTrue(context.hits[0].text.endswith("…"))

    def test_separator_characters_are_included_in_the_budget(self) -> None:
        builder = ContextBuilder(max_context_chars=60, min_body_chars=5)
        context = builder.build(
            [
                _hit(0, "A", "First compact evidence."),
                _hit(1, "B", "Second compact evidence."),
            ]
        )

        joined = "\n\n".join(context.snippets)
        self.assertEqual(context.total_chars, len(joined))
        self.assertLessEqual(len(joined), 60)

    def test_zero_budget_returns_no_evidence(self) -> None:
        context = ContextBuilder(max_context_chars=0).build(
            [_hit(0, "Policy", "Evidence")]
        )

        self.assertEqual(context.hits, ())
        self.assertEqual(context.snippets, ())
        self.assertEqual(context.total_chars, 0)

    def test_empty_chunk_is_never_sent_to_the_generator(self) -> None:
        context = ContextBuilder(max_context_chars=100).build(
            [_hit(0, "Empty", "   \n")]
        )

        self.assertEqual(context.hits, ())
        self.assertEqual(context.snippets, ())


if __name__ == "__main__":
    unittest.main()

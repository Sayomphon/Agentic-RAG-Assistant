"""Tests for candidate expansion and deterministic hybrid fusion."""

from __future__ import annotations

import unittest

from src.retrievers.base import Chunk, ScoredChunk
from src.retrievers.hybrid import HybridRetriever


def _hit(index: int, score: float, source: str) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(title=f"Section {index}", text="Evidence", index=index),
        score=score,
        source=source,
    )


class _RecordingRetriever:
    def __init__(self, hits: list[ScoredChunk]) -> None:
        self._hits = hits
        self.requested_top_k: list[int] = []

    def search(self, _query: str, top_k: int) -> list[ScoredChunk]:
        self.requested_top_k.append(top_k)
        return self._hits[:top_k]


class HybridCandidateExpansionTests(unittest.TestCase):
    """Candidate breadth is configurable and separate from final output size."""

    def test_fetches_candidate_k_then_returns_only_final_top_k(self) -> None:
        keyword = _RecordingRetriever(
            [_hit(index, 10.0 - index, "bm25") for index in range(8)]
        )
        dense = _RecordingRetriever(
            [_hit(index, 1.0 - index / 10, "dense") for index in range(7, -1, -1)]
        )
        retriever = HybridRetriever(keyword, dense, candidate_k=7)

        hits = retriever.search("query", top_k=2)

        self.assertEqual(keyword.requested_top_k, [7])
        self.assertEqual(dense.requested_top_k, [7])
        self.assertEqual(len(hits), 2)

    def test_never_fetches_fewer_candidates_than_the_requested_result(self) -> None:
        keyword = _RecordingRetriever([_hit(0, 1.0, "bm25")])
        dense = _RecordingRetriever([])
        retriever = HybridRetriever(keyword, dense, candidate_k=2)

        retriever.search("query", top_k=5)

        self.assertEqual(keyword.requested_top_k, [5])
        self.assertEqual(dense.requested_top_k, [5])

    def test_non_positive_top_k_skips_both_backends(self) -> None:
        keyword = _RecordingRetriever([])
        dense = _RecordingRetriever([])
        retriever = HybridRetriever(keyword, dense, candidate_k=7)

        self.assertEqual(retriever.search("query", top_k=0), [])
        self.assertEqual(keyword.requested_top_k, [])
        self.assertEqual(dense.requested_top_k, [])


if __name__ == "__main__":
    unittest.main()

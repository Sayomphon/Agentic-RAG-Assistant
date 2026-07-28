"""Integration fixtures for Thai and mixed-script lexical retrieval."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.retrievers.base import Chunk
from src.retrievers.keyword import BM25Retriever


def _thai_fixture() -> list[Chunk]:
    """Small test-only corpus; production knowledge_base.txt is untouched."""
    return [
        Chunk(
            title=(
                "นโยบายการทำงานจากบ้าน "
                "Remote Work"
            ),
            text=(
                "พนักงานสามารถทำงานจากบ้าน"
                "ได้สัปดาห์ละสองวัน "
                "เมื่อได้รับอนุมัติจากผู้จัดการ"
                "ผ่าน HR portal"
            ),
            index=0,
            source_file="thai-fixture.txt",
        ),
        Chunk(
            title="การลา Annual Leave",
            text=(
                "พนักงานยื่นคำขอลาประจำปี"
                "ผ่าน leave system"
            ),
            index=1,
            source_file="thai-fixture.txt",
        ),
        Chunk(
            title="การเดินทาง Business Travel",
            text=(
                "การเดินทางต่างประเทศ"
                "ต้องได้รับ travel approval"
            ),
            index=2,
            source_file="thai-fixture.txt",
        ),
        Chunk(
            title="ความปลอดภัย Information Security",
            text=(
                "ห้ามเปิดเผย password "
                "และต้องใช้ approved VPN"
            ),
            index=3,
            source_file="thai-fixture.txt",
        ),
    ]


def _retriever(chunks: list[Chunk]) -> BM25Retriever:
    return BM25Retriever(
        chunks,
        min_score=0.0,
        min_matched_terms=1,
        min_relative_score=0.25,
    )


class ThaiRetrievalIntegrationTests(unittest.TestCase):
    def test_thai_query_ranks_the_thai_policy_first(self) -> None:
        hits = _retriever(_thai_fixture()).search(
            (
                "ทำงานจากบ้านได้"
                "สัปดาห์ละกี่วัน"
            ),
            top_k=2,
        )

        self.assertTrue(hits)
        self.assertEqual(
            hits[0].title,
            "นโยบายการทำงานจากบ้าน Remote Work",
        )

    def test_mixed_thai_english_query_ranks_the_same_policy(self) -> None:
        hits = _retriever(_thai_fixture()).search(
            "ขอ work from home สัปดาห์ละกี่วัน",
            top_k=2,
        )

        self.assertTrue(hits)
        self.assertEqual(
            hits[0].title,
            "นโยบายการทำงานจากบ้าน Remote Work",
        )

    def test_disabling_thai_tokenizer_defines_thai_only_as_not_searchable(
        self,
    ) -> None:
        with patch(
            "src.retrievers.keyword.THAI_TOKENIZER_ENABLED",
            False,
        ):
            hits = _retriever(_thai_fixture()).search(
                (
                    "ทำงานจากบ้านได้"
                    "สัปดาห์ละกี่วัน"
                ),
                top_k=2,
            )

        self.assertEqual(hits, [])

    def test_english_fixture_does_not_regress(self) -> None:
        hits = _retriever(_thai_fixture()).search(
            "international travel approval",
            top_k=1,
        )

        self.assertEqual(
            [hit.title for hit in hits],
            ["การเดินทาง Business Travel"],
        )


if __name__ == "__main__":
    unittest.main()

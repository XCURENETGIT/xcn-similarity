from __future__ import annotations

import unittest
from datetime import datetime

from pydantic import ValidationError

from app.schemas import (
    DocumentRegisterRequest,
    MiddlewareAnalyzeRequest,
    SearchDocumentsRequest,
    SearchLogsRequest,
    SimilarityHit,
)
from app.similarity_engine.chunker import chunk_text
from app.similarity_engine.text_normalizer import normalize_text_for_embedding
from app.similarity_engine.catalog import _log_retention_delete_filter
from app.similarity_engine.vector_store import _milvus_filter, month_partition_names_between
from app.search_logging import search_hit_log_items
from app.time_utils import kst_iso, kst_naive_iso, normalize_kst_payload


class TextNormalizerTest(unittest.TestCase):
    def test_html_text_is_extracted_without_script_or_style_content(self) -> None:
        raw = """
        <html>
          <head><style>.hidden { display: none; }</style></head>
          <body>
            <p>영업전략&nbsp;문서</p>
            <script>console.log("secret")</script>
            <div>외부 전송 검증</div>
          </body>
        </html>
        """

        normalized = normalize_text_for_embedding(raw)

        self.assertIn("영업전략 문서", normalized)
        self.assertIn("외부 전송 검증", normalized)
        self.assertNotIn("console.log", normalized)
        self.assertNotIn("display: none", normalized)

    def test_control_characters_and_repeated_whitespace_are_normalized(self) -> None:
        normalized = normalize_text_for_embedding("  alpha\x00\t beta  \n\n\n   gamma  ")

        self.assertEqual(normalized, "alpha beta\n\ngamma")


class ChunkerValidationTest(unittest.TestCase):
    def test_empty_text_returns_no_chunks(self) -> None:
        chunks = chunk_text("", chunk_size=10, chunk_overlap=2, min_chunk_chars=3, max_chunks=10)

        self.assertEqual(chunks, [])

    def test_short_text_below_minimum_still_returns_one_chunk(self) -> None:
        chunks = chunk_text("짧은 본문", chunk_size=100, chunk_overlap=10, min_chunk_chars=50, max_chunks=10)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_id, "chunk-000000")
        self.assertEqual(chunks[0].text, "짧은 본문")

    def test_chunks_respect_sentence_boundary_limit_and_sequential_ids(self) -> None:
        text = "Alpha sentence. Beta sentence. Gamma sentence. Delta sentence."

        chunks = chunk_text(text, chunk_size=32, chunk_overlap=0, min_chunk_chars=5, max_chunks=2)

        self.assertEqual([chunk.chunk_id for chunk in chunks], ["chunk-000000", "chunk-000001"])
        self.assertLessEqual(len(chunks), 2)
        self.assertEqual(chunks[0].text, "Alpha sentence. Beta sentence.")
        self.assertGreater(chunks[1].start, chunks[0].start)


class SchemaValidationTest(unittest.TestCase):
    def test_document_registration_requires_title_and_text(self) -> None:
        with self.assertRaises(ValidationError):
            DocumentRegisterRequest(title="", text="본문")

        with self.assertRaises(ValidationError):
            DocumentRegisterRequest(title="문서", text="")

    def test_search_documents_request_enforces_score_and_top_k_ranges(self) -> None:
        with self.assertRaises(ValidationError):
            SearchDocumentsRequest(text="query", top_k=0)

        with self.assertRaises(ValidationError):
            SearchDocumentsRequest(text="query", top_k=101)

        with self.assertRaises(ValidationError):
            SearchDocumentsRequest(text="query", min_score=1.1)

    def test_search_logs_request_enforces_document_id_and_top_k_ranges(self) -> None:
        with self.assertRaises(ValidationError):
            SearchLogsRequest(document_id="", top_k=20)

        with self.assertRaises(ValidationError):
            SearchLogsRequest(document_id="doc-1", top_k=201)

    def test_middleware_request_accepts_ems_id_alias(self) -> None:
        request = MiddlewareAnalyzeRequest(svc="EMMS", _id="202607100001.sample")

        self.assertEqual(request.id, "202607100001.sample")
        self.assertEqual(request.model_dump(by_alias=True)["_id"], "202607100001.sample")


class SearchLoggingTest(unittest.TestCase):
    def test_log_text_search_summary_has_scores_and_ids_without_text(self) -> None:
        hits = [
            SimilarityHit(
                score=0.8752621,
                target_type="log",
                target_id="20260713194709.sample:body",
                chunk_id="chunk-000000",
                text_preview="sensitive preview",
                metadata={"msg_id": "20260713194709.sample", "source_type": "body", "svc": "WNTS"},
            )
        ]

        items = search_hit_log_items(hits)

        self.assertEqual(items[0]["score"], 0.875262)
        self.assertEqual(items[0]["target_id"], "20260713194709.sample:body")
        self.assertEqual(items[0]["msg_id"], "20260713194709.sample")
        self.assertNotIn("text", items[0])
        self.assertNotIn("text_preview", items[0])


class MilvusFilterTimezoneTest(unittest.TestCase):
    def test_utc_ctime_range_is_converted_to_kst_storage_format(self) -> None:
        expression = _milvus_filter(
            {
                "source_type": "body",
                "ctime": {
                    "$gte": "2026-07-12T15:00:00.000Z",
                    "$lte": "2026-07-13T14:59:59.999Z",
                },
            }
        )

        self.assertIn('metadata["ctime"] >= "2026-07-13T00:00:00"', expression)
        self.assertIn('metadata["ctime"] <= "2026-07-13T23:59:59.999000"', expression)

    def test_naive_kst_ctime_range_is_preserved(self) -> None:
        expression = _milvus_filter({"ctime": {"$gte": "2026-07-13T00:00:00"}})

        self.assertIn('metadata["ctime"] >= "2026-07-13T00:00:00"', expression)

    def test_month_partitions_use_kst_month_at_utc_boundary(self) -> None:
        names = month_partition_names_between(
            datetime.fromisoformat("2026-07-31T15:00:00+00:00"),
            datetime.fromisoformat("2026-07-31T23:59:59+00:00"),
            include_default=False,
        )

        self.assertEqual(names, ["m_202608"])

    def test_month_partitions_accept_mixed_aware_and_naive_values(self) -> None:
        names = month_partition_names_between(
            datetime.fromisoformat("2026-07-31T15:00:00+00:00"),
            datetime.fromisoformat("2026-08-02T00:00:00"),
            include_default=False,
        )

        self.assertEqual(names, ["m_202608"])


class KstTimestampTest(unittest.TestCase):
    def test_external_timestamp_is_rendered_as_kst(self) -> None:
        self.assertEqual(kst_iso(datetime.fromisoformat("2026-07-13T11:00:00+00:00")), "2026-07-13T20:00:00+09:00")

    def test_retention_cutoff_matches_naive_kst_ctime_storage(self) -> None:
        query = _log_retention_delete_filter(svc_values=["*"], delete_before="2026-07-13T11:00:00Z")

        self.assertEqual(query["metadata.ctime"]["$lt"], "2026-07-13T20:00:00")
        self.assertEqual(kst_naive_iso("2026-07-13T20:00:00+09:00"), "2026-07-13T20:00:00")

    def test_nested_legacy_utc_timestamp_is_returned_as_kst(self) -> None:
        payload = normalize_kst_payload({"data": {"generated_at": "2026-07-13T11:39:51.626133+00:00"}})

        self.assertEqual(payload["data"]["generated_at"], "2026-07-13T20:39:51.626133+09:00")


if __name__ == "__main__":
    unittest.main()

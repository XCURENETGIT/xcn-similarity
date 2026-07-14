from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any
from app.schemas import ChunkItem, CollectionStats, DocumentInfo, LogInfo, LogListItem, SimilarityHit
from app.time_utils import KST, as_kst, kst_naive_iso, now_kst

from .chunker import chunk_text
from .catalog import SimilarityCatalog
from .config import SimilarityConfig, load_config
from .embedder import Embedder, build_embedder
from .kafka_delivery import SimpleKafkaProducer
from .storage_stats import milvus_collection_storage_bytes
from .text_normalizer import normalize_text_for_embedding
from .vector_store import VectorRecord, VectorStore, build_vector_store, month_partition_names_between


DOCUMENT_COLLECTION = "document_chunks"
LOG_COLLECTION = "log_body_chunks"
logger = logging.getLogger(__name__)


class SimilarityProcessingTimeout(Exception):
    """Raised when a cooperative processing deadline is exceeded."""


class SimilarityEngine:
    def __init__(self, config: SimilarityConfig | None = None):
        self.config = config or load_config()
        self.embedder: Embedder = build_embedder(self.config)
        self.store: VectorStore = build_vector_store(
            milvus_url=self.config.milvus_url,
            dim=self.embedder.dim,
        )
        self.catalog = SimilarityCatalog(
            mongo_uri=self.config.catalog_mongo_uri,
            database=self.config.catalog_database,
            log_collection=self.config.log_catalog_collection,
            document_collection=self.config.document_catalog_collection,
            review_collection=self.config.review_collection,
            match_cache_collection=self.config.match_cache_collection,
            similarity_result_collection=self.config.similarity_result_collection,
            kafka_producer=(
                SimpleKafkaProducer(
                    bootstrap_servers=self.config.kafka_bootstrap_servers,
                    topic=self.config.kafka_topic,
                    client_id=self.config.kafka_client_id,
                    timeout_sec=self.config.kafka_timeout_sec,
                )
                if self.config.kafka_enabled
                else None
            ),
        )
        self._documents: dict[str, DocumentInfo] = {}
        self._logs: dict[str, LogInfo] = {}
        self._document_texts: dict[str, str] = {}
        self._lock = RLock()
        self._storage_stats_cache: tuple[float, dict[str, int]] | None = None

    def register_document(
        self,
        *,
        title: str,
        text: str,
        owner: str | None,
        department: str | None,
        security_level: str | None,
        metadata: dict[str, Any],
    ) -> DocumentInfo:
        op_started = time.perf_counter()
        normalize_started = time.perf_counter()
        text = normalize_text_for_embedding(text)
        normalize_ms = _elapsed_ms(normalize_started)
        metadata = dict(metadata or {})
        text_hidden = metadata.get("file_retained") is False
        document_id = "doc_" + hashlib.sha256(f"{title}\n{text}".encode("utf-8", errors="ignore")).hexdigest()[:24]
        chunk_started = time.perf_counter()
        chunks = chunk_text(
            text,
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            min_chunk_chars=self.config.min_chunk_chars,
            max_chunks=self.config.max_document_chunks,
        )
        chunk_ms = _elapsed_ms(chunk_started)
        embed_started = time.perf_counter()
        vectors = self.embedder.embed([c.text for c in chunks]) if chunks else []
        embed_ms = _elapsed_ms(embed_started)
        records = [
            VectorRecord(
                id=f"{document_id}:{chunk.chunk_id}",
                collection=DOCUMENT_COLLECTION,
                vector=vector,
                text="" if text_hidden else chunk.text,
                metadata={
                    **metadata,
                    "target_type": "document",
                    "document_id": document_id,
                    "chunk_id": chunk.chunk_id,
                    "title": title,
                    "owner": owner,
                    "department": department,
                    "security_level": security_level,
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        upsert_started = time.perf_counter()
        self.store.upsert(records)
        upsert_ms = _elapsed_ms(upsert_started)
        info = DocumentInfo(
            document_id=document_id,
            title=title,
            owner=owner,
            department=department,
            security_level=security_level,
            status="INDEXED",
            chunk_count=len(chunks),
            created_at=now_kst(),
            metadata=metadata,
        )
        with self._lock:
            self._documents[document_id] = info
            if text_hidden:
                self._document_texts.pop(document_id, None)
            else:
                self._document_texts[document_id] = text
        self.catalog.upsert_document(info)
        logger.info(
            "document register completed document_id=%s title=%s chars=%d chunks=%d vectors=%d text_filter=%s file_name=%s normalize_ms=%.1f chunk_ms=%.1f embed_ms=%.1f upsert_ms=%.1f total_ms=%.1f",
            document_id,
            title,
            len(text),
            len(chunks),
            len(vectors),
            metadata.get("text_filter"),
            metadata.get("file_name"),
            normalize_ms,
            chunk_ms,
            embed_ms,
            upsert_ms,
            _elapsed_ms(op_started),
        )
        return info

    def list_documents(self) -> list[DocumentInfo]:
        catalog_docs = self.catalog.list_documents()
        if catalog_docs:
            with self._lock:
                for info in catalog_docs:
                    self._documents[info.document_id] = info
            return catalog_docs
        with self._lock:
            cached = [info for info in self._documents.values() if info.status != "DELETED"]
        if cached:
            return cached
        records, _ = self.store.scroll(DOCUMENT_COLLECTION, limit=1000)
        by_doc: dict[str, dict[str, Any]] = {}
        for record in records:
            doc_id = str(record.metadata.get("document_id") or "")
            if not doc_id:
                continue
            item = by_doc.setdefault(
                doc_id,
                {
                    "document_id": doc_id,
                    "title": str(record.metadata.get("title") or doc_id),
                    "owner": record.metadata.get("owner"),
                    "department": record.metadata.get("department"),
                    "security_level": record.metadata.get("security_level"),
                    "chunk_count": 0,
                    "metadata": {
                        k: v
                        for k, v in record.metadata.items()
                        if k
                        not in {
                            "target_type",
                            "document_id",
                            "chunk_id",
                            "title",
                            "owner",
                            "department",
                            "security_level",
                            "record_id",
                        }
                    },
                },
            )
            item["chunk_count"] += 1
        now = now_kst()
        docs = [
            DocumentInfo(
                document_id=item["document_id"],
                title=item["title"],
                owner=item["owner"],
                department=item["department"],
                security_level=item["security_level"],
                status="INDEXED",
                chunk_count=item["chunk_count"],
                created_at=now,
                metadata=item["metadata"],
            )
            for item in sorted(by_doc.values(), key=lambda x: str(x["title"]))
        ]
        for info in docs:
            self.catalog.upsert_document(info)
        return docs

    def search_document_catalog(
        self,
        *,
        query: str | None = None,
        limit: int = 30,
        offset: int = 0,
        security_level: str | None = None,
        department: str | None = None,
        owner: str | None = None,
    ) -> tuple[list[DocumentInfo], int | None]:
        docs, next_offset = self.catalog.search_documents(
            query=query,
            limit=limit,
            offset=offset,
            security_level=security_level,
            department=department,
            owner=owner,
        )
        if docs:
            with self._lock:
                for info in docs:
                    self._documents[info.document_id] = info
        return docs, next_offset

    def delete_document(self, document_id: str) -> int:
        started = time.perf_counter()
        removed = self.store.delete_by_metadata(DOCUMENT_COLLECTION, {"document_id": document_id})
        self.catalog.mark_document_deleted(document_id)
        with self._lock:
            info = self._documents.get(document_id)
            if info is not None:
                updated = info.model_copy(update={"status": "DELETED", "deleted_at": now_kst()})
                self._documents[document_id] = updated
            self._document_texts.pop(document_id, None)
        logger.info("document delete completed document_id=%s removed_chunks=%s elapsed_ms=%.1f", document_id, removed, _elapsed_ms(started))
        return removed

    def update_document(
        self,
        document_id: str,
        *,
        title: str | None = None,
        owner: str | None = None,
        department: str | None = None,
        security_level: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentInfo | None:
        info = self.catalog.update_document_info(
            document_id,
            title=title,
            owner=owner,
            department=department,
            security_level=security_level,
            metadata=metadata,
        )
        if info is None:
            return None
        with self._lock:
            self._documents[document_id] = info
        return info

    def index_log(
        self,
        *,
        log_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> LogInfo:
        started = time.perf_counter()
        text = normalize_text_for_embedding(text)
        chunks = chunk_text(
            text,
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            min_chunk_chars=self.config.min_chunk_chars,
            max_chunks=self.config.max_log_chunks,
        )
        vectors = self.embedder.embed([c.text for c in chunks]) if chunks else []
        records = [
            VectorRecord(
                id=f"{log_id}:{chunk.chunk_id}",
                collection=LOG_COLLECTION,
                vector=vector,
                text=chunk.text,
                metadata={
                    **metadata,
                    "target_type": "log",
                    "log_id": log_id,
                    "chunk_id": chunk.chunk_id,
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        self.store.upsert(records)
        info = LogInfo(
            log_id=log_id,
            status="INDEXED",
            chunk_count=len(chunks),
            created_at=now_kst(),
            metadata=metadata,
        )
        with self._lock:
            self._logs[log_id] = info
        self.catalog.upsert_log(
            log_id=log_id,
            chunk_count=len(chunks),
            sample_text=chunks[0].text if chunks else "",
            metadata=metadata,
        )
        self._generate_similarity_result_parts(
            normalized_items=[{"log_id": log_id, "metadata": metadata, "chunks": chunks}],
            chunk_refs=[(log_id, chunk) for chunk in chunks],
            vectors=vectors,
        )
        logger.info(
            "log index completed log_id=%s chars=%d chunks=%d vectors=%d source_type=%s elapsed_ms=%.1f",
            log_id,
            len(text),
            len(chunks),
            len(vectors),
            metadata.get("source_type"),
            _elapsed_ms(started),
        )
        return info

    def index_logs(
        self,
        items: list[dict[str, Any]],
        *,
        deadline: float | None = None,
        max_total_chunks: int | None = None,
        max_total_chars: int | None = None,
        max_item_chars: int | None = None,
        return_summary: bool = False,
    ) -> list[LogInfo] | tuple[list[LogInfo], dict[str, Any]]:
        op_started = time.perf_counter()
        normalized_items: list[dict[str, Any]] = []
        texts_to_embed: list[str] = []
        chunk_refs: list[tuple[str, Any]] = []
        input_chars = 0
        original_chars = 0
        skipped_items = 0
        truncated_items = 0
        timeout_reached = False
        limit_reached = False
        stop_reason = ""
        chunk_started = time.perf_counter()
        max_total_chunks = int(max_total_chunks) if max_total_chunks is not None else None
        max_total_chars = int(max_total_chars) if max_total_chars is not None else None
        max_item_chars = int(max_item_chars) if max_item_chars is not None else None

        for item in items:
            if deadline is not None and time.perf_counter() >= deadline:
                timeout_reached = True
                stop_reason = "timeout_before_chunking"
                skipped_items += 1
                break
            log_id = str(item.get("log_id") or "").strip()
            if not log_id:
                continue
            metadata = dict(item.get("metadata") or {})
            text = normalize_text_for_embedding(str(item.get("text") or ""))
            raw_chars = len(text)
            original_chars += raw_chars
            if max_total_chars is not None and input_chars >= max_total_chars:
                limit_reached = True
                stop_reason = "max_total_chars"
                skipped_items += 1
                break
            if max_item_chars is not None and raw_chars > max_item_chars:
                metadata["truncated"] = True
                metadata["truncated_reason"] = "max_item_chars"
                metadata["original_chars"] = raw_chars
                metadata["processed_chars"] = max_item_chars
                text = text[:max_item_chars]
                truncated_items += 1
            if max_total_chars is not None and input_chars + len(text) > max_total_chars:
                allowed_chars = max(0, max_total_chars - input_chars)
                metadata["truncated"] = True
                metadata["truncated_reason"] = "max_total_chars"
                metadata["original_chars"] = raw_chars
                metadata["processed_chars"] = allowed_chars
                text = text[:allowed_chars]
                truncated_items += 1
                limit_reached = True
                stop_reason = "max_total_chars"
            input_chars += len(text)
            chunks = chunk_text(
                text,
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                min_chunk_chars=self.config.min_chunk_chars,
                max_chunks=self.config.max_log_chunks,
            )
            if max_total_chunks is not None and len(chunk_refs) + len(chunks) > max_total_chunks:
                allowed_chunks = max(0, max_total_chunks - len(chunk_refs))
                metadata["truncated"] = True
                metadata["truncated_reason"] = "max_total_chunks"
                metadata["original_chunks"] = len(chunks)
                metadata["processed_chunks"] = allowed_chunks
                chunks = chunks[:allowed_chunks]
                truncated_items += 1
                limit_reached = True
                stop_reason = "max_total_chunks"
            normalized_items.append({"log_id": log_id, "metadata": metadata, "chunks": chunks})
            for chunk in chunks:
                texts_to_embed.append(chunk.text)
                chunk_refs.append((log_id, chunk))
            if limit_reached:
                break

        chunk_ms = _elapsed_ms(chunk_started)
        embed_started = time.perf_counter()
        vectors: list[list[float]] = []
        embed_batches = 0
        if texts_to_embed and deadline is None:
            vectors = self.embedder.embed(texts_to_embed)
            embed_batches = 1
        elif texts_to_embed:
            for idx, text in enumerate(texts_to_embed):
                if deadline is not None and time.perf_counter() >= deadline:
                    timeout_reached = True
                    stop_reason = "timeout_during_embedding"
                    break
                batch_vectors = self.embedder.embed([text])
                if batch_vectors:
                    vectors.append(batch_vectors[0])
                embed_batches += 1
            if len(vectors) < len(chunk_refs):
                chunk_refs = chunk_refs[: len(vectors)]
                texts_to_embed = texts_to_embed[: len(vectors)]
        embed_ms = _elapsed_ms(embed_started)
        metadata_by_log = {item["log_id"]: item["metadata"] for item in normalized_items}
        records = [
            VectorRecord(
                id=f"{log_id}:{chunk.chunk_id}",
                collection=LOG_COLLECTION,
                vector=vector,
                text=chunk.text,
                metadata={
                    **metadata_by_log.get(log_id, {}),
                    "target_type": "log",
                    "log_id": log_id,
                    "chunk_id": chunk.chunk_id,
                },
            )
            for (log_id, chunk), vector in zip(chunk_refs, vectors)
        ]
        upsert_started = time.perf_counter()
        self.store.upsert(records)
        upsert_ms = _elapsed_ms(upsert_started)

        now = now_kst()
        infos: list[LogInfo] = []
        catalog_rows: list[dict[str, Any]] = []
        processed_chunks_by_log: dict[str, list[Any]] = {}
        for log_id, chunk in chunk_refs:
            processed_chunks_by_log.setdefault(log_id, []).append(chunk)
        for item in normalized_items:
            chunks = processed_chunks_by_log.get(item["log_id"], [])
            metadata = dict(item["metadata"])
            if len(chunks) < len(item["chunks"]):
                metadata["partial"] = True
                metadata["partial_reason"] = stop_reason or "partial_processing"
                metadata["original_chunks"] = len(item["chunks"])
                metadata["processed_chunks"] = len(chunks)
            info = LogInfo(
                log_id=item["log_id"],
                status="INDEXED",
                chunk_count=len(chunks),
                created_at=now,
                metadata=metadata,
            )
            infos.append(info)
            catalog_rows.append(
                {
                    "log_id": info.log_id,
                    "chunk_count": info.chunk_count,
                    "sample_text": chunks[0].text if chunks else "",
                    "metadata": info.metadata,
                }
            )
        with self._lock:
            for info in infos:
                self._logs[info.log_id] = info
        self.catalog.bulk_upsert_logs(catalog_rows)
        similarity_started = time.perf_counter()
        self._generate_similarity_result_parts(
            normalized_items=normalized_items,
            chunk_refs=chunk_refs,
            vectors=vectors,
            deadline=deadline,
        )
        similarity_ms = _elapsed_ms(similarity_started)
        partial = timeout_reached or limit_reached or skipped_items > 0 or any(
            bool(info.metadata.get("partial") or info.metadata.get("truncated")) for info in infos
        )
        summary = {
            "partial": partial,
            "timeout": timeout_reached,
            "limit_reached": limit_reached,
            "stop_reason": stop_reason,
            "input_items": len(items),
            "indexed_items": len(infos),
            "skipped_items": skipped_items + max(0, len(items) - len(normalized_items) - skipped_items),
            "truncated_items": truncated_items,
            "original_chars": original_chars,
            "processed_chars": input_chars,
            "original_chunks": sum(len(item["chunks"]) for item in normalized_items),
            "processed_chunks": len(chunk_refs),
            "vectors": len(vectors),
        }
        logger.info(
            "logs index completed items=%d indexed=%d chars=%d original_chars=%d chunks=%d vectors=%d partial=%s timeout=%s limit_reached=%s stop_reason=%s embed_batches=%d chunk_ms=%.1f embed_ms=%.1f upsert_ms=%.1f similarity_ms=%.1f total_ms=%.1f",
            len(items),
            len(infos),
            input_chars,
            original_chars,
            len(chunk_refs),
            len(vectors),
            partial,
            timeout_reached,
            limit_reached,
            stop_reason,
            embed_batches,
            chunk_ms,
            embed_ms,
            upsert_ms,
            similarity_ms,
            _elapsed_ms(op_started),
        )
        if return_summary:
            return infos, summary
        return infos

    def _generate_similarity_result_parts(
        self,
        *,
        normalized_items: list[dict[str, Any]],
        chunk_refs: list[tuple[str, Any]],
        vectors: list[list[float]],
        deadline: float | None = None,
    ) -> None:
        started = time.perf_counter()
        if not self.config.similarity_result_enabled or not normalized_items:
            logger.info(
                "similarity result skipped enabled=%s items=%d chunks=%d",
                self.config.similarity_result_enabled,
                len(normalized_items),
                len(chunk_refs),
            )
            return
        top_k = max(1, int(self.config.similarity_result_top_k or 5))
        min_score = max(-1.0, min(float(self.config.similarity_result_min_score), 1.0))
        best_by_log_doc: dict[tuple[str, str], dict[str, Any]] = {}
        metadata_by_log = {str(item["log_id"]): dict(item.get("metadata") or {}) for item in normalized_items}
        max_attempts = self._similarity_result_search_attempts()
        searches = 0
        hits_seen = 0
        timeout_reached = False
        for attempt in range(max_attempts):
            for (log_id, chunk), vector in zip(chunk_refs, vectors):
                if deadline is not None and time.perf_counter() >= deadline:
                    timeout_reached = True
                    break
                if not vector:
                    continue
                searches += 1
                hits = self.store.search(
                    DOCUMENT_COLLECTION,
                    vector,
                    top_k=top_k,
                    min_score=min_score,
                    metadata_filter={},
                )
                hits_seen += len(hits)
                for hit in hits:
                    doc_meta = dict(hit.record.metadata or {})
                    document_id = str(doc_meta.get("document_id") or hit.record.id).strip()
                    if not document_id:
                        continue
                    key = (str(log_id), document_id)
                    old = best_by_log_doc.get(key)
                    if old is not None and float(old.get("score") or 0.0) >= float(hit.score):
                        continue
                    evidence = _match_evidence(
                        document_text=str(getattr(hit.record, "text", "") or ""),
                        log_text=str(getattr(chunk, "text", "") or ""),
                        raw_score=float(hit.score),
                    )
                    best_by_log_doc[key] = {
                        "document_id": document_id,
                        "document_title": str(doc_meta.get("title") or document_id),
                        "document_chunk_id": str(doc_meta.get("chunk_id") or hit.record.id),
                        "document_security_level": doc_meta.get("security_level"),
                        "log_chunk_id": str(getattr(chunk, "chunk_id", "") or ""),
                        "_match_document_text_preview": str(getattr(hit.record, "text", "") or "")[:1000],
                        "_match_log_text_preview": str(getattr(chunk, "text", "") or "")[:1000],
                        "score": evidence["score"],
                        "score_percent": round(evidence["score"] * 100, 2),
                        "raw_score": evidence["raw_score"],
                        "weighted_coverage_score": evidence["weighted_coverage_score"],
                        "phrase_match_score": evidence["phrase_match_score"],
                        "matched_terms": evidence["matched_terms"],
                        "matched_keywords": evidence["matched_keywords"],
                        "matched_terms_description": evidence["matched_terms_description"],
                        "score_breakdown": evidence["score_breakdown"],
                        "score_weight_policy": evidence["score_weight_policy"],
                        "reason": f"등록문서와 {evidence['score'] * 100:.2f}% 유사",
                    }
            if timeout_reached:
                break
            if attempt >= max_attempts - 1:
                break
            time.sleep(max(0.0, float(self.config.similarity_result_search_retry_delay_sec)))
        parts: list[dict[str, Any]] = []
        for item in normalized_items:
            log_id = str(item.get("log_id") or "")
            metadata = dict(metadata_by_log.get(log_id, {}))
            if timeout_reached:
                metadata["partial"] = True
                metadata["partial_reason"] = "timeout_during_similarity_search"
            msgid = _log_msgid(log_id, metadata)
            result_key = _log_result_key(log_id, metadata)
            matches = sorted(
                [value for (item_log_id, _), value in best_by_log_doc.items() if item_log_id == log_id],
                key=lambda value: float(value.get("score") or 0.0),
                reverse=True,
            )[:top_k]
            max_score = float(matches[0]["score"]) if matches else 0.0
            risk = _result_risk_level(
                max_score,
                low=float(self.config.grey_zone_low_score),
                high=float(self.config.grey_zone_high_score),
            )
            parts.append(
                {
                    "msgid": msgid,
                    "result_key": result_key,
                    "result": {
                        "target": "attach" if result_key.startswith("attach_") else "body",
                        "attach_index": _log_attach_index(log_id, metadata),
                        "max_score": round(max_score, 6),
                        "risk_level": risk if risk != "none" else "low",
                        "review_scope": _review_scope(risk),
                        "review_status": "unreviewed",
                        "matches": matches,
                    },
                }
            )
        self.catalog.upsert_similarity_result_parts(
            parts=parts,
            thresholds={
                "min_score": min_score,
                "grey_zone_low_score": float(self.config.grey_zone_low_score),
                "grey_zone_high_score": float(self.config.grey_zone_high_score),
            },
        )
        logger.info(
            "similarity result completed items=%d chunks=%d attempts=%d searches=%d hits=%d matches=%d parts=%d timeout=%s min_score=%.3f top_k=%d elapsed_ms=%.1f",
            len(normalized_items),
            len(chunk_refs),
            max_attempts,
            searches,
            hits_seen,
            len(best_by_log_doc),
            len(parts),
            timeout_reached,
            min_score,
            top_k,
            _elapsed_ms(started),
        )

    def _similarity_result_search_attempts(self) -> int:
        retries = max(0, int(self.config.similarity_result_search_retries or 0))
        if retries <= 0:
            return 1
        window_sec = max(0, int(self.config.similarity_result_recent_document_window_sec or 0))
        if window_sec <= 0:
            return 1 + retries
        since = now_kst() - timedelta(seconds=window_sec)
        if self.catalog.count_documents_created_since(since) <= 0:
            return 1
        return 1 + retries

    def stats(self) -> CollectionStats:
        docs = self.list_documents()
        document_chunks = sum(doc.chunk_count for doc in docs)
        log_chunks = self.catalog.count_log_chunks()
        storage_bytes = self._physical_index_bytes()
        document_index_bytes = storage_bytes.get(DOCUMENT_COLLECTION, 0)
        log_index_bytes = storage_bytes.get(LOG_COLLECTION, 0)
        total_index_bytes = document_index_bytes + log_index_bytes
        storage_paths = self._storage_path_stats()
        monitor_alerts = self._monitor_alerts(
            storage_paths=storage_paths,
            document_chunks=document_chunks,
            log_chunks=log_chunks,
        )
        today_kst = now_kst().replace(hour=0, minute=0, second=0, microsecond=0)
        return CollectionStats(
            document_chunks=document_chunks,
            log_chunks=log_chunks,
            documents=len(docs),
            logs=self.catalog.count_logs(),
            documents_today=self.catalog.count_documents_created_since(today_kst),
            logs_today=self.catalog.count_logs_created_since(today_kst),
            document_index_bytes=document_index_bytes,
            log_index_bytes=log_index_bytes,
            total_index_bytes=total_index_bytes,
            storage_paths=storage_paths,
            monitor_alerts=monitor_alerts,
            retention_policy=self._retention_policy(),
            recent_match_policy=self._recent_match_policy(len(docs)),
        )

    def _physical_index_bytes(self) -> dict[str, int]:
        root = str(self.config.milvus_object_root or "").strip()
        if not root:
            return {DOCUMENT_COLLECTION: 0, LOG_COLLECTION: 0}
        now = now_kst().timestamp()
        ttl = max(0, int(self.config.storage_stats_ttl_sec or 0))
        if self._storage_stats_cache and ttl:
            cached_at, cached = self._storage_stats_cache
            if now - cached_at < ttl:
                return dict(cached)
        values = {
            DOCUMENT_COLLECTION: milvus_collection_storage_bytes(root, self.store.collection_id(DOCUMENT_COLLECTION)),
            LOG_COLLECTION: milvus_collection_storage_bytes(root, self.store.collection_id(LOG_COLLECTION)),
        }
        self._storage_stats_cache = (now, values)
        return dict(values)

    def _storage_path_stats(self) -> list[dict[str, Any]]:
        seen: set[str] = set()
        grouped: dict[int, dict[str, Any]] = {}
        order: list[int] = []
        for raw in str(self.config.monitor_paths or "").split(","):
            path = raw.strip()
            if not path or path in seen or not os.path.exists(path):
                continue
            seen.add(path)
            try:
                device_id = int(os.stat(path).st_dev)
                usage = shutil.disk_usage(path)
            except OSError:
                continue
            total = int(usage.total)
            used = int(usage.used)
            free = int(usage.free)
            used_percent = round((used / total) * 100, 2) if total else 0.0
            label = {
                "/": "container runtime",
                "/logs": "log storage",
                "/minio_data": "vector object storage",
            }.get(path, path)
            if device_id not in grouped:
                grouped[device_id] = {
                    "path": path,
                    "paths": [path],
                    "labels": [label],
                    "label": label,
                    "total_bytes": total,
                    "used_bytes": used,
                    "free_bytes": free,
                    "used_percent": used_percent,
                }
                order.append(device_id)
            else:
                item = grouped[device_id]
                paths = item.setdefault("paths", [])
                if path not in paths:
                    paths.append(path)
                item["path"] = ", ".join(paths)
                labels = item.setdefault("labels", [])
                if label not in labels:
                    labels.append(label)
                item["label"] = " / ".join(str(value) for value in labels if value)
        return [grouped[key] for key in order]

    def _monitor_alerts(
        self,
        *,
        storage_paths: list[dict[str, Any]],
        document_chunks: int,
        log_chunks: int,
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        warn = float(self.config.disk_warn_percent)
        critical = float(self.config.disk_critical_percent)
        for item in storage_paths:
            used_percent = float(item.get("used_percent") or 0.0)
            if used_percent >= critical:
                level = "critical"
            elif used_percent >= warn:
                level = "warning"
            else:
                continue
            alerts.append(
                {
                    "level": level,
                    "type": "disk",
                    "path": item.get("path"),
                    "message": f"{item.get('label') or item.get('path')} disk usage {used_percent:.1f}%",
                    "used_percent": used_percent,
                }
            )
        total_rows = int(document_chunks or 0) + int(log_chunks or 0)
        row_warn = max(0, int(self.config.vector_row_warn_count or 0))
        if row_warn and total_rows >= row_warn:
            alerts.append(
                {
                    "level": "warning",
                    "type": "vector_rows",
                    "message": f"vector row count {total_rows:,} exceeds warning threshold {row_warn:,}",
                    "row_count": total_rows,
                    "threshold": row_warn,
                }
            )
        return alerts

    def _retention_policy(self) -> dict[str, Any]:
        return {
            "mode": "policy_only",
            "hot_days": max(1, int(self.config.retention_hot_days or 90)),
            "warm_days": max(1, int(self.config.retention_warm_days or 365)),
            "archive_days": max(1, int(self.config.retention_archive_days or 1095)),
            "log_delete_before_days": max(0, int(self.config.log_delete_before_days or 0)),
            "log_retention_svc": _normalize_svc_values(self.config.log_retention_svc),
            "log_retention_policy": self.config.log_retention_policy,
            "log_retention_delete_results": bool(self.config.log_retention_delete_results),
            "log_retention_delete_reviews": bool(self.config.log_retention_delete_reviews),
            "log_retention_clear_match_cache": bool(self.config.log_retention_clear_match_cache),
            "cleanup_enabled": bool(self.config.cleanup_enabled),
            "cleanup_dry_run": bool(self.config.cleanup_dry_run),
            "upload_deleted_retention_days": max(0, int(self.config.upload_deleted_retention_days or 0)),
            "search_upload_retention_days": max(0, int(self.config.search_upload_retention_days or 0)),
            "result_retention_days": max(0, int(self.config.result_retention_days or 0)),
            "match_cache_retention_days": max(0, int(self.config.match_cache_retention_days or 0)),
            "review_retention_days": max(0, int(self.config.review_retention_days or 0)),
            "description": "No automatic delete/archive is executed by default.",
        }

    def _default_log_delete_cutoff(self) -> datetime:
        days = int(self.config.log_delete_before_days or 0)
        if days <= 0:
            raise ValueError("delete_before is required when SIM_LOG_DELETE_BEFORE_DAYS is not set")
        return now_kst() - timedelta(days=days)

    def _recent_match_policy(self, document_count: int) -> dict[str, Any]:
        configured_limit = int(self.config.recent_match_document_limit or 0)
        limit = max(0, configured_limit)
        recent_days = max(1, int(self.config.recent_match_document_recent_days or 365))
        return {
            "document_limit": limit,
            "document_recent_days": recent_days,
            "document_count": int(document_count or 0),
            "sampling_enabled": bool(limit and int(document_count or 0) > limit),
        }

    def list_document_chunks(self, document_id: str, *, limit: int, offset: str | None = None) -> tuple[list[ChunkItem], str | None]:
        info = self.catalog.get_document(document_id)
        if info and _is_text_hidden(info.metadata):
            return [], None
        records, next_offset = self.store.scroll(
            DOCUMENT_COLLECTION,
            limit=limit,
            offset=offset,
            metadata_filter={"document_id": document_id},
        )
        return [self._to_chunk(record, target_type="document") for record in records], next_offset

    def list_logs(
        self,
        *,
        limit: int,
        offset: str | None = None,
        source_type: str | None = None,
        svc: str | None = None,
        user_id: str | None = None,
        order: str = "desc",
    ) -> tuple[list[LogListItem], str | None]:
        items, next_offset = self.catalog.list_logs(
            limit=limit,
            offset=int(offset or 0),
            source_type=source_type,
            svc=svc,
            user_id=user_id,
            order=order,
        )
        return items, str(next_offset) if next_offset is not None else None

    def delete_logs_by_retention(
        self,
        *,
        svc: str | list[str],
        delete_before: datetime | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        svc_values = _normalize_svc_values(svc)
        if not svc_values:
            raise ValueError("svc is required")
        cutoff = as_kst(delete_before) if delete_before is not None else self._default_log_delete_cutoff()
        cutoff_text = kst_naive_iso(cutoff)
        matched_logs, matched_chunks = self.catalog.count_logs_for_retention_delete(
            svc_values=svc_values,
            delete_before=cutoff_text,
        )
        log_ids = self.catalog.log_ids_for_retention_delete(
            svc_values=svc_values,
            delete_before=cutoff_text,
        )
        msgids = _msgids_from_log_ids(log_ids)
        result = {
            "dry_run": bool(dry_run),
            "svc": svc_values,
            "delete_before": cutoff,
            "matched_logs": matched_logs,
            "matched_chunks": matched_chunks,
            "sample_log_ids": log_ids[:10],
            "matched_msgids": len(msgids),
            "catalog_deleted": 0,
            "vector_deleted": 0,
            "linked_similarity_results": {"enabled": bool(self.config.log_retention_delete_results), "matched": 0, "deleted": 0},
            "linked_reviews": {"enabled": bool(self.config.log_retention_delete_reviews), "matched": 0, "deleted": 0},
            "linked_match_cache": {"enabled": bool(self.config.log_retention_clear_match_cache), "matched": 0, "deleted": 0},
        }
        if self.config.log_retention_delete_results:
            result["linked_similarity_results"] = {
                "enabled": True,
                **self.catalog.delete_similarity_results_by_msgids(msgids, dry_run=dry_run),
            }
        if self.config.log_retention_delete_reviews:
            result["linked_reviews"] = {
                "enabled": True,
                **self.catalog.delete_reviews_by_log_ids(log_ids, dry_run=dry_run),
            }
        if self.config.log_retention_clear_match_cache:
            result["linked_match_cache"] = {
                "enabled": True,
                **self.catalog.clear_match_cache(dry_run=dry_run),
            }
        if dry_run:
            return result
        if matched_logs <= 0:
            logger.info("logs retention delete skipped because no catalog rows matched svc=%s delete_before=%s", svc_values, cutoff_text)
            return result

        vector_filter: dict[str, Any] = {
            "svc": svc_values[0] if len(svc_values) == 1 else {"$in": svc_values},
            "ctime": {"$lt": cutoff_text},
        }
        if any(value.lower() in {"*", "all", "__all__"} for value in svc_values):
            vector_filter = {"ctime": {"$lt": cutoff_text}}
        result["vector_deleted"] = self.store.delete_by_metadata(LOG_COLLECTION, vector_filter)
        result["catalog_deleted"] = self.catalog.delete_logs_for_retention(
            svc_values=svc_values,
            delete_before=cutoff_text,
        )
        return result

    def cleanup_operations(self, *, dry_run: bool = True) -> dict[str, Any]:
        started = time.perf_counter()
        now = now_kst()
        result: dict[str, Any] = {
            "dry_run": bool(dry_run),
            "started_at": now.isoformat(),
            "log_retention": None,
            "similarity_results": None,
            "match_cache": None,
            "reviews": None,
            "uploads": None,
            "elapsed_ms": 0.0,
        }

        policies = _parse_log_retention_policy(self.config.log_retention_policy)
        if policies:
            policy_results: list[dict[str, Any]] = []
            for svc_values, days in policies:
                try:
                    policy_results.append(
                        self.delete_logs_by_retention(
                            svc=svc_values,
                            delete_before=now - timedelta(days=days),
                            dry_run=dry_run,
                        )
                    )
                except Exception as exc:
                    policy_results.append({"svc": svc_values, "days": days, "error": str(exc)})
            result["log_retention"] = {"mode": "policy", "items": policy_results}
        else:
            svc_values = _normalize_svc_values(self.config.log_retention_svc)
            if svc_values and int(self.config.log_delete_before_days or 0) > 0:
                try:
                    result["log_retention"] = self.delete_logs_by_retention(
                        svc=svc_values,
                        delete_before=None,
                        dry_run=dry_run,
                    )
                except Exception as exc:
                    result["log_retention"] = {"error": str(exc)}

        result["similarity_results"] = self._cleanup_collection_by_days(
            "similarity_results",
            days=int(self.config.result_retention_days or 0),
            dry_run=dry_run,
            cleanup=lambda cutoff: self.catalog.cleanup_similarity_results(older_than=cutoff, dry_run=dry_run),
        )
        result["match_cache"] = self._cleanup_collection_by_days(
            "match_cache",
            days=int(self.config.match_cache_retention_days or 0),
            dry_run=dry_run,
            cleanup=lambda cutoff: self.catalog.cleanup_match_cache(older_than=cutoff, dry_run=dry_run),
        )
        result["reviews"] = self._cleanup_collection_by_days(
            "reviews",
            days=int(self.config.review_retention_days or 0),
            dry_run=dry_run,
            cleanup=lambda cutoff: self.catalog.cleanup_reviews(older_than=cutoff, dry_run=dry_run),
        )
        result["uploads"] = self._cleanup_upload_files(dry_run=dry_run, now=now)
        result["elapsed_ms"] = round(_elapsed_ms(started), 1)
        logger.info("cleanup operations completed dry_run=%s result=%s", dry_run, result)
        return result

    def _cleanup_collection_by_days(self, name: str, *, days: int, dry_run: bool, cleanup) -> dict[str, Any]:
        if days <= 0:
            return {"enabled": False, "days": int(days or 0), "matched": 0, "deleted": 0}
        cutoff = now_kst() - timedelta(days=days)
        data = cleanup(cutoff)
        return {"enabled": True, "days": days, "cutoff": cutoff.isoformat(), **data}

    def _cleanup_upload_files(self, *, dry_run: bool, now: datetime) -> dict[str, Any]:
        upload_root = Path(self.config.upload_dir).resolve()
        result: dict[str, Any] = {
            "enabled": True,
            "upload_dir": str(upload_root),
            "search": {"enabled": False, "matched": 0, "deleted": 0, "bytes": 0},
            "deleted_documents": {"enabled": False, "matched": 0, "deleted": 0, "bytes": 0},
        }
        search_days = int(self.config.search_upload_retention_days or 0)
        if search_days > 0:
            cutoff_ts = (now - timedelta(days=search_days)).timestamp()
            result["search"] = self._cleanup_file_tree(upload_root / "search", cutoff_ts=cutoff_ts, dry_run=dry_run)
            result["search"]["enabled"] = True
            result["search"]["days"] = search_days

        deleted_days = int(self.config.upload_deleted_retention_days or 0)
        if deleted_days > 0:
            cutoff = now - timedelta(days=deleted_days)
            paths = self.catalog.deleted_document_upload_paths(deleted_before=cutoff)
            result["deleted_documents"] = self._cleanup_known_files(paths, root=upload_root, dry_run=dry_run)
            result["deleted_documents"]["enabled"] = True
            result["deleted_documents"]["days"] = deleted_days
            result["deleted_documents"]["cutoff"] = cutoff.isoformat()
        return result

    def _cleanup_file_tree(self, root: Path, *, cutoff_ts: float, dry_run: bool) -> dict[str, Any]:
        matched = deleted = total_bytes = 0
        if not root.exists():
            return {"enabled": True, "matched": 0, "deleted": 0, "bytes": 0}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime >= cutoff_ts:
                continue
            matched += 1
            total_bytes += int(stat.st_size)
            if not dry_run:
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    logger.warning("cleanup failed to delete file path=%s", path, exc_info=True)
        return {"matched": matched, "deleted": deleted, "bytes": total_bytes}

    def _cleanup_known_files(self, paths: list[str], *, root: Path, dry_run: bool) -> dict[str, Any]:
        matched = deleted = total_bytes = 0
        root = root.resolve()
        seen: set[Path] = set()
        for value in paths:
            path = Path(value)
            if not path.is_absolute():
                path = root / path
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
            except Exception:
                logger.warning("cleanup skipped upload path outside root path=%s root=%s", value, root)
                continue
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            try:
                size = int(resolved.stat().st_size)
            except OSError:
                size = 0
            matched += 1
            total_bytes += size
            if not dry_run:
                try:
                    resolved.unlink()
                    deleted += 1
                except OSError:
                    logger.warning("cleanup failed to delete upload file path=%s", resolved, exc_info=True)
        return {"matched": matched, "deleted": deleted, "bytes": total_bytes}

    def list_log_chunks(self, log_id: str, *, limit: int, offset: str | None = None) -> tuple[list[ChunkItem], str | None]:
        records, next_offset = self.store.scroll(
            LOG_COLLECTION,
            limit=limit,
            offset=offset,
            metadata_filter={"log_id": log_id},
        )
        return [self._to_chunk(record, target_type="log") for record in records], next_offset

    def list_recent_similarity_matches(
        self,
        *,
        limit: int,
        offset: int = 0,
        min_score: float = 0.82,
        risk_level: str | None = "high",
    ) -> tuple[list[dict[str, Any]], int | None]:
        rows, next_offset = self.catalog.list_recent_similarity_matches(
            limit=limit,
            offset=offset,
            min_score=min_score,
            risk_level=risk_level,
        )
        return [self._hydrate_stored_match(row) for row in rows], next_offset

    def _hydrate_stored_match(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(row.get("metadata") or {})
        document_id = str(row.get("target_id") or metadata.get("document_id") or "").strip()
        document_chunk_id = str(row.get("chunk_id") or metadata.get("chunk_id") or "").strip()
        log_id = str(metadata.get("_match_log_id") or "").strip()
        log_chunk_id = str(metadata.get("_match_log_chunk_id") or "").strip()
        text_preview = str(row.get("text_preview") or metadata.get("_match_document_text_preview") or "")
        log_text_preview = str(metadata.get("_match_log_text_preview") or "")
        if not text_preview and document_id:
            text_preview = self._chunk_text_preview(
                DOCUMENT_COLLECTION,
                metadata_filter={"document_id": document_id, **({"chunk_id": document_chunk_id} if document_chunk_id else {})},
            )
        if not log_text_preview and log_id:
            log_text_preview = self._chunk_text_preview(
                LOG_COLLECTION,
                metadata_filter={"log_id": log_id, **({"chunk_id": log_chunk_id} if log_chunk_id else {})},
            )
        if text_preview:
            row["text_preview"] = text_preview
            metadata["_match_document_text_preview"] = text_preview
        if log_text_preview:
            metadata["_match_log_text_preview"] = log_text_preview
        row["metadata"] = metadata
        return row

    def _chunk_text_preview(self, collection: str, *, metadata_filter: dict[str, Any], limit: int = 1000) -> str:
        try:
            records, _ = self.store.scroll(collection, limit=1, metadata_filter=metadata_filter)
        except Exception:
            return ""
        if not records:
            return ""
        return str(records[0].text or "")[: max(1, int(limit))]

    def search_documents(
        self,
        *,
        text: str,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any],
    ) -> list[SimilarityHit]:
        text = normalize_text_for_embedding(text)
        vector = self.embedder.embed([text])[0]
        hits = self.store.search(
            DOCUMENT_COLLECTION,
            vector,
            top_k=top_k,
            min_score=min_score,
            metadata_filter=metadata_filter,
        )
        return [self._to_hit(hit, target_type="document") for hit in hits]

    def search_logs_by_text(
        self,
        *,
        text: str,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any],
    ) -> list[SimilarityHit]:
        text = normalize_text_for_embedding(text)
        chunks = chunk_text(
            text,
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            min_chunk_chars=self.config.min_chunk_chars,
            max_chunks=32,
        )
        vectors = self.embedder.embed([chunk.text for chunk in chunks]) if chunks else []
        best_by_record: dict[str, SimilarityHit] = {}
        for vector in vectors:
            for hit in self.store.search(
                LOG_COLLECTION,
                vector,
                top_k=top_k,
                min_score=min_score,
                metadata_filter=metadata_filter,
            ):
                converted = self._to_hit(hit, target_type="log")
                dedup_key = f"{converted.target_id}:{converted.chunk_id}"
                old = best_by_record.get(dedup_key)
                if old is None or converted.score > old.score:
                    best_by_record[dedup_key] = converted
        values = sorted(best_by_record.values(), key=lambda x: x.score, reverse=True)
        return values[:top_k]

    def search_logs_by_document(
        self,
        *,
        document_id: str,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any],
    ) -> list[SimilarityHit]:
        metadata_filter = dict(metadata_filter or {})
        partition_names = self._log_search_partitions(metadata_filter)
        cache_key = self._search_logs_cache_key(
            document_id=document_id,
            top_k=top_k,
            min_score=min_score,
            metadata_filter=metadata_filter,
            partition_names=partition_names,
        )
        if self.config.search_logs_cache_enabled:
            cached = self.catalog.get_match_cache(cache_key, max_age_sec=self.config.search_logs_cache_ttl_sec)
            if cached:
                return [SimilarityHit(**item) for item in (cached.get("hits") or [])]

        with self._lock:
            text = self._document_texts.get(document_id)
        max_doc_chunks = max(1, min(int(self.config.search_logs_max_document_chunks or 8), self.config.max_document_chunks))
        vectors: list[list[float]] = []
        if not text:
            records, _ = self.store.scroll(
                DOCUMENT_COLLECTION,
                limit=max_doc_chunks,
                metadata_filter={"document_id": document_id},
                include_vectors=True,
            )
            vectors = [record.vector for record in records if record.vector]
            if not vectors:
                text = "\n".join(record.text for record in records if record.text)
        if text:
            text = normalize_text_for_embedding(text)
            chunks = chunk_text(
                text,
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                min_chunk_chars=self.config.min_chunk_chars,
                max_chunks=max_doc_chunks,
            )
            vectors = self.embedder.embed([c.text for c in chunks]) if chunks else []
        if not vectors:
            return []
        best_by_record: dict[str, SimilarityHit] = {}
        hits = self._search_log_vectors(
            vectors,
            top_k=top_k,
            min_score=min_score,
            metadata_filter=metadata_filter,
            partition_names=partition_names,
        )
        for hit in hits:
            converted = self._to_hit(hit, target_type="log")
            dedup_key = f"{converted.target_id}:{converted.chunk_id}"
            old = best_by_record.get(dedup_key)
            if old is None or converted.score > old.score:
                best_by_record[dedup_key] = converted
        values = sorted(best_by_record.values(), key=lambda x: x.score, reverse=True)
        values = values[:top_k]
        if self.config.search_logs_cache_enabled:
            self.catalog.save_match_cache(
                cache_key,
                params={
                    "type": "search_logs_by_document",
                    "document_id": document_id,
                    "top_k": top_k,
                    "min_score": min_score,
                    "metadata_filter": metadata_filter,
                    "partition_names": partition_names,
                    "max_document_chunks": max_doc_chunks,
                },
                hits=[_model_json_dict(item) for item in values],
            )
        return values

    def _search_log_vectors(
        self,
        vectors: list[list[float]],
        *,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any],
        partition_names: list[str] | None,
    ):
        if not vectors:
            return []
        try:
            return self.store.batch_search(
                LOG_COLLECTION,
                vectors,
                top_k=top_k,
                min_score=min_score,
                metadata_filter=metadata_filter,
                partition_names=partition_names,
            )
        except Exception:
            # Older vector backends may not support multi-vector search efficiently.
            parallelism = max(1, min(int(self.config.search_logs_parallelism or 1), len(vectors)))
            if parallelism <= 1:
                hits = []
                for vector in vectors:
                    hits.extend(
                        self.store.search(
                            LOG_COLLECTION,
                            vector,
                            top_k=top_k,
                            min_score=min_score,
                            metadata_filter=metadata_filter,
                            partition_names=partition_names,
                        )
                    )
                return hits
            hits = []
            with ThreadPoolExecutor(max_workers=parallelism) as pool:
                futures = [
                    pool.submit(
                        self.store.search,
                        LOG_COLLECTION,
                        vector,
                        top_k=top_k,
                        min_score=min_score,
                        metadata_filter=metadata_filter,
                        partition_names=partition_names,
                    )
                    for vector in vectors
                ]
                for future in as_completed(futures):
                    hits.extend(future.result())
            return hits

    def _log_search_partitions(self, metadata_filter: dict[str, Any]) -> list[str] | None:
        ctime = metadata_filter.get("ctime")
        start, end = _datetime_range_from_filter(ctime)
        if start is None and end is None and int(self.config.search_logs_default_days or 0) > 0:
            end = now_kst().replace(second=0, microsecond=0)
            start = end - timedelta(days=int(self.config.search_logs_default_days))
            metadata_filter["ctime"] = {"$gte": start.isoformat(), "$lte": end.isoformat()}
        if start is None and end is None:
            return None
        if start is None:
            start = end
        if end is None:
            end = now_kst()
        return month_partition_names_between(
            start,
            end,
            include_default=self.config.search_logs_include_default_partition,
        )

    def _search_logs_cache_key(
        self,
        *,
        document_id: str,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any],
        partition_names: list[str] | None,
    ) -> str:
        payload = {
            "type": "search_logs_by_document:v2",
            "document_id": document_id,
            "top_k": int(top_k),
            "min_score": float(min_score),
            "metadata_filter": metadata_filter,
            "partition_names": partition_names or [],
            "max_document_chunks": int(self.config.search_logs_max_document_chunks or 0),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def recent_document_matches(
        self,
        *,
        log_limit: int,
        top_k: int,
        min_score: float,
        since: datetime | None = None,
    ) -> list[SimilarityHit]:
        best_by_pair: dict[str, SimilarityHit] = {}
        candidate_k = max(top_k * 5, min(log_limit, 200), 20)
        log_filter: dict[str, Any] = {}
        if since is not None:
            log_filter["ctime"] = {"$gte": since.isoformat()}
        partition_names = (
            month_partition_names_between(
                since,
                now_kst(),
                include_default=self.config.recent_match_include_default_partition,
            )
            if since is not None
            else None
        )
        for doc in self._recent_match_documents():
            doc_records, _ = self.store.scroll(
                DOCUMENT_COLLECTION,
                limit=max(1, min(int(doc.chunk_count or 1), self.config.max_document_chunks)),
                metadata_filter={"document_id": doc.document_id},
                include_vectors=True,
            )
            for doc_record in doc_records:
                if not doc_record.vector:
                    continue
                doc_meta = dict(doc_record.metadata or {})
                doc_id = str(doc_meta.get("document_id") or doc.document_id)
                doc_chunk_id = str(doc_meta.get("chunk_id") or doc_record.id)
                for hit in self.store.search(
                    LOG_COLLECTION,
                    doc_record.vector,
                    top_k=candidate_k,
                    min_score=min_score,
                    metadata_filter=log_filter,
                    partition_names=partition_names,
                ):
                    log_meta = dict(hit.record.metadata or {})
                    svc = str(log_meta.get("svc") or "").strip().upper()
                    if svc.endswith("R"):
                        continue
                    log_id = str(log_meta.get("log_id") or hit.record.id)
                    meta = dict(doc_meta)
                    meta["_match_log_id"] = log_id
                    meta["_match_log_chunk_id"] = str(log_meta.get("chunk_id") or hit.record.id)
                    meta["_match_log_text_preview"] = hit.record.text[:1000]
                    meta["_match_log_metadata"] = log_meta
                    converted = SimilarityHit(
                        score=float(hit.score),
                        target_type="document",
                        target_id=doc_id,
                        chunk_id=doc_chunk_id,
                        text_preview=doc_record.text[:1000] if not _is_text_hidden(doc_meta) else "",
                        metadata=meta,
                    )
                    key = f"{log_id}:{doc_id}"
                    old = best_by_pair.get(key)
                    if old is None or converted.score > old.score:
                        best_by_pair[key] = converted
        values = sorted(best_by_pair.values(), key=lambda x: x.score, reverse=True)
        return values[:top_k]

    def _recent_match_documents(self) -> list[DocumentInfo]:
        docs = self.catalog.list_documents()
        limit = max(0, int(self.config.recent_match_document_limit or 0))
        if limit <= 0 or len(docs) <= limit:
            return docs
        recent_cutoff = now_kst() - timedelta(days=max(1, int(self.config.recent_match_document_recent_days or 365)))

        def priority(doc: DocumentInfo) -> tuple[int, float, int, str]:
            metadata = dict(doc.metadata or {})
            security = str(doc.security_level or metadata.get("security_level") or "").strip()
            priority_value = _safe_int(metadata.get("priority") or metadata.get("importance"), 0)
            file_ext = str(metadata.get("file_ext") or metadata.get("ext") or "").strip().lower()
            kind_score = 2 if file_ext in {".pdf", ".doc", ".docx", ".hwp", ".hwpx", ".xls", ".xlsx", ".ppt", ".pptx"} else 1
            security_score = 3 if security == "대외비" else 1
            created_at = _as_utc(doc.created_at)
            recent_score = 1 if created_at >= recent_cutoff else 0
            chunk_score = min(int(doc.chunk_count or 0), 1000)
            created_ts = created_at.timestamp()
            return (
                security_score * 10000 + priority_value * 1000 + recent_score * 100 + kind_score * 10 + chunk_score,
                created_ts,
                int(doc.chunk_count or 0),
                str(doc.document_id),
            )

        return sorted(docs, key=priority, reverse=True)[:limit]

    @staticmethod
    def _to_hit(hit, *, target_type: str) -> SimilarityHit:
        meta = dict(hit.record.metadata)
        target_id = str(meta.get("document_id") if target_type == "document" else meta.get("log_id"))
        text_hidden = target_type == "document" and _is_text_hidden(meta)
        return SimilarityHit(
            score=float(hit.score),
            target_type=target_type,
            target_id=target_id,
            chunk_id=str(meta.get("chunk_id") or hit.record.id),
            text_preview="" if text_hidden else hit.record.text[:500],
            metadata=meta,
        )

    @staticmethod
    def _to_chunk(record: VectorRecord, *, target_type: str) -> ChunkItem:
        meta = dict(record.metadata)
        target_id = str(meta.get("document_id") if target_type == "document" else meta.get("log_id"))
        text_hidden = target_type == "document" and _is_text_hidden(meta)
        return ChunkItem(
            target_type=target_type,
            target_id=target_id,
            chunk_id=str(meta.get("chunk_id") or record.id),
            text="" if text_hidden else record.text,
            metadata=meta,
        )


def _is_text_hidden(metadata: dict[str, Any] | None) -> bool:
    return bool((metadata or {}).get("file_retained") is False)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _as_utc(value: datetime) -> datetime:
    """Compatibility name retained; operational timestamps are normalized to KST."""
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def _datetime_range_from_filter(value: Any) -> tuple[datetime | None, datetime | None]:
    if isinstance(value, dict):
        start: datetime | None = None
        end: datetime | None = None
        for key in ("$gte", "gte", "$gt", "gt"):
            dt = _parse_datetime_value(value.get(key))
            if dt is not None and (start is None or dt < start):
                start = dt
        for key in ("$lte", "lte", "$lt", "lt"):
            dt = _parse_datetime_value(value.get(key))
            if dt is not None and (end is None or dt > end):
                end = dt
        return start, end

    dt = _parse_datetime_value(value)
    return (dt, dt) if dt is not None else (None, None)


def _parse_datetime_value(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return _as_utc(dt)


def _model_json_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "json"):
        return json.loads(value.json())
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)


_TERM_STOPWORDS = {
    "그리고",
    "그러나",
    "또한",
    "대한",
    "관련",
    "내용",
    "사항",
    "입니다",
    "합니다",
    "있는",
    "없는",
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
}


def _tokenize_terms(text: str) -> list[str]:
    values = re.findall(r"[A-Za-z0-9가-힣_.:%/-]{3,}", str(text or ""))
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = value.strip("._:%/-")
        key = term.lower()
        if len(key) < 3 or key in _TERM_STOPWORDS or key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


def _term_weight(value: str) -> float:
    text = str(value or "")
    if re.fullmatch(r"\d{4,}", text) or re.search(r"[0-9][0-9,._:%/-]{2,}", text):
        return 2.0
    if re.search(r"[A-Za-z]", text) and re.search(r"\d", text):
        return 1.8
    if len(text) >= 8:
        return 1.5
    if len(text) >= 5:
        return 1.25
    return 1.0


def _weighted_term_coverage(left_text: str, right_text: str) -> float:
    left = {term.lower() for term in _tokenize_terms(left_text)}
    right_terms = [term.lower() for term in _tokenize_terms(right_text)]
    if not left or not right_terms:
        return 0.0
    seen: set[str] = set()
    total = 0.0
    shared = 0.0
    for term in right_terms:
        if term in seen:
            continue
        seen.add(term)
        weight = _term_weight(term)
        total += weight
        if term in left:
            shared += weight
    return shared / total if total else 0.0


def _phrase_match_score(left_text: str, right_text: str) -> float:
    left_terms = [term.lower() for term in _tokenize_terms(left_text)]
    right_terms = [term.lower() for term in _tokenize_terms(right_text)]
    if len(left_terms) < 2 or len(right_terms) < 2:
        return 0.0
    left_phrases: set[str] = set()
    for size in range(2, 5):
        for index in range(0, len(left_terms) - size + 1):
            left_phrases.add(" ".join(left_terms[index : index + size]))
    total = 0
    matched = 0
    for size in range(2, 5):
        for index in range(0, len(right_terms) - size + 1):
            total += 1
            if " ".join(right_terms[index : index + size]) in left_phrases:
                matched += size
    return min(1.0, matched / max(total, 1)) if total else 0.0


def _matched_terms(left_text: str, right_text: str, *, limit: int = 8) -> list[str]:
    left = {term.lower() for term in _tokenize_terms(left_text)}
    terms: list[str] = []
    seen: set[str] = set()
    for term in _tokenize_terms(right_text):
        key = term.lower()
        if key in left and key not in seen:
            seen.add(key)
            terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _match_evidence(*, document_text: str, log_text: str, raw_score: float) -> dict[str, Any]:
    raw = max(0.0, min(float(raw_score or 0.0), 1.0))
    weighted = _weighted_term_coverage(document_text, log_text)
    phrase = _phrase_match_score(document_text, log_text)
    matched_keywords = _matched_terms(document_text, log_text)
    has_keyword_evidence = bool(str(document_text or "").strip() and str(log_text or "").strip())
    vector_weight = 0.85 if has_keyword_evidence else 1.0
    keyword_weight = 0.10 if has_keyword_evidence else 0.0
    phrase_weight = 0.05 if has_keyword_evidence else 0.0
    final_score = max(0.0, min((raw * vector_weight) + (weighted * keyword_weight) + (phrase * phrase_weight), 1.0))
    rounded_final = round(final_score, 6)
    rounded_raw = round(raw, 6)
    rounded_weighted = round(weighted, 6)
    rounded_phrase = round(phrase, 6)
    return {
        "score": rounded_final,
        "raw_score": rounded_raw,
        "weighted_coverage_score": rounded_weighted,
        "phrase_match_score": rounded_phrase,
        "matched_terms": matched_keywords,
        "matched_keywords": matched_keywords,
        "matched_terms_description": "등록문서 매칭 청크와 EMS 본문/첨부 매칭 청크 양쪽에 공통으로 나타난 대표 핵심어입니다. 유사도 판정 사유 설명용이며 전체 공통 단어 목록은 아닙니다.",
        "score_breakdown": [
            ["최고 청크 벡터 유사도", rounded_raw],
            ["가중 공통어구 커버리지", rounded_weighted],
            ["구문 일치 보강", rounded_phrase],
        ],
        "score_weight_policy": {
            "decision_score_field": "score",
            "decision_score_formula": "score = raw_score * vector_similarity_weight + weighted_coverage_score * keyword_match_weight + phrase_match_score * phrase_match_weight",
            "vector_similarity_weight": vector_weight,
            "keyword_match_weight": keyword_weight,
            "weighted_term_coverage_weight": keyword_weight,
            "phrase_match_weight": phrase_weight,
            "description": "운영 판정은 AI 유사도, 핵심어 일치, 문장흐름만 사용한다. 원문이 없어 근거 항목을 계산할 수 없으면 AI 유사도 100%로 판정한다.",
        },
    }


def _log_msgid(log_id: str, metadata: dict[str, Any]) -> str:
    value = str(metadata.get("msg_id") or "").strip()
    if value:
        return value
    return re.sub(r":(?:body|attach:\d+)$", "", str(log_id or ""), flags=re.IGNORECASE)


def _log_result_key(log_id: str, metadata: dict[str, Any]) -> str:
    source_type = str(metadata.get("source_type") or "").lower()
    attach_index = _log_attach_index(log_id, metadata)
    if source_type == "attachment" or attach_index is not None:
        return f"attach_{int(attach_index or 0)}"
    return "body"


def _log_attach_index(log_id: str, metadata: dict[str, Any]) -> int | None:
    for key in ("attachment_index", "attach_index"):
        if metadata.get(key) is not None:
            try:
                return int(metadata.get(key))
            except Exception:
                pass
    match = re.search(r":attach:(\d+)$", str(log_id or ""), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _normalize_svc_values(value: str | list[str]) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    values: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        values.append(text)
        seen.add(text)
    return values


def _parse_log_retention_policy(value: str) -> list[tuple[list[str], int]]:
    policies: list[tuple[list[str], int]] = []
    for item in re.split(r"[,;\n]+", str(value or "")):
        text = item.strip()
        if not text:
            continue
        if "=" in text:
            raw_svc, raw_days = text.split("=", 1)
        elif ":" in text:
            raw_svc, raw_days = text.split(":", 1)
        else:
            continue
        try:
            days = int(str(raw_days).strip())
        except Exception:
            continue
        if days <= 0:
            continue
        svc_values = _normalize_svc_values(re.split(r"[+|]", raw_svc))
        if svc_values:
            policies.append((svc_values, days))
    return policies


def _msgids_from_log_ids(log_ids: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for log_id in log_ids:
        text = str(log_id or "").strip()
        if not text:
            continue
        msgid = re.sub(r":(?:body|attach:\d+)$", "", text, flags=re.IGNORECASE)
        if msgid and msgid not in seen:
            values.append(msgid)
            seen.add(msgid)
    return values


def _result_risk_level(score: float, *, low: float, high: float) -> str:
    value = float(score or 0.0)
    if value <= 0:
        return "none"
    if value >= high:
        return "high"
    if value >= low:
        return "grey"
    return "low"


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _review_scope(risk_level: str) -> str:
    if risk_level == "high":
        return "high_risk"
    if risk_level == "grey":
        return "grey_zone"
    return "low_risk"


_ENGINE: SimilarityEngine | None = None
_ENGINE_LOCK = RLock()


def get_engine() -> SimilarityEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = SimilarityEngine()
    return _ENGINE

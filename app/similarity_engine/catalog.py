from __future__ import annotations

import re
import logging
from datetime import datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient, UpdateOne

from app.schemas import DocumentInfo, LogListItem, ReviewItem
from app.time_utils import KST, kst_iso, kst_naive_iso, normalize_kst_payload, now_kst
from .kafka_delivery import SimpleKafkaProducer


logger = logging.getLogger(__name__)


class SimilarityCatalog:
    def __init__(
        self,
        *,
        mongo_uri: str,
        database: str,
        log_collection: str,
        document_collection: str,
        review_collection: str,
        match_cache_collection: str,
        similarity_result_collection: str,
        kafka_producer: SimpleKafkaProducer | None = None,
    ):
        self.client = MongoClient(mongo_uri, tz_aware=True, tzinfo=KST)
        self.db = self.client[database]
        self.logs = self.db[log_collection]
        self.documents = self.db[document_collection]
        self.reviews = self.db[review_collection]
        self.match_cache = self.db[match_cache_collection]
        self.similarity_results = self.db[similarity_result_collection]
        self.kafka_producer = kafka_producer
        self._ensure_indexes()
        if self.kafka_producer is None:
            self.similarity_results.update_many(
                {"delivery_status": "pending"},
                {"$set": {"delivery_status": "disabled", "delivery_error": None, "delivery_skip_reason": "kafka_disabled"}},
            )

    def ping(self) -> None:
        self.client.admin.command("ping")

    def upsert_log(self, *, log_id: str, chunk_count: int, sample_text: str, metadata: dict[str, Any]) -> None:
        now = now_kst()
        metadata = dict(metadata or {})
        doc = {
            "log_id": str(log_id),
            "source_type": str(metadata.get("source_type") or ""),
            "svc": str(metadata.get("svc") or ""),
            "user_id": str(metadata.get("user_id") or ""),
            "chunk_count": int(chunk_count),
            "sample_text": str(sample_text or "")[:1000],
            "metadata": metadata,
            "updated_at": now,
        }
        self.logs.update_one(
            {"log_id": str(log_id)},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

    def count_logs(self, *, source_type: str | None = None, svc: str | None = None, user_id: str | None = None) -> int:
        return int(self.logs.count_documents(_log_filter(source_type=source_type, svc=svc, user_id=user_id)))

    def count_logs_created_since(self, since: datetime) -> int:
        return int(self.logs.count_documents({"created_at": {"$gte": since}}))

    def count_log_chunks(self) -> int:
        rows = list(self.logs.aggregate([{"$group": {"_id": None, "total": {"$sum": "$chunk_count"}}}]))
        return int(rows[0]["total"]) if rows else 0

    def count_logs_for_retention_delete(self, *, svc_values: list[str], delete_before: str) -> tuple[int, int]:
        query = _log_retention_delete_filter(svc_values=svc_values, delete_before=delete_before)
        matched_logs = int(self.logs.count_documents(query))
        rows = list(self.logs.aggregate([{"$match": query}, {"$group": {"_id": None, "total": {"$sum": "$chunk_count"}}}]))
        matched_chunks = int(rows[0]["total"]) if rows else 0
        return matched_logs, matched_chunks

    def log_ids_for_retention_delete(self, *, svc_values: list[str], delete_before: str, limit: int = 200000) -> list[str]:
        query = _log_retention_delete_filter(svc_values=svc_values, delete_before=delete_before)
        cursor = self.logs.find(query, {"_id": 0, "log_id": 1}).limit(max(1, int(limit)))
        return [str(row.get("log_id") or "") for row in cursor if row.get("log_id")]

    def delete_logs_for_retention(self, *, svc_values: list[str], delete_before: str) -> int:
        query = _log_retention_delete_filter(svc_values=svc_values, delete_before=delete_before)
        result = self.logs.delete_many(query)
        return int(result.deleted_count)

    @staticmethod
    def _retention_result(collection, query: dict[str, Any], *, dry_run: bool) -> dict[str, int]:
        matched = int(collection.count_documents(query))
        deleted = 0
        if not dry_run and matched:
            deleted = int(collection.delete_many(query).deleted_count)
        return {"matched": matched, "deleted": deleted}

    def cleanup_similarity_results(self, *, older_than: datetime, dry_run: bool) -> dict[str, int]:
        return self._retention_result(self.similarity_results, {"generated_at": {"$lt": older_than}}, dry_run=dry_run)

    def cleanup_match_cache(self, *, older_than: datetime, dry_run: bool) -> dict[str, int]:
        return self._retention_result(self.match_cache, {"generated_at": {"$lt": older_than}}, dry_run=dry_run)

    def cleanup_reviews(self, *, older_than: datetime, dry_run: bool) -> dict[str, int]:
        return self._retention_result(self.reviews, {"reviewed_at": {"$lt": older_than}}, dry_run=dry_run)

    def delete_similarity_results_by_msgids(self, msgids: list[str], *, dry_run: bool) -> dict[str, int]:
        values = _unique_text_values(msgids)
        if not values:
            return {"matched": 0, "deleted": 0}
        return self._retention_result(self.similarity_results, {"msgid": {"$in": values}}, dry_run=dry_run)

    def delete_reviews_by_log_ids(self, log_ids: list[str], *, dry_run: bool) -> dict[str, int]:
        values = _unique_text_values(log_ids)
        if not values:
            return {"matched": 0, "deleted": 0}
        matched = 0
        deleted = 0
        for log_id in values:
            query = {"match_key": {"$regex": r"^[^|]*\|" + re.escape(log_id) + r"\|"}}
            count = int(self.reviews.count_documents(query))
            matched += count
            if not dry_run and count:
                deleted += int(self.reviews.delete_many(query).deleted_count)
        return {"matched": matched, "deleted": deleted}

    def clear_match_cache(self, *, dry_run: bool) -> dict[str, int]:
        return self._retention_result(self.match_cache, {}, dry_run=dry_run)

    def deleted_document_upload_paths(self, *, deleted_before: datetime, limit: int = 5000) -> list[str]:
        cursor = self.documents.find(
            {
                "status": "DELETED",
                "deleted_at": {"$lt": deleted_before},
                "metadata.upload_path": {"$type": "string", "$ne": ""},
            },
            {"_id": 0, "metadata.upload_path": 1},
        ).limit(max(1, int(limit)))
        paths: list[str] = []
        for row in cursor:
            path = str(dict(row.get("metadata") or {}).get("upload_path") or "").strip()
            if path:
                paths.append(path)
        return paths

    def list_logs(
        self,
        *,
        limit: int,
        offset: int = 0,
        source_type: str | None = None,
        svc: str | None = None,
        user_id: str | None = None,
        order: str = "desc",
    ) -> tuple[list[LogListItem], int | None]:
        limit = max(1, int(limit))
        offset = max(0, int(offset))
        query = _log_filter(source_type=source_type, svc=svc, user_id=user_id)
        direction = DESCENDING if str(order or "").lower() != "asc" else ASCENDING
        cursor = self.logs.find(
            query,
            {"_id": 0, "log_id": 1, "chunk_count": 1, "sample_text": 1, "metadata": 1},
        ).sort([("metadata.ctime", direction), ("log_id", direction)]).skip(offset).limit(limit + 1)
        rows = list(cursor)
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            LogListItem(
                log_id=str(row.get("log_id") or ""),
                chunk_count=int(row.get("chunk_count") or 0),
                sample_text=str(row.get("sample_text") or ""),
                metadata=dict(row.get("metadata") or {}),
            )
            for row in rows
        ]
        return items, offset + limit if has_more else None

    def list_recent_logs(self, *, limit: int) -> list[LogListItem]:
        cursor = self.logs.find(
            {},
            {"_id": 0, "log_id": 1, "chunk_count": 1, "sample_text": 1, "metadata": 1},
        ).sort([("metadata.ctime", DESCENDING), ("log_id", DESCENDING)]).limit(max(1, int(limit)))
        return [
            LogListItem(
                log_id=str(row.get("log_id") or ""),
                chunk_count=int(row.get("chunk_count") or 0),
                sample_text=str(row.get("sample_text") or ""),
                metadata=dict(row.get("metadata") or {}),
            )
            for row in cursor
        ]

    def upsert_document(self, info: DocumentInfo) -> None:
        now = now_kst()
        doc = info.model_dump(mode="python")
        created_at = doc.pop("created_at", None) or now
        doc["document_id"] = str(info.document_id)
        doc["updated_at"] = now
        self.documents.update_one(
            {"document_id": str(info.document_id)},
            {"$set": doc, "$setOnInsert": {"created_at": created_at}},
            upsert=True,
        )

    def list_documents(self) -> list[DocumentInfo]:
        rows = self.documents.find(
            {"status": {"$ne": "DELETED"}},
            {"_id": 0},
        ).sort([("created_at", DESCENDING), ("document_id", DESCENDING)])
        return [_document_info(row) for row in rows]

    def search_documents(
        self,
        *,
        query: str | None = None,
        limit: int = 30,
        offset: int = 0,
        security_level: str | None = None,
        department: str | None = None,
        owner: str | None = None,
    ) -> tuple[list[DocumentInfo], int | None]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        mongo_query: dict[str, Any] = {"status": {"$ne": "DELETED"}}
        if security_level:
            mongo_query["security_level"] = str(security_level).strip()
        if department:
            mongo_query["department"] = {"$regex": re.escape(str(department).strip()), "$options": "i"}
        if owner:
            mongo_query["owner"] = {"$regex": re.escape(str(owner).strip()), "$options": "i"}
        q = str(query or "").strip()
        if q:
            pattern = {"$regex": re.escape(q), "$options": "i"}
            mongo_query["$or"] = [
                {"document_id": pattern},
                {"title": pattern},
                {"owner": pattern},
                {"department": pattern},
                {"security_level": pattern},
                {"metadata.file_name": pattern},
                {"metadata.file_ext": pattern},
                {"metadata.file_checksum_sha256": pattern},
                {"metadata.checksum_sha256": pattern},
                {"metadata.description": pattern},
            ]
            if q.isdigit():
                mongo_query["$or"].append({"metadata.file_size": int(q)})
        cursor = self.documents.find(mongo_query, {"_id": 0}).sort([("created_at", DESCENDING), ("document_id", DESCENDING)]).skip(offset).limit(limit + 1)
        rows = list(cursor)
        has_more = len(rows) > limit
        rows = rows[:limit]
        return [_document_info(row) for row in rows], offset + limit if has_more else None

    def mark_document_deleted(self, document_id: str) -> None:
        now = now_kst()
        self.documents.update_one(
            {"document_id": str(document_id)},
            {"$set": {"status": "DELETED", "deleted_at": now, "updated_at": now}},
        )

    def get_document(self, document_id: str) -> DocumentInfo | None:
        row = self.documents.find_one(
            {"document_id": str(document_id), "status": {"$ne": "DELETED"}},
            {"_id": 0},
        )
        return _document_info(row) if row else None

    def update_document_info(
        self,
        document_id: str,
        *,
        title: str | None = None,
        owner: str | None = None,
        department: str | None = None,
        security_level: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentInfo | None:
        current = self.documents.find_one(
            {"document_id": str(document_id), "status": {"$ne": "DELETED"}},
            {"_id": 0},
        )
        if not current:
            return None
        update: dict[str, Any] = {"updated_at": now_kst()}
        if title is not None:
            update["title"] = str(title)
        if owner is not None:
            update["owner"] = str(owner).strip() or None
        if department is not None:
            update["department"] = str(department).strip() or None
        if security_level is not None:
            update["security_level"] = str(security_level).strip() or None
        if metadata is not None:
            merged_metadata = dict(current.get("metadata") or {})
            merged_metadata.update(dict(metadata or {}))
            update["metadata"] = merged_metadata
        self.documents.update_one({"document_id": str(document_id)}, {"$set": update})
        current.update(update)
        return _document_info(current)

    def count_documents(self) -> int:
        return int(self.documents.count_documents({"status": {"$ne": "DELETED"}}))

    def count_documents_created_since(self, since: datetime) -> int:
        return int(self.documents.count_documents({"status": {"$ne": "DELETED"}, "created_at": {"$gte": since}}))

    def count_document_chunks(self) -> int:
        rows = list(
            self.documents.aggregate(
                [
                    {"$match": {"status": {"$ne": "DELETED"}}},
                    {"$group": {"_id": None, "total": {"$sum": "$chunk_count"}}},
                ]
            )
        )
        return int(rows[0]["total"]) if rows else 0

    def bulk_upsert_logs(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = now_kst()
        ops = []
        for row in rows:
            metadata = dict(row.get("metadata") or {})
            log_id = str(row.get("log_id") or "")
            if not log_id:
                continue
            doc = {
                "log_id": log_id,
                "source_type": str(metadata.get("source_type") or row.get("source_type") or ""),
                "svc": str(metadata.get("svc") or row.get("svc") or ""),
                "user_id": str(metadata.get("user_id") or row.get("user_id") or ""),
                "chunk_count": int(row.get("chunk_count") or 0),
                "sample_text": str(row.get("sample_text") or "")[:1000],
                "metadata": metadata,
                "updated_at": now,
            }
            ops.append(UpdateOne({"log_id": log_id}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True))
        if not ops:
            return 0
        result = self.logs.bulk_write(ops, ordered=False)
        return int(result.upserted_count + result.modified_count + result.matched_count)

    def list_reviews(self, *, match_key: str | None = None, limit: int = 500) -> list[ReviewItem]:
        query: dict[str, Any] = {}
        if match_key:
            query["match_key"] = str(match_key)
        cursor = self.reviews.find(query, {"_id": 0}).sort([("reviewed_at", DESCENDING)]).limit(max(1, min(int(limit or 500), 2000)))
        return [ReviewItem(**row) for row in cursor]

    def upsert_review(self, item: dict[str, Any]) -> ReviewItem:
        now = now_kst()
        doc = dict(item)
        doc["match_key"] = str(doc.get("match_key") or "")
        doc["updated_at"] = now
        self.reviews.update_one(
            {"match_key": doc["match_key"]},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        stored = self.reviews.find_one({"match_key": doc["match_key"]}, {"_id": 0}) or doc
        return ReviewItem(**stored)

    def import_reviews(self, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        now = now_kst()
        ops = []
        for item in items:
            match_key = str(item.get("match_key") or "").strip()
            if not match_key:
                continue
            doc = dict(item)
            doc["match_key"] = match_key
            doc["updated_at"] = now
            ops.append(UpdateOne({"match_key": match_key}, {"$set": doc, "$setOnInsert": {"created_at": now}}, upsert=True))
        if not ops:
            return 0
        result = self.reviews.bulk_write(ops, ordered=False)
        return int(result.upserted_count + result.modified_count + result.matched_count)

    def get_match_cache(self, key: str, *, max_age_sec: int) -> dict[str, Any] | None:
        row = self.match_cache.find_one({"cache_key": str(key)}, {"_id": 0})
        if not row:
            return None
        generated_at = row.get("generated_at")
        if not isinstance(generated_at, datetime):
            return None
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=KST)
        age = (now_kst() - generated_at).total_seconds()
        if age > max(0, int(max_age_sec)):
            return None
        return row

    def save_match_cache(self, key: str, *, params: dict[str, Any], hits: list[dict[str, Any]]) -> None:
        now = now_kst()
        self.match_cache.update_one(
            {"cache_key": str(key)},
            {
                "$set": {
                    "cache_key": str(key),
                    "params": dict(params or {}),
                    "hits": list(hits or []),
                    "hit_count": len(hits or []),
                    "generated_at": now,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    def upsert_similarity_result_parts(
        self,
        *,
        parts: list[dict[str, Any]],
        thresholds: dict[str, float],
        version: str = "similarity-result-v1",
    ) -> int:
        if not parts:
            return 0
        now = now_kst()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for part in parts:
            msgid = str(part.get("msgid") or "").strip()
            result_key = str(part.get("result_key") or "").strip()
            result = dict(part.get("result") or {})
            if not msgid or not result_key or not result:
                continue
            grouped.setdefault(msgid, []).append({"key": result_key, "result": result})
        changed = 0
        for msgid, items in grouped.items():
            existing = self.similarity_results.find_one({"msgid": msgid}, {"_id": 0}) or {}
            results_by_key = dict(existing.get("results_by_key") or {})
            for item in items:
                results_by_key[item["key"]] = item["result"]
            results = [results_by_key[key] for key in sorted(results_by_key, key=_result_sort_key)]
            similarity = _build_similarity_payload(
                results=results,
                thresholds=thresholds,
                generated_at=now,
                version=version,
            )
            doc = {
                "type": "similarity",
                "msgid": msgid,
                "data": {"similarity": similarity},
                "results_by_key": results_by_key,
                "summary": similarity["summary"],
                "detected": bool(similarity["summary"]["detected"]),
                "max_score": float(similarity["summary"]["max_score"]),
                "match_count": int(similarity["summary"]["match_count"]),
                "risk_level": similarity["summary"]["risk_level"],
                "delivery_status": (existing.get("delivery_status") or "pending") if self.kafka_producer is not None else "disabled",
                "generated_at": now,
                "updated_at": now,
            }
            self.similarity_results.update_one(
                {"msgid": msgid},
                {"$set": doc, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            self._deliver_similarity_result(msgid=msgid, doc=doc)
            changed += 1
        return changed

    def _deliver_similarity_result(self, *, msgid: str, doc: dict[str, Any]) -> None:
        if self.kafka_producer is None:
            self.similarity_results.update_one(
                {"msgid": msgid},
                {"$set": {"delivery_status": "disabled", "delivery_error": None, "delivery_skip_reason": "kafka_disabled"}},
            )
            return
        if not bool(doc.get("detected")):
            skipped_at = now_kst()
            self.similarity_results.update_one(
                {"msgid": msgid},
                {
                    "$set": {
                        "delivery_status": "skipped",
                        "delivery_error": None,
                        "delivery_skip_reason": "below_similarity_threshold",
                        "delivery_updated_at": skipped_at,
                        "updated_at": skipped_at,
                    }
                },
            )
            return
        delivered_at = now_kst()
        try:
            delivery = self.kafka_producer.send_json(_build_kafka_delivery_payload(doc), key=msgid)
        except Exception as exc:
            self.similarity_results.update_one(
                {"msgid": msgid},
                {
                    "$set": {
                        "delivery_status": "failed",
                        "delivery_error": str(exc)[:1000],
                        "delivery_updated_at": delivered_at,
                        "updated_at": delivered_at,
                    }
                },
            )
            logger.warning("similarity result kafka delivery failed msgid=%s error=%s", msgid, exc)
            return
        self.similarity_results.update_one(
            {"msgid": msgid},
            {
                "$set": {
                    "delivery_status": "sent",
                    "delivery_error": None,
                    "delivery": delivery,
                    "delivery_updated_at": delivered_at,
                    "updated_at": delivered_at,
                }
            },
        )

    def get_similarity_result(self, msgid: str) -> dict[str, Any] | None:
        row = self.similarity_results.find_one({"msgid": str(msgid)}, {"_id": 0, "results_by_key": 0})
        return normalize_kst_payload(dict(row)) if row else None

    def mark_middleware_delivery(
        self,
        *,
        msgid: str,
        status: str,
        url: str | None = None,
        error: str | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        now = now_kst()
        update: dict[str, Any] = {
            "middleware_delivery_status": str(status),
            "middleware_delivery_url": str(url or ""),
            "middleware_delivery_error": str(error or "")[:1000] if error else None,
            "middleware_delivery_response": dict(response or {}),
            "middleware_delivery_updated_at": now,
            "updated_at": now,
        }
        self.similarity_results.update_one({"msgid": str(msgid)}, {"$set": update})

    def list_similarity_results(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        detected: bool | None = None,
        delivery_status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        query: dict[str, Any] = {}
        if detected is not None:
            query["detected"] = bool(detected)
        if delivery_status:
            query["delivery_status"] = str(delivery_status)
        limit = max(1, min(int(limit or 50), 500))
        offset = max(0, int(offset or 0))
        rows = list(
            self.similarity_results.find(query, {"_id": 0, "results_by_key": 0})
            .sort([("generated_at", DESCENDING), ("msgid", ASCENDING)])
            .skip(offset)
            .limit(limit + 1)
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        return [normalize_kst_payload(dict(row)) for row in rows], offset + limit if has_more else None

    def list_recent_similarity_matches(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        min_score: float = 0.82,
        risk_level: str | None = "high",
    ) -> tuple[list[dict[str, Any]], int | None]:
        query: dict[str, Any] = {"detected": True, "max_score": {"$gte": float(min_score)}}
        if risk_level:
            query["risk_level"] = str(risk_level)
        scan_limit = max(1, min(int(limit or 50), 500)) + 1
        offset = max(0, int(offset or 0))
        rows = list(
            self.similarity_results.find(query, {"_id": 0, "results_by_key": 0})
            .sort([("generated_at", DESCENDING), ("msgid", ASCENDING)])
            .skip(offset)
            .limit(scan_limit)
        )
        matches: list[dict[str, Any]] = []
        for row in rows:
            similarity = dict((row.get("data") or {}).get("similarity") or {})
            for result in similarity.get("results") or []:
                for match in result.get("matches") or []:
                    if float(match.get("score") or 0.0) < float(min_score):
                        continue
                    matches.append(_stored_match_to_hit(row, result, match))
        matches.sort(key=lambda item: (item.get("generated_at") or "", float(item.get("score") or 0.0)), reverse=True)
        limit = max(1, min(int(limit or 50), 500))
        has_more = len(rows) > limit
        return matches[:limit], offset + limit if has_more else None

    def _ensure_indexes(self) -> None:
        self.logs.create_index([("log_id", ASCENDING)], unique=True, name="ux_log_id")
        self.logs.create_index([("source_type", ASCENDING), ("log_id", ASCENDING)], name="idx_source_type_log_id")
        self.logs.create_index([("svc", ASCENDING), ("log_id", ASCENDING)], name="idx_svc_log_id")
        self.logs.create_index([("user_id", ASCENDING), ("log_id", ASCENDING)], name="idx_user_id_log_id")
        self.logs.create_index([("metadata.ctime", DESCENDING), ("log_id", DESCENDING)], name="idx_metadata_ctime_log_id")
        self.logs.create_index([("updated_at", DESCENDING)], name="idx_updated_at")
        self.logs.create_index([("created_at", DESCENDING)], name="idx_created_at")
        self.documents.create_index([("document_id", ASCENDING)], unique=True, name="ux_document_id")
        self.documents.create_index([("status", ASCENDING), ("title", ASCENDING)], name="idx_status_title")
        self.documents.create_index([("status", ASCENDING), ("created_at", DESCENDING)], name="idx_status_created_at")
        self.documents.create_index([("metadata.file_name", ASCENDING)], name="idx_document_file_name")
        self.documents.create_index([("metadata.file_size", ASCENDING)], name="idx_document_file_size")
        self.documents.create_index([("metadata.file_checksum_sha256", ASCENDING)], name="idx_document_checksum_sha256")
        self.reviews.create_index([("match_key", ASCENDING)], unique=True, name="ux_match_key")
        self.reviews.create_index([("decision", ASCENDING), ("reviewed_at", DESCENDING)], name="idx_decision_reviewed_at")
        self.reviews.create_index([("review_scope", ASCENDING), ("reviewed_at", DESCENDING)], name="idx_scope_reviewed_at")
        self.reviews.create_index([("reviewed_at", DESCENDING)], name="idx_reviewed_at")
        self.match_cache.create_index([("cache_key", ASCENDING)], unique=True, name="ux_cache_key")
        self.match_cache.create_index([("generated_at", DESCENDING)], name="idx_generated_at")
        self.similarity_results.create_index([("msgid", ASCENDING)], unique=True, name="ux_msgid")
        self.similarity_results.create_index([("generated_at", DESCENDING)], name="idx_generated_at")
        self.similarity_results.create_index([("detected", ASCENDING), ("generated_at", DESCENDING)], name="idx_detected_generated_at")
        self.similarity_results.create_index([("delivery_status", ASCENDING), ("updated_at", DESCENDING)], name="idx_delivery_status_updated_at")


def _log_filter(
    *,
    source_type: str | None = None,
    svc: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    source_type = (source_type or "").strip()
    svc = (svc or "").strip()
    user_id = (user_id or "").strip()
    if source_type:
        query["source_type"] = source_type
    if svc:
        query["svc"] = {"$regex": re.escape(svc)}
    if user_id:
        query["user_id"] = {"$regex": re.escape(user_id)}
    return query


def _log_retention_delete_filter(*, svc_values: list[str], delete_before: str) -> dict[str, Any]:
    values = [str(value).strip() for value in svc_values if str(value).strip()]
    if not values:
        raise ValueError("svc is required")
    cutoff = kst_naive_iso(delete_before)
    if any(value.lower() in {"*", "all", "__all__"} for value in values):
        return {"metadata.ctime": {"$lt": cutoff}}
    svc_filter: Any = values[0] if len(values) == 1 else {"$in": values}
    return {
        "svc": svc_filter,
        "metadata.ctime": {"$lt": cutoff},
    }


def _unique_text_values(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _document_info(row: dict[str, Any]) -> DocumentInfo:
    now = now_kst()
    return DocumentInfo(
        document_id=str(row.get("document_id") or ""),
        title=str(row.get("title") or row.get("document_id") or ""),
        owner=row.get("owner"),
        department=row.get("department"),
        security_level=row.get("security_level"),
        status=row.get("status") or "INDEXED",
        chunk_count=int(row.get("chunk_count") or 0),
        created_at=row.get("created_at") or now,
        deleted_at=row.get("deleted_at"),
        metadata=dict(row.get("metadata") or {}),
    )


def _result_sort_key(key: str) -> tuple[int, int, str]:
    value = str(key or "")
    if value == "body":
        return (0, -1, value)
    match = re.match(r"attach_(\d+)$", value)
    if match:
        return (1, int(match.group(1)), value)
    return (2, 0, value)


def _build_kafka_delivery_payload(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(doc.get("type") or "similarity"),
        "msgid": str(doc.get("msgid") or ""),
        "data": dict(doc.get("data") or {}),
    }


def _build_similarity_payload(
    *,
    results: list[dict[str, Any]],
    thresholds: dict[str, float],
    generated_at: datetime,
    version: str,
) -> dict[str, Any]:
    match_count = sum(len(item.get("matches") or []) for item in results)
    max_match = _max_similarity_match(results)
    max_score = float(max_match.get("score") or 0.0) if max_match else max([float(item.get("max_score") or 0.0) for item in results] or [0.0])
    high = float(thresholds.get("grey_zone_high_score") or thresholds.get("min_score") or 0.82)
    low = float(thresholds.get("grey_zone_low_score") or 0.62)
    risk_level = _risk_level(max_score, low=low, high=high)
    return {
        "success": True,
        "status": 200,
        "message": "OK",
        "version": version,
        "generated_at": generated_at.isoformat(),
        "thresholds": {
            "min_score": float(thresholds.get("min_score") or 0.0),
            "grey_zone_low_score": low,
            "grey_zone_high_score": high,
        },
        "summary": {
            "detected": match_count > 0,
            "max_score": round(max_score, 6),
            "max_document_id": str(max_match.get("document_id") or "") if max_match else None,
            "max_document_title": str(max_match.get("document_title") or max_match.get("document_id") or "") if max_match else None,
            "risk_level": risk_level,
            "match_count": int(match_count),
        },
        "results": results,
    }


def _max_similarity_match(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = -1.0
    for item in results:
        for match in item.get("matches") or []:
            if not isinstance(match, dict):
                continue
            try:
                score = float(match.get("score") or 0.0)
            except Exception:
                score = 0.0
            if best is None or score > best_score:
                best = match
                best_score = score
    return best


def _risk_level(score: float, *, low: float, high: float) -> str:
    value = float(score or 0.0)
    if value <= 0:
        return "none"
    if value >= high:
        return "high"
    if value >= low:
        return "grey"
    return "low"


def _stored_match_to_hit(row: dict[str, Any], result: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    msgid = str(row.get("msgid") or "")
    target = str(result.get("target") or "body")
    attach_index = result.get("attach_index")
    log_id = f"{msgid}:body" if target == "body" else f"{msgid}:attach:{int(attach_index or 0)}"
    log_chunk_id = str(match.get("log_chunk_id") or "")
    generated_at = kst_iso(row.get("generated_at"))
    metadata = {
        "document_id": match.get("document_id"),
        "title": match.get("document_title"),
        "security_level": match.get("document_security_level"),
        "_match_log_id": log_id,
        "_match_log_chunk_id": log_chunk_id,
        "_match_log_text_preview": "",
        "_match_log_metadata": {
            "msg_id": msgid,
            "source_type": "attachment" if target == "attach" else "body",
            "attachment_index": attach_index,
            "attach_index": attach_index,
            "ctime": generated_at,
        },
        "_match_document_text_preview": match.get("_match_document_text_preview") or "",
        "_match_log_text_preview": match.get("_match_log_text_preview") or "",
        "stored_result": True,
        "delivery_status": row.get("delivery_status"),
        "risk_level": row.get("risk_level"),
        "matched_terms": match.get("matched_terms") or [],
        "matched_keywords": match.get("matched_keywords") or match.get("matched_terms") or [],
        "matched_terms_description": match.get("matched_terms_description") or "등록문서 매칭 청크와 EMS 본문/첨부 매칭 청크 양쪽에 공통으로 나타난 대표 핵심어입니다. 유사도 판정 사유 설명용이며 전체 공통 단어 목록은 아닙니다.",
        "score_breakdown": match.get("score_breakdown") or [],
        "score_weight_policy": match.get("score_weight_policy") or {},
        "raw_score": match.get("raw_score"),
        "weighted_coverage_score": match.get("weighted_coverage_score"),
        "phrase_match_score": match.get("phrase_match_score"),
    }
    return {
        "score": float(match.get("score") or 0.0),
        "target_type": "document",
        "target_id": str(match.get("document_id") or ""),
        "chunk_id": str(match.get("document_chunk_id") or ""),
        "text_preview": str(match.get("_match_document_text_preview") or ""),
        "metadata": metadata,
        "generated_at": generated_at,
    }


def _utc_iso(value: Any) -> str:
    """Compatibility alias; externally exposed timestamps are KST."""
    return kst_iso(value)

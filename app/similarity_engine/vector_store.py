from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any
from app.time_utils import KST, as_kst


@dataclass
class VectorRecord:
    id: str
    collection: str
    vector: list[float]
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorHit:
    record: VectorRecord
    score: float


class VectorStore(ABC):
    def ping(self) -> None:
        return None

    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        collection: str,
        vector: list[float],
        *,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any] | None = None,
        partition_names: list[str] | None = None,
    ) -> list[VectorHit]:
        raise NotImplementedError

    def batch_search(
        self,
        collection: str,
        vectors: list[list[float]],
        *,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any] | None = None,
        partition_names: list[str] | None = None,
    ) -> list[VectorHit]:
        hits: list[VectorHit] = []
        for vector in vectors:
            hits.extend(
                self.search(
                    collection,
                    vector,
                    top_k=top_k,
                    min_score=min_score,
                    metadata_filter=metadata_filter,
                    partition_names=partition_names,
                )
            )
        return hits

    @abstractmethod
    def delete_by_metadata(self, collection: str, metadata: dict[str, Any]) -> int:
        raise NotImplementedError

    def count(self, collection: str) -> int:
        return 0

    def collection_id(self, collection: str) -> int | None:
        return None

    def scroll(
        self,
        collection: str,
        *,
        limit: int,
        offset: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
        include_vectors: bool = False,
        partition_names: list[str] | None = None,
    ) -> tuple[list[VectorRecord], str | None]:
        return [], None


class MilvusVectorStore(VectorStore):
    def __init__(self, base_url: str, dim: int):
        self.base_url = str(base_url).rstrip("/")
        self.dim = int(dim)
        self._collections: set[str] = set()
        self._lock = RLock()

    def ping(self) -> None:
        self._request("POST", "/v2/vectordb/collections/has", {"collectionName": "document_chunks"})

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        by_collection: dict[str, list[VectorRecord]] = {}
        for record in records:
            partition = _record_partition_name(record)
            key = f"{record.collection}\0{partition or ''}"
            by_collection.setdefault(key, []).append(record)
        for key, items in by_collection.items():
            collection, partition = key.split("\0", 1)
            partition = partition or None
            self._ensure_collection(collection)
            if partition:
                self._ensure_partition(collection, partition)
            self._request(
                "POST",
                "/v2/vectordb/entities/upsert",
                {
                    "collectionName": collection,
                    **({"partitionName": partition} if partition else {}),
                    "data": [
                        {
                            "id": record.id,
                            "vector": record.vector,
                            "text": _limit_varchar(record.text),
                            "metadata": record.metadata,
                        }
                        for record in items
                    ],
                },
            )

    def search(
        self,
        collection: str,
        vector: list[float],
        *,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any] | None = None,
        partition_names: list[str] | None = None,
    ) -> list[VectorHit]:
        return self.batch_search(
            collection,
            [vector],
            top_k=top_k,
            min_score=min_score,
            metadata_filter=metadata_filter,
            partition_names=partition_names,
        )[: max(1, int(top_k))]

    def batch_search(
        self,
        collection: str,
        vectors: list[list[float]],
        *,
        top_k: int,
        min_score: float,
        metadata_filter: dict[str, Any] | None = None,
        partition_names: list[str] | None = None,
    ) -> list[VectorHit]:
        if not self._collection_exists(collection):
            return []
        query_vectors = [vector for vector in vectors if vector]
        if not query_vectors:
            return []
        body: dict[str, Any] = {
            "collectionName": collection,
            "data": query_vectors,
            "annsField": "vector",
            "limit": max(1, int(top_k)),
            "outputFields": ["id", "text", "metadata"],
        }
        selected_partitions = self._valid_partitions(collection, partition_names)
        if selected_partitions:
            body["partitionNames"] = selected_partitions
        filt = _milvus_filter(metadata_filter)
        if filt:
            body["filter"] = filt
        data = self._request("POST", "/v2/vectordb/entities/search", body)
        hits: list[VectorHit] = []
        for item in _milvus_data_items(data):
            score = float(item.get("distance") or item.get("score") or 0.0)
            if score < min_score:
                continue
            entity = item.get("entity") or item
            metadata = _milvus_metadata(entity.get("metadata"))
            record = VectorRecord(
                id=str(entity.get("id") or item.get("id") or ""),
                collection=collection,
                vector=[],
                text=str(entity.get("text") or ""),
                metadata=metadata,
            )
            hits.append(VectorHit(record=record, score=score))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[: max(1, int(top_k)) * len(query_vectors)]

    def delete_by_metadata(self, collection: str, metadata: dict[str, Any]) -> int:
        if not self._collection_exists(collection):
            return 0
        filt = _milvus_filter(metadata)
        if not filt:
            return 0
        self._request(
            "POST",
            "/v2/vectordb/entities/delete",
            {"collectionName": collection, "filter": filt},
        )
        return -1

    def count(self, collection: str) -> int:
        if not self._collection_exists(collection):
            return 0
        try:
            data = self._request("POST", "/v2/vectordb/collections/get_stats", {"collectionName": collection})
        except RuntimeError:
            return 0
        payload = data.get("data") or {}
        stats = payload.get("stats") if isinstance(payload, dict) else None
        if isinstance(stats, dict):
            return int(stats.get("row_count") or stats.get("rowCount") or 0)
        if isinstance(stats, list):
            for item in stats:
                if item.get("key") in {"row_count", "rowCount"}:
                    return int(item.get("value") or 0)
        return int(payload.get("row_count") or payload.get("rowCount") or 0) if isinstance(payload, dict) else 0

    def collection_id(self, collection: str) -> int | None:
        if not self._collection_exists(collection):
            return None
        try:
            data = self._request("POST", "/v2/vectordb/collections/describe", {"collectionName": collection})
        except RuntimeError:
            return None
        payload = data.get("data") or {}
        try:
            return int(payload.get("collectionID") or payload.get("collectionId"))
        except Exception:
            return None

    def scroll(
        self,
        collection: str,
        *,
        limit: int,
        offset: str | None = None,
        metadata_filter: dict[str, Any] | None = None,
        include_vectors: bool = False,
        partition_names: list[str] | None = None,
    ) -> tuple[list[VectorRecord], str | None]:
        if not self._collection_exists(collection):
            return [], None
        page_size = max(1, int(limit))
        start = max(0, int(offset or 0))
        output_fields = ["id", "text", "metadata"]
        if include_vectors:
            output_fields.append("vector")
        body: dict[str, Any] = {
            "collectionName": collection,
            "filter": _milvus_filter(metadata_filter) or "",
            "outputFields": output_fields,
            "limit": page_size,
            "offset": start,
        }
        selected_partitions = self._valid_partitions(collection, partition_names)
        if selected_partitions:
            body["partitionNames"] = selected_partitions
        data = self._request("POST", "/v2/vectordb/entities/query", body)
        records: list[VectorRecord] = []
        for item in _milvus_data_items(data):
            metadata = _milvus_metadata(item.get("metadata"))
            records.append(
                VectorRecord(
                    id=str(item.get("id") or ""),
                    collection=collection,
                    vector=[float(x) for x in (item.get("vector") or [])],
                    text=str(item.get("text") or ""),
                    metadata=metadata,
                )
            )
        next_offset = str(start + page_size) if len(records) == page_size else None
        return records, next_offset

    def _ensure_collection(self, collection: str) -> None:
        with self._lock:
            if collection in self._collections:
                return
            if not self._collection_exists(collection):
                self._request("POST", "/v2/vectordb/collections/create", _milvus_create_body(collection, self.dim))
                self._request("POST", "/v2/vectordb/collections/load", {"collectionName": collection})
            self._collections.add(collection)

    def _ensure_partition(self, collection: str, partition: str) -> None:
        with self._lock:
            partitions = set(self._list_partitions(collection))
            if partition in partitions:
                return
            self._request(
                "POST",
                "/v2/vectordb/partitions/create",
                {"collectionName": collection, "partitionName": partition},
            )
            try:
                self._request(
                    "POST",
                    "/v2/vectordb/partitions/load",
                    {"collectionName": collection, "partitionNames": [partition]},
                )
            except RuntimeError:
                pass

    def _list_partitions(self, collection: str) -> list[str]:
        if not self._collection_exists(collection):
            return []
        try:
            data = self._request("POST", "/v2/vectordb/partitions/list", {"collectionName": collection})
        except RuntimeError:
            return []
        payload = data.get("data") or []
        return [str(item) for item in payload if item]

    def _valid_partitions(self, collection: str, partition_names: list[str] | None) -> list[str]:
        requested = [str(name) for name in (partition_names or []) if str(name).strip()]
        if not requested:
            return []
        existing = set(self._list_partitions(collection))
        return [name for name in requested if name in existing]

    def _collection_exists(self, collection: str) -> bool:
        data = self._request("POST", "/v2/vectordb/collections/has", {"collectionName": collection})
        value = data.get("data")
        if isinstance(value, dict):
            return bool(value.get("has") or value.get("exists"))
        return bool(value)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Milvus request failed {method} {path}: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Milvus request failed {method} {path}: {exc}") from exc
        data = json.loads(raw.decode("utf-8")) if raw else {}
        code = data.get("code")
        if code not in (None, 0, 200):
            raise RuntimeError(f"Milvus request failed {method} {path}: {data}")
        return data


def _milvus_create_body(collection: str, dim: int) -> dict[str, Any]:
    return {
        "collectionName": collection,
        "schema": {
            "autoID": False,
            "enableDynamicField": False,
            "fields": [
                {
                    "fieldName": "id",
                    "dataType": "VarChar",
                    "isPrimary": True,
                    "elementTypeParams": {"max_length": "512"},
                },
                {
                    "fieldName": "vector",
                    "dataType": "FloatVector",
                    "elementTypeParams": {"dim": str(dim)},
                },
                {
                    "fieldName": "text",
                    "dataType": "VarChar",
                    "elementTypeParams": {"max_length": "65535"},
                },
                {"fieldName": "metadata", "dataType": "JSON"},
            ],
        },
        "indexParams": [
            {
                "fieldName": "vector",
                "indexName": "vector_index",
                "indexType": "AUTOINDEX",
                "metricType": "COSINE",
            }
        ],
    }


def _milvus_filter(metadata_filter: dict[str, Any] | None) -> str:
    if not metadata_filter:
        return ""
    parts = []
    for key, value in metadata_filter.items():
        encoded_key = json.dumps(str(key), ensure_ascii=False)
        left = f"metadata[{encoded_key}]"
        if isinstance(value, dict):
            for op, operand in value.items():
                if op in {"$gte", "gte"}:
                    parts.append(f"{left} >= {_milvus_filter_literal(key, operand)}")
                elif op in {"$gt", "gt"}:
                    parts.append(f"{left} > {_milvus_filter_literal(key, operand)}")
                elif op in {"$lte", "lte"}:
                    parts.append(f"{left} <= {_milvus_filter_literal(key, operand)}")
                elif op in {"$lt", "lt"}:
                    parts.append(f"{left} < {_milvus_filter_literal(key, operand)}")
                elif op in {"$ne", "ne"}:
                    parts.append(f"{left} != {_milvus_filter_literal(key, operand)}")
                elif op in {"$in", "in"} and isinstance(operand, list):
                    values = ", ".join(_milvus_filter_literal(key, item) for item in operand)
                    parts.append(f"{left} in [{values}]")
        else:
            parts.append(f"{left} == {_milvus_filter_literal(key, value)}")
    return " and ".join(parts)


def _milvus_filter_literal(key: str, value: Any) -> str:
    if str(key) == "ctime":
        value = _kst_filter_datetime(value)
    return _milvus_literal(value)


def _kst_filter_datetime(value: Any) -> Any:
    dt = _parse_datetime(value)
    if dt is None or dt.tzinfo is None:
        return value
    return dt.astimezone(KST).replace(tzinfo=None).isoformat()


def _milvus_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _record_partition_name(record: VectorRecord) -> str | None:
    metadata = dict(record.metadata or {})
    if str(metadata.get("target_type") or "").lower() != "log":
        return None
    return _month_partition_name(metadata.get("ctime"))


def _month_partition_name(value: Any) -> str | None:
    dt = _parse_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = as_kst(dt)
    return f"m_{dt.year:04d}{dt.month:02d}"


def month_partition_names_between(start: datetime, end: datetime, *, include_default: bool = True) -> list[str]:
    if start.tzinfo is not None:
        start = as_kst(start).replace(tzinfo=None)
    if end.tzinfo is not None:
        end = as_kst(end).replace(tzinfo=None)
    if start > end:
        start, end = end, start
    names = ["_default"] if include_default else []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        names.append(f"m_{year:04d}{month:02d}")
        month += 1
        if month > 12:
            year += 1
            month = 1
    return names


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _milvus_data_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data") or []
    if isinstance(payload, dict):
        payload = payload.get("data") or payload.get("results") or []
    if payload and isinstance(payload[0], list):
        return [item for group in payload for item in group if isinstance(item, dict)]
    return [item for item in payload if isinstance(item, dict)]


def _milvus_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _limit_varchar(text: str, max_bytes: int = 65000) -> str:
    raw = str(text or "").encode("utf-8", errors="ignore")
    if len(raw) <= max_bytes:
        return str(text or "")
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def build_vector_store(
    *,
    milvus_url: str = "http://milvus:19530",
    dim: int = 384,
) -> VectorStore:
    return MilvusVectorStore(milvus_url, dim)

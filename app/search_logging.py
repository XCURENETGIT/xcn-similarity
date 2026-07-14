from __future__ import annotations

from typing import Any, Iterable


def search_hit_log_items(hits: Iterable[Any], *, limit: int = 5) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for hit in hits:
        metadata = dict(getattr(hit, "metadata", {}) or {})
        items.append(
            {
                "target_id": str(getattr(hit, "target_id", "") or ""),
                "chunk_id": str(getattr(hit, "chunk_id", "") or ""),
                "score": round(float(getattr(hit, "score", 0.0) or 0.0), 6),
                "msg_id": str(metadata.get("msg_id") or ""),
                "source_type": str(metadata.get("source_type") or ""),
                "svc": str(metadata.get("svc") or ""),
            }
        )
        if len(items) >= max(0, int(limit)):
            break
    return items

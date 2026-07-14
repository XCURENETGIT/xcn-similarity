from __future__ import annotations

import argparse
import json
import os
import sqlite3
from typing import Any

from app.similarity_engine.catalog import SimilarityCatalog
from app.similarity_engine.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite similarity catalog into MongoDB catalog.")
    parser.add_argument("--sqlite-path", default=os.getenv("SIM_LEGACY_SQLITE_PATH", "logs/similarity-catalog.sqlite"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("MIGRATE_BATCH_SIZE", "2000")))
    parser.add_argument("--drop-existing", action="store_true")
    args = parser.parse_args()

    config = load_config()
    catalog = SimilarityCatalog(
        mongo_uri=config.catalog_mongo_uri,
        database=config.catalog_database,
        log_collection=config.log_catalog_collection,
        document_collection=config.document_catalog_collection,
    )
    if args.drop_existing:
        catalog.logs.drop()
        catalog.documents.drop()
        catalog._ensure_indexes()

    if not os.path.exists(args.sqlite_path):
        raise FileNotFoundError(args.sqlite_path)

    conn = sqlite3.connect(args.sqlite_path)
    conn.row_factory = sqlite3.Row
    total = 0
    offset = 0
    while True:
        rows = conn.execute(
            """
            SELECT log_id, source_type, svc, user_id, chunk_count, sample_text, metadata_json
            FROM logs
            ORDER BY log_id
            LIMIT ? OFFSET ?
            """,
            (args.batch_size, offset),
        ).fetchall()
        if not rows:
            break
        payload: list[dict[str, Any]] = []
        for row in rows:
            metadata = _decode_metadata(row["metadata_json"])
            payload.append(
                {
                    "log_id": row["log_id"],
                    "source_type": row["source_type"],
                    "svc": row["svc"],
                    "user_id": row["user_id"],
                    "chunk_count": row["chunk_count"],
                    "sample_text": row["sample_text"],
                    "metadata": metadata,
                }
            )
        catalog.bulk_upsert_logs(payload)
        total += len(payload)
        offset += len(rows)
        print(f"[progress] migrated={total}", flush=True)
    print(f"[done] migrated={total}", flush=True)
    return 0


def _decode_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import os
from typing import Any

from pymongo import MongoClient, ReplaceOne


DEFAULT_SOURCE_URI = (
    "mongodb://10.10.20.6:27018/xcn_similarity?replicaSet=shard1rs&readPreference=primary"
    "&serverSelectionTimeoutMS=5000&connectTimeoutMS=10000&directConnection=true"
)
DEFAULT_TARGET_URI = "mongodb://mongodb:27017/xcn_similarity?serverSelectionTimeoutMS=5000&connectTimeoutMS=10000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate xcn-similarity catalog collections to local MongoDB.")
    parser.add_argument("--source-uri", default=os.getenv("SOURCE_MONGO_URI", DEFAULT_SOURCE_URI))
    parser.add_argument("--source-db", default=os.getenv("SOURCE_MONGO_DB", "xcn_similarity"))
    parser.add_argument("--target-uri", default=os.getenv("TARGET_MONGO_URI", os.getenv("SIM_CATALOG_MONGO_URI", DEFAULT_TARGET_URI)))
    parser.add_argument("--target-db", default=os.getenv("TARGET_MONGO_DB", os.getenv("SIM_CATALOG_DATABASE", "xcn_similarity")))
    parser.add_argument("--collections", nargs="*", default=None, help="Collection names. Defaults to every non-system collection.")
    parser.add_argument("--batch-size", type=int, default=1000)
    return parser.parse_args()


def migrate_collection(source_db, target_db, name: str, *, batch_size: int) -> int:
    source = source_db[name]
    target = target_db[name]
    total = 0
    ops: list[ReplaceOne] = []
    for doc in source.find({}):
        key: dict[str, Any]
        if "_id" in doc:
            key = {"_id": doc["_id"]}
        elif doc.get("match_key"):
            key = {"match_key": doc["match_key"]}
        elif doc.get("document_id"):
            key = {"document_id": doc["document_id"]}
        elif doc.get("log_id"):
            key = {"log_id": doc["log_id"]}
        else:
            key = dict(doc)
        ops.append(ReplaceOne(key, doc, upsert=True))
        if len(ops) >= batch_size:
            result = target.bulk_write(ops, ordered=False)
            total += int(result.upserted_count + result.modified_count + result.matched_count)
            ops.clear()
    if ops:
        result = target.bulk_write(ops, ordered=False)
        total += int(result.upserted_count + result.modified_count + result.matched_count)
    return total


def main() -> None:
    args = parse_args()
    source_client = MongoClient(args.source_uri)
    target_client = MongoClient(args.target_uri)
    source_db = source_client[args.source_db]
    target_db = target_client[args.target_db]
    collections = args.collections or [name for name in source_db.list_collection_names() if not name.startswith("system.")]
    print(f"source={args.source_uri} db={args.source_db}")
    print(f"target={args.target_uri} db={args.target_db}")
    for name in collections:
        count = migrate_collection(source_db, target_db, name, batch_size=max(1, int(args.batch_size)))
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()

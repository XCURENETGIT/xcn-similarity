from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import time
import urllib.error
import calendar
from typing import Any
from zoneinfo import ZoneInfo

from pymongo import ASCENDING, DESCENDING, MongoClient

from app.similarity_engine.text_normalizer import normalize_text_for_embedding
from tools.backfill_ems_may import (
    MinioSigV4Client,
    build_metadata,
    post_json,
    read_body_text,
)


KST = ZoneInfo("Asia/Seoul")


DEFAULT_CATALOG_URI = (
    "mongodb://mongodb:27017/xcn_similarity?serverSelectionTimeoutMS=5000&connectTimeoutMS=10000"
)
DEFAULT_EMS_URI = "mongodb://mongodb:27017/venus?serverSelectionTimeoutMS=5000&connectTimeoutMS=10000"


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuously index EMS MongoDB body/attachments into xcn-similarity.")
    parser.add_argument("--mongo-uri", default=os.getenv("EMS_MONGO_URI", DEFAULT_EMS_URI))
    parser.add_argument("--catalog-mongo-uri", default=os.getenv("SIM_CATALOG_MONGO_URI", DEFAULT_CATALOG_URI))
    parser.add_argument("--catalog-db", default=os.getenv("SIM_CATALOG_DATABASE", "xcn_similarity"))
    parser.add_argument("--state-collection", default=os.getenv("SIM_INDEXER_STATE_COLLECTION", "SIM_INDEXER_STATE"))
    parser.add_argument("--failed-collection", default=os.getenv("SIM_INDEXER_FAILED_COLLECTION", "SIM_INDEXER_FAILED"))
    parser.add_argument("--job", default=os.getenv("SIM_INDEXER_JOB", "ems"))
    parser.add_argument(
        "--direct-enabled",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("EMS_INDEX_DIRECT_ENABLED", "true").lower() != "false",
        help="Enable direct EMS MongoDB/MinIO scanning. Disable when middleware drives ingest by svc/_id.",
    )
    parser.add_argument("--months", default=os.getenv("EMS_INDEX_MONTHS", "auto"))
    parser.add_argument("--months-lookback", type=int, default=int(os.getenv("EMS_INDEX_MONTHS_LOOKBACK", "1")))
    parser.add_argument(
        "--timezone",
        default=os.getenv("EMS_INDEX_TIMEZONE", "Asia/Seoul"),
        help="Timezone used to resolve automatic EMS monthly collections and daily reconciliation windows.",
    )
    parser.add_argument(
        "--cursor-field",
        default=os.getenv("EMS_INDEX_CURSOR_FIELD", "ltime"),
        choices=["ltime", "ctime", "_id"],
        help="Source field used for incremental indexing. Non-unique time fields use _id as a tie breaker.",
    )
    parser.add_argument(
        "--ensure-source-indexes",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("EMS_INDEX_ENSURE_SOURCE_INDEXES", "true").lower() != "false",
        help="Ensure required EMS_MESSAGE_yyyymm source MongoDB indexes before indexing each month.",
    )
    parser.add_argument(
        "--seed-missing-recent",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("EMS_INDEX_SEED_MISSING_RECENT", "true").lower() != "false",
        help="In auto_recent mode, start past months from their latest existing cursor when no state exists.",
    )
    parser.add_argument("--seed-state-file", default=os.getenv("EMS_INDEX_SEED_STATE_FILE", ""))
    parser.add_argument("--api-url", default=os.getenv("SIM_API_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--minio-endpoint", default=os.getenv("MINIO_ENDPOINT", "http://minio:9000"))
    parser.add_argument("--minio-access-key", default=os.getenv("MINIO_ACCESS_KEY", "minioadmin"))
    parser.add_argument("--minio-secret-key", default=os.getenv("MINIO_SECRET_KEY", "minioadmin"))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("EMS_INDEX_BATCH_SIZE", "500")))
    parser.add_argument("--post-batch-size", type=int, default=int(os.getenv("EMS_INDEX_POST_BATCH_SIZE", "50")))
    parser.add_argument("--post-retries", type=int, default=int(os.getenv("EMS_INDEX_POST_RETRIES", "5")))
    parser.add_argument("--post-retry-delay-sec", type=float, default=float(os.getenv("EMS_INDEX_POST_RETRY_DELAY_SEC", "5")))
    parser.add_argument("--interval-sec", type=float, default=float(os.getenv("EMS_INDEX_INTERVAL_SEC", "60")))
    parser.add_argument("--loop", action=argparse.BooleanOptionalAction, default=os.getenv("EMS_INDEX_LOOP", "true").lower() != "false")
    parser.add_argument("--body", action="store_true", default=os.getenv("EMS_INDEX_BODY", "true").lower() != "false")
    parser.add_argument("--attach", action="store_true", default=os.getenv("EMS_INDEX_ATTACH", "true").lower() != "false")
    parser.add_argument("--max-text-chars", type=int, default=int(os.getenv("EMS_INDEX_MAX_TEXT_CHARS", "2000000")))
    parser.add_argument("--exclude-svc", default=os.getenv("EMS_INDEX_EXCLUDE_SVC", "FGIS"))
    parser.add_argument("--exclude-svc-prefix", default=os.getenv("EMS_INDEX_EXCLUDE_SVC_PREFIX", "FGI"))
    parser.add_argument("--progress-every", type=int, default=int(os.getenv("EMS_INDEX_PROGRESS_EVERY", "100")))
    parser.add_argument(
        "--recent-sweep-hours",
        type=int,
        default=int(os.getenv("EMS_INDEX_RECENT_SWEEP_HOURS", "0")),
        help="Rescan recent source messages and index only missing body/attachment log ids. Set 0 to disable.",
    )
    parser.add_argument(
        "--recent-sweep-limit",
        type=int,
        default=int(os.getenv("EMS_INDEX_RECENT_SWEEP_LIMIT", "1000")),
        help="Maximum source messages to inspect per month during the recent missing sweep.",
    )
    parser.add_argument(
        "--log-catalog-collection",
        default=os.getenv("SIM_LOG_CATALOG_COLLECTION", os.getenv("SIM_LOG_COLLECTION", "SIM_LOG_CATALOG")),
    )
    parser.add_argument(
        "--reconcile-days",
        type=int,
        default=int(os.getenv("EMS_INDEX_RECONCILE_DAYS", "2")),
        help="Reconcile source cursor dates for today and previous N-1 days. Set 0 to disable.",
    )
    parser.add_argument(
        "--reconcile-limit",
        type=int,
        default=int(os.getenv("EMS_INDEX_RECONCILE_LIMIT", "5000")),
        help="Maximum source messages to inspect per month during cursor-date reconciliation.",
    )
    parser.add_argument(
        "--failed-retry-limit",
        type=int,
        default=int(os.getenv("EMS_INDEX_FAILED_RETRY_LIMIT", "200")),
        help="Maximum previously failed body/attachment items to retry per month per cycle. Set 0 to disable.",
    )
    args = parser.parse_args()
    args._pending_logs = []

    if not args.direct_enabled:
        print("[disabled] direct EMS source indexing is disabled; waiting for middleware-driven ingest", flush=True)
        while args.loop:
            time.sleep(max(1.0, args.interval_sec))
        return 0

    ems_client = MongoClient(args.mongo_uri)
    ems_db = ems_client["venus"]
    catalog_client = MongoClient(args.catalog_mongo_uri)
    catalog_db = catalog_client[args.catalog_db]
    states = catalog_db[args.state_collection]
    failed = catalog_db[args.failed_collection]
    log_catalog = catalog_db[args.log_catalog_collection]
    ensure_indexes(states, failed)
    minio = MinioSigV4Client(args.minio_endpoint, args.minio_access_key, args.minio_secret_key)

    while True:
        cycle_started = time.time()
        totals = {"messages": 0, "body_ok": 0, "body_fail": 0, "attach_ok": 0, "attach_fail": 0, "skipped_empty": 0}
        now = indexer_now(args.timezone)
        months = resolve_months(args.months, lookback=args.months_lookback, now=now)
        current_month = now.strftime("%Y%m")
        dynamic_recent = is_dynamic_recent_mode(args.months)
        print(f"[cycle-start] months={','.join(months)} interval_sec={args.interval_sec} batch_size={args.batch_size}", flush=True)
        for month in months:
            if args.ensure_source_indexes:
                ensure_source_indexes(ems_db, month, args.cursor_field)
            seed_state_if_needed(states, args.job, month, args.seed_state_file)
            if dynamic_recent and args.seed_missing_recent and month != current_month:
                seed_missing_recent_state(states, args.job, month, ems_db, args)
            retry_stats = retry_failed_items(args, ems_db, failed, minio, month)
            flush_log_batch(args)
            if any(retry_stats.values()):
                print(f"[failed-retry] month={month} stats={retry_stats}", flush=True)
            stats = index_month(args, ems_db, states, failed, minio, month)
            flush_log_batch(args)
            sweep_stats = sweep_recent_missing(args, ems_db, failed, minio, log_catalog, month)
            flush_log_batch(args)
            if any(sweep_stats.values()):
                print(f"[recent-sweep] month={month} stats={sweep_stats}", flush=True)
            reconcile_stats = reconcile_missing_by_date_prefix(args, ems_db, failed, minio, log_catalog, month)
            flush_log_batch(args)
            if any(reconcile_stats.values()):
                print(f"[reconcile] month={month} stats={reconcile_stats}", flush=True)
            for key, value in stats.items():
                totals[key] = totals.get(key, 0) + value
            for key, value in retry_stats.items():
                totals[key] = totals.get(key, 0) + value
            for key, value in sweep_stats.items():
                totals[key] = totals.get(key, 0) + value
            for key, value in reconcile_stats.items():
                totals[key] = totals.get(key, 0) + value
        write_cycle_state(states, args.job, months, totals, time.time() - cycle_started)
        print(f"[cycle] months={','.join(months)} stats={totals} elapsed_sec={time.time() - cycle_started:.1f}", flush=True)
        if not args.loop:
            break
        time.sleep(max(1.0, args.interval_sec))
    return 0


def index_month(args, ems_db, states, failed, minio: MinioSigV4Client, month: str) -> dict[str, int]:
    messages = ems_db[f"EMS_MESSAGE_{month}"]
    state = hydrate_cursor_state(read_state(states, args.job, month), messages, args.cursor_field)
    query = apply_cursor_filter(build_query(args), state, args.cursor_field)
    projection = {
        "_id": 1,
        "fileName": 1,
        "svc": 1,
        "ctime": 1,
        "ltime": 1,
        "body": 1,
        "attach": 1,
        "user": 1,
        "sender": 1,
        "network": 1,
        "http": 1,
        "direction": 1,
        "directionSvc": 1,
    }
    stats = {"messages": 0, "body_ok": 0, "body_fail": 0, "attach_ok": 0, "attach_fail": 0, "skipped_empty": 0}
    docs = list(messages.find(query, projection=projection).sort(cursor_sort(args.cursor_field)).limit(max(1, args.batch_size)))
    for msg in docs:
        process_message(args, ems_db, failed, minio, month, msg, stats)
        state = cursor_state_from_message(msg, args.cursor_field)
        if stats["messages"] % max(1, args.progress_every) == 0:
            print(f"[progress] month={month} cursor={format_cursor_state(state, args.cursor_field)} stats={stats}", flush=True)
    if docs:
        flush_log_batch(args)
        write_state(states, args.job, month, state, stats)
        print(f"[indexed] month={month} count={len(docs)} cursor={format_cursor_state(state, args.cursor_field)} stats={stats}", flush=True)
    else:
        print(f"[idle] month={month} cursor={format_cursor_state(state, args.cursor_field)}", flush=True)
    return stats


def retry_failed_items(args, ems_db, failed, minio: MinioSigV4Client, month: str) -> dict[str, int]:
    if int(args.failed_retry_limit or 0) <= 0:
        return empty_stats()

    rows = list(
        failed.find(
            {"job": args.job, "month": month},
            {"_id": 0},
        )
        .sort("updated_at", ASCENDING)
        .limit(max(1, int(args.failed_retry_limit)))
    )
    stats = empty_stats()
    if not rows:
        return stats

    messages = ems_db[f"EMS_MESSAGE_{month}"]
    for row in rows:
        msg_id = str(row.get("msg_id") or "")
        source_type = str(row.get("source_type") or "")
        attach_index = row.get("attach_index")
        if not msg_id or source_type not in {"body", "attachment"}:
            continue
        msg = messages.find_one(
            {"_id": msg_id},
            projection={
                "_id": 1,
                "fileName": 1,
                "svc": 1,
                "ctime": 1,
                "ltime": 1,
                "body": 1,
                "attach": 1,
                "user": 1,
                "sender": 1,
                "network": 1,
                "http": 1,
                "direction": 1,
                "directionSvc": 1,
            },
        )
        if not msg:
            stats["skipped_empty"] += 1
            failed.delete_one(_failed_key(args.job, month, msg_id, source_type, attach_index))
            continue
        if _retry_failed_item(args, ems_db, failed, minio, month, msg, source_type, attach_index, stats):
            failed.delete_one(_failed_key(args.job, month, msg_id, source_type, attach_index))
    return stats


def _retry_failed_item(
    args,
    ems_db,
    failed,
    minio: MinioSigV4Client,
    month: str,
    msg: dict[str, Any],
    source_type: str,
    attach_index: Any,
    stats: dict[str, int],
) -> bool:
    stats["messages"] += 1
    msg_id = str(msg["_id"])
    if source_type == "body":
        try:
            text = normalize_text_for_embedding(read_body_text(ems_db, month, msg))
            if not text:
                stats["skipped_empty"] += 1
                return True
            post_log(args, f"{msg_id}:body", text, msg, build_metadata(msg, "body"))
            stats["body_ok"] += 1
            return True
        except Exception as exc:
            stats["body_fail"] += 1
            record_failure(failed, args.job, month, msg_id, "body", None, exc)
            return False

    try:
        idx = int(attach_index)
    except Exception:
        stats["skipped_empty"] += 1
        return True
    attachments = msg.get("attach") or []
    if idx < 0 or idx >= len(attachments):
        stats["skipped_empty"] += 1
        return True
    attach = attachments[idx] or {}
    path = attach.get("textPath") or attach.get("path")
    if not path:
        stats["skipped_empty"] += 1
        return True
    try:
        text = normalize_text_for_embedding(minio.get_text_by_path(path))
        if not text:
            stats["skipped_empty"] += 1
            return True
        post_log(
            args,
            f"{msg_id}:attach:{idx}",
            text,
            msg,
            build_metadata(
                msg,
                "attachment",
                {
                    "attachment_index": idx,
                    "attach_index": idx,
                    "attach_id": attach.get("id"),
                    "attach_name": attach.get("name"),
                    "attachment_name": attach.get("name"),
                    "file_name": attach.get("name"),
                    "attach_ext": attach.get("ext"),
                    "attach_size": attach.get("size"),
                    "attach_path": attach.get("path"),
                    "attach_textPath": attach.get("textPath"),
                },
            ),
        )
        stats["attach_ok"] += 1
        return True
    except Exception as exc:
        stats["attach_fail"] += 1
        record_failure(failed, args.job, month, msg_id, "attachment", idx, exc)
        return False


def sweep_recent_missing(args, ems_db, failed, minio: MinioSigV4Client, log_catalog, month: str) -> dict[str, int]:
    if int(args.recent_sweep_hours or 0) <= 0:
        return {"messages": 0, "body_ok": 0, "body_fail": 0, "attach_ok": 0, "attach_fail": 0, "skipped_empty": 0}

    messages = ems_db[f"EMS_MESSAGE_{month}"]
    cutoff = indexer_now(args.timezone) - dt.timedelta(hours=max(1, int(args.recent_sweep_hours)))
    query = build_query(args)
    time_field = time_cursor_field(args.cursor_field)
    query[time_field] = {"$gte": cutoff}
    projection = {
        "_id": 1,
        "fileName": 1,
        "svc": 1,
        "ctime": 1,
        "ltime": 1,
        "body": 1,
        "attach": 1,
        "user": 1,
        "sender": 1,
        "network": 1,
        "http": 1,
        "direction": 1,
        "directionSvc": 1,
    }
    docs = messages.find(query, projection=projection).sort(time_field, DESCENDING).limit(max(1, int(args.recent_sweep_limit)))
    stats = {"messages": 0, "body_ok": 0, "body_fail": 0, "attach_ok": 0, "attach_fail": 0, "skipped_empty": 0}
    process_missing_docs(args, ems_db, failed, minio, log_catalog, month, list(docs), stats)
    return stats


def reconcile_missing_by_date_prefix(args, ems_db, failed, minio: MinioSigV4Client, log_catalog, month: str) -> dict[str, int]:
    if int(args.reconcile_days or 0) <= 0:
        return empty_stats()

    time_field = time_cursor_field(args.cursor_field)
    ranges = date_ranges_for_month(month, int(args.reconcile_days), field=time_field, now=indexer_now(args.timezone))
    if not ranges:
        return empty_stats()

    messages = ems_db[f"EMS_MESSAGE_{month}"]
    query = combine_query(build_query(args), {"$or": ranges})
    projection = {
        "_id": 1,
        "fileName": 1,
        "svc": 1,
        "ctime": 1,
        "ltime": 1,
        "body": 1,
        "attach": 1,
        "user": 1,
        "sender": 1,
        "network": 1,
        "http": 1,
        "direction": 1,
        "directionSvc": 1,
    }
    docs = list(messages.find(query, projection=projection).sort([(time_field, DESCENDING), ("_id", DESCENDING)]).limit(max(1, int(args.reconcile_limit))))
    stats = empty_stats()
    print(f"[reconcile-scan] month={month} field={time_field} ranges={len(ranges)} inspected={len(docs)}", flush=True)
    process_missing_docs(args, ems_db, failed, minio, log_catalog, month, docs, stats)
    return stats


def process_missing_docs(
    args,
    ems_db,
    failed,
    minio: MinioSigV4Client,
    log_catalog,
    month: str,
    docs: list[dict[str, Any]],
    stats: dict[str, int],
) -> None:
    if not docs:
        return
    expected_ids = expected_log_ids(args, docs)
    existing_ids = set()
    for start in range(0, len(expected_ids), 5000):
        batch = expected_ids[start : start + 5000]
        existing_ids.update(
            str(row.get("log_id") or "")
            for row in log_catalog.find({"log_id": {"$in": batch}}, {"_id": 0, "log_id": 1})
        )
    for msg in docs:
        missing_body, missing_attach_indexes = find_missing_log_parts(args, existing_ids, msg)
        if not missing_body and not missing_attach_indexes:
            continue
        process_missing_message(args, ems_db, failed, minio, month, msg, missing_body, missing_attach_indexes, stats)


def expected_log_ids(args, docs: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for msg in docs:
        msg_id = str(msg["_id"])
        if args.body and int((msg.get("body") or {}).get("size") or 0) > 0:
            ids.append(f"{msg_id}:body")
        if args.attach:
            for idx, attach in enumerate(msg.get("attach") or []):
                if attach.get("textPath") or attach.get("path"):
                    ids.append(f"{msg_id}:attach:{idx}")
    return ids


def date_ranges_for_month(month: str, days: int, *, field: str, now: dt.datetime | None = None) -> list[dict[str, Any]]:
    now = now or indexer_now()
    ranges: list[dict[str, Any]] = []
    for offset in range(max(1, days)):
        day = now - dt.timedelta(days=offset)
        start = day.strftime("%Y%m%d")
        end = (day + dt.timedelta(days=1)).strftime("%Y%m%d")
        if start.startswith(str(month)):
            if field == "_id":
                ranges.append({"_id": {"$gte": start, "$lt": end}})
            else:
                day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
                ranges.append({field: {"$gte": day_start, "$lt": day_start + dt.timedelta(days=1)}})
    return ranges


def combine_query(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if not left:
        return dict(right)
    if not right:
        return dict(left)
    return {"$and": [left, right]}


def find_missing_log_parts(args, existing_ids: set[str], msg: dict[str, Any]) -> tuple[bool, list[int]]:
    msg_id = str(msg["_id"])
    missing_body = bool(args.body and int((msg.get("body") or {}).get("size") or 0) > 0 and f"{msg_id}:body" not in existing_ids)
    missing_attach_indexes: list[int] = []
    if args.attach:
        for idx, attach in enumerate(msg.get("attach") or []):
            if not (attach.get("textPath") or attach.get("path")):
                continue
            if f"{msg_id}:attach:{idx}" not in existing_ids:
                missing_attach_indexes.append(idx)
    return missing_body, missing_attach_indexes


def empty_stats() -> dict[str, int]:
    return {"messages": 0, "body_ok": 0, "body_fail": 0, "attach_ok": 0, "attach_fail": 0, "skipped_empty": 0}


def process_missing_message(
    args,
    ems_db,
    failed,
    minio: MinioSigV4Client,
    month: str,
    msg: dict[str, Any],
    missing_body: bool,
    missing_attach_indexes: list[int],
    stats: dict[str, int],
) -> None:
    stats["messages"] += 1
    msg_id = str(msg["_id"])
    if missing_body:
        try:
            text = normalize_text_for_embedding(read_body_text(ems_db, month, msg))
            if text:
                post_log(args, f"{msg_id}:body", text, msg, build_metadata(msg, "body"))
                stats["body_ok"] += 1
            else:
                stats["skipped_empty"] += 1
        except Exception as exc:
            stats["body_fail"] += 1
            record_failure(failed, args.job, month, msg_id, "body", None, exc)

    attachments = msg.get("attach") or []
    for idx in missing_attach_indexes:
        if idx >= len(attachments):
            continue
        attach = attachments[idx] or {}
        path = attach.get("textPath") or attach.get("path")
        if not path:
            continue
        try:
            text = normalize_text_for_embedding(minio.get_text_by_path(path))
            if not text:
                stats["skipped_empty"] += 1
                continue
            post_log(
                args,
                f"{msg_id}:attach:{idx}",
                text,
                msg,
                build_metadata(
                    msg,
                    "attachment",
                    {
                        "attachment_index": idx,
                        "attach_index": idx,
                        "attach_id": attach.get("id"),
                        "attach_name": attach.get("name"),
                        "attachment_name": attach.get("name"),
                        "file_name": attach.get("name"),
                        "attach_ext": attach.get("ext"),
                        "attach_size": attach.get("size"),
                        "attach_path": attach.get("path"),
                        "attach_textPath": attach.get("textPath"),
                    },
                ),
            )
            stats["attach_ok"] += 1
        except Exception as exc:
            stats["attach_fail"] += 1
            record_failure(failed, args.job, month, msg_id, "attachment", idx, exc)


def process_message(args, ems_db, failed, minio: MinioSigV4Client, month: str, msg: dict[str, Any], stats: dict[str, int]) -> None:
    stats["messages"] += 1
    msg_id = str(msg["_id"])
    if args.body and int((msg.get("body") or {}).get("size") or 0) > 0:
        try:
            text = normalize_text_for_embedding(read_body_text(ems_db, month, msg))
            if text:
                post_log(args, f"{msg_id}:body", text, msg, build_metadata(msg, "body"))
                stats["body_ok"] += 1
            else:
                stats["skipped_empty"] += 1
        except Exception as exc:
            stats["body_fail"] += 1
            record_failure(failed, args.job, month, msg_id, "body", None, exc)

    if args.attach:
        for idx, attach in enumerate(msg.get("attach") or []):
            path = attach.get("textPath") or attach.get("path")
            if not path:
                continue
            try:
                text = normalize_text_for_embedding(minio.get_text_by_path(path))
                if not text:
                    stats["skipped_empty"] += 1
                    continue
                post_log(
                    args,
                    f"{msg_id}:attach:{idx}",
                    text,
                    msg,
                    build_metadata(
                        msg,
                        "attachment",
                        {
                            "attachment_index": idx,
                            "attach_index": idx,
                            "attach_id": attach.get("id"),
                            "attach_name": attach.get("name"),
                            "attachment_name": attach.get("name"),
                            "file_name": attach.get("name"),
                            "attach_ext": attach.get("ext"),
                            "attach_size": attach.get("size"),
                            "attach_path": attach.get("path"),
                            "attach_textPath": attach.get("textPath"),
                        },
                    ),
                )
                stats["attach_ok"] += 1
            except Exception as exc:
                stats["attach_fail"] += 1
                record_failure(failed, args.job, month, msg_id, "attachment", idx, exc)


def post_log(args, log_id: str, text: str, msg: dict[str, Any], metadata: dict[str, Any]) -> None:
    pending = getattr(args, "_pending_logs", None)
    if pending is None:
        args._pending_logs = []
        pending = args._pending_logs
    pending.append(
        {
            "log_id": log_id,
            "text": text[: args.max_text_chars],
            "svc": msg.get("svc"),
            "user_id": (msg.get("user") or {}).get("userId") or (msg.get("sender") or {}).get("userId"),
            "ctime": msg.get("ctime").isoformat() if hasattr(msg.get("ctime"), "isoformat") else None,
            "metadata": metadata,
        }
    )
    if len(pending) >= max(1, int(args.post_batch_size or 1)):
        flush_log_batch(args)


def flush_log_batch(args) -> None:
    pending = list(getattr(args, "_pending_logs", []) or [])
    if not pending:
        return
    path = "/similarity/logs" if len(pending) == 1 else "/similarity/logs/batch"
    payload = pending[0] if len(pending) == 1 else {"items": pending}
    attempts = max(1, int(args.post_retries or 1))
    for attempt in range(1, attempts + 1):
        try:
            post_json(args.api_url, path, payload)
            break
        except Exception:
            if attempt >= attempts:
                raise
            time.sleep(max(0.1, float(args.post_retry_delay_sec or 1)))
    args._pending_logs = []


def build_query(args) -> dict[str, Any]:
    excluded_svc = [value.strip() for value in str(args.exclude_svc or "").split(",") if value.strip()]
    excluded_prefixes = [value.strip() for value in str(args.exclude_svc_prefix or "").split(",") if value.strip()]
    prefixes = "|".join(re.escape(prefix) for prefix in excluded_prefixes)
    regex = "^(?:[XU]" + (f"|(?:{prefixes})" if prefixes else "") + ")"
    svc_filter: dict[str, Any] = {"$not": {"$regex": regex}}
    if excluded_svc:
        svc_filter["$nin"] = excluded_svc
    return {"svc": svc_filter, "$or": [{"body.size": {"$gt": 0}}, {"attach.0": {"$exists": True}}]}


def resolve_months(value: str, *, lookback: int = 1, now: dt.datetime | None = None) -> list[str]:
    value = str(value or "auto").strip()
    now = now or indexer_now()
    if value.lower() in {"auto", "current"}:
        return [_month_offset(now, 0)]
    if value.lower() in {"auto_recent", "recent", "rolling"}:
        count = max(1, int(lookback or 1))
        return [_month_offset(now, -idx) for idx in range(count)]
    return [item.strip() for item in value.split(",") if item.strip()]


def is_dynamic_recent_mode(value: str) -> bool:
    return str(value or "").strip().lower() in {"auto_recent", "recent", "rolling"}


def _month_offset(base: dt.datetime, offset: int) -> str:
    month_index = base.year * 12 + (base.month - 1) + offset
    year = month_index // 12
    month = month_index % 12 + 1
    # Clamp the day to keep this helper valid for month-end dates.
    day = min(base.day, calendar.monthrange(year, month)[1])
    return base.replace(year=year, month=month, day=day).strftime("%Y%m")


def indexer_now(timezone_name: str | None = None) -> dt.datetime:
    name = str(timezone_name or os.getenv("EMS_INDEX_TIMEZONE", "Asia/Seoul") or "Asia/Seoul").strip()
    try:
        return dt.datetime.now(ZoneInfo(name))
    except Exception:
        return dt.datetime.now()


def time_cursor_field(cursor_field: str) -> str:
    field = str(cursor_field or "ltime").strip()
    return field if field in {"ltime", "ctime"} else "ltime"


def cursor_sort(cursor_field: str, *, descending: bool = False) -> list[tuple[str, int]]:
    direction = DESCENDING if descending else ASCENDING
    field = str(cursor_field or "ltime").strip()
    if field == "_id":
        return [("_id", direction)]
    return [(field, direction), ("_id", direction)]


def cursor_state_from_message(msg: dict[str, Any], cursor_field: str) -> dict[str, Any]:
    if not msg:
        return {}
    field = str(cursor_field or "ltime").strip()
    state: dict[str, Any] = {"cursor_field": field, "last_id": str(msg.get("_id") or "")}
    if field != "_id":
        state[f"last_{field}"] = msg.get(field)
    return state


def hydrate_cursor_state(state: dict[str, Any], messages, cursor_field: str) -> dict[str, Any]:
    if not state:
        return {}
    field = str(cursor_field or "ltime").strip()
    if field == "_id":
        return {"cursor_field": "_id", "last_id": str(state.get("last_id") or "")}
    cursor_key = f"last_{field}"
    if state.get(cursor_key) is not None:
        return {"cursor_field": field, "last_id": str(state.get("last_id") or ""), cursor_key: state.get(cursor_key)}
    last_id = str(state.get("last_id") or "")
    if not last_id:
        return {}
    doc = messages.find_one({"_id": last_id}, projection={"_id": 1, field: 1})
    if doc and doc.get(field) is not None:
        return cursor_state_from_message(doc, field)
    return {"cursor_field": "_id", "last_id": last_id}


def apply_cursor_filter(query: dict[str, Any], state: dict[str, Any], cursor_field: str) -> dict[str, Any]:
    if not state:
        return query
    field = str(cursor_field or "ltime").strip()
    last_id = str(state.get("last_id") or "")
    if field == "_id" or state.get(f"last_{field}") is None:
        if not last_id:
            return query
        return combine_query(query, {"_id": {"$gt": last_id}})
    last_value = state.get(f"last_{field}")
    clause = {
        "$or": [
            {field: {"$gt": last_value}},
            {field: last_value, "_id": {"$gt": last_id}},
        ]
    }
    return combine_query(query, clause)


def format_cursor_state(state: dict[str, Any], cursor_field: str) -> str:
    if not state:
        return "-"
    field = str(cursor_field or state.get("cursor_field") or "ltime").strip()
    last_id = str(state.get("last_id") or "")
    if field == "_id":
        return f"_id={last_id}"
    return f"{field}={state.get(f'last_{field}')} _id={last_id}"


def read_state(states, job: str, month: str) -> dict[str, Any]:
    row = states.find_one(
        {"job": job, "month": month},
        {"_id": 0, "last_id": 1, "last_ltime": 1, "last_ctime": 1, "cursor_field": 1},
    )
    return dict(row or {})


def write_state(states, job: str, month: str, state: dict[str, Any], stats: dict[str, int]) -> None:
    now = dt.datetime.now(KST)
    cursor_field = str(state.get("cursor_field") or "_id")
    last_id = str(state.get("last_id") or "")
    update: dict[str, Any] = {
        "last_id": last_id,
        "cursor_field": cursor_field,
        "stats": dict(stats),
        "updated_at": now,
        "state_type": "month",
    }
    cursor_key = f"last_{cursor_field}" if cursor_field != "_id" else ""
    if cursor_key and state.get(cursor_key) is not None:
        update[cursor_key] = state.get(cursor_key)
    states.update_one(
        {"job": job, "month": month},
        {
            "$set": update,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def write_cycle_state(states, job: str, months: list[str], totals: dict[str, int], elapsed_sec: float) -> None:
    now = dt.datetime.now(KST)
    states.update_one(
        {"job": job, "month": "_cycle"},
        {
            "$set": {
                "state_type": "cycle",
                "months": list(months),
                "stats": dict(totals),
                "elapsed_sec": round(float(elapsed_sec), 3),
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def seed_state_if_needed(states, job: str, month: str, state_file: str) -> None:
    if not state_file or read_state(states, job, month):
        return
    try:
        last_id = open(state_file, "r", encoding="utf-8").read().strip()
    except Exception:
        last_id = ""
    if last_id:
        write_state(states, job, month, {"cursor_field": "_id", "last_id": last_id}, {"messages": 0})
        print(f"[seed] month={month} last_id={last_id} source={state_file}", flush=True)


def seed_missing_recent_state(states, job: str, month: str, ems_db, args) -> None:
    if read_state(states, job, month):
        return
    state = latest_message_state(ems_db, month, args)
    if not state.get("last_id"):
        return
    write_state(states, job, month, state, {"messages": 0, "seeded_latest": 1})
    print(f"[seed-latest] month={month} cursor={format_cursor_state(state, args.cursor_field)} reason=missing_recent_state", flush=True)


def latest_message_state(ems_db, month: str, args) -> dict[str, Any]:
    messages = ems_db[f"EMS_MESSAGE_{month}"]
    projection = {"_id": 1}
    if args.cursor_field != "_id":
        projection[args.cursor_field] = 1
    doc = messages.find_one(build_query(args), projection=projection, sort=cursor_sort(args.cursor_field, descending=True))
    return cursor_state_from_message(doc or {}, args.cursor_field)


def record_failure(failed, job: str, month: str, msg_id: str, source_type: str, attach_index: int | None, exc: Exception) -> None:
    now = dt.datetime.now(KST)
    key = _failed_key(job, month, msg_id, source_type, attach_index)
    failed.update_one(
        key,
        {
            "$set": {"error": str(exc), "error_type": type(exc).__name__, "updated_at": now},
            "$setOnInsert": {**key, "created_at": now},
            "$inc": {"retry_count": 1},
        },
        upsert=True,
    )
    print(f"[warn] {source_type} failed month={month} msg_id={msg_id} attach_index={attach_index} err={exc}", flush=True)


def _failed_key(job: str, month: str, msg_id: str, source_type: str, attach_index: Any) -> dict[str, Any]:
    return {
        "job": job,
        "month": month,
        "msg_id": str(msg_id),
        "source_type": source_type,
        "attach_index": attach_index,
    }


def ensure_indexes(states, failed) -> None:
    states.create_index([("job", ASCENDING), ("month", ASCENDING)], unique=True, name="ux_job_month")
    failed.create_index(
        [("job", ASCENDING), ("month", ASCENDING), ("msg_id", ASCENDING), ("source_type", ASCENDING), ("attach_index", ASCENDING)],
        unique=True,
        name="ux_failed_item",
    )
    failed.create_index([("updated_at", ASCENDING)], name="idx_failed_updated_at")


def ensure_source_indexes(ems_db, month: str, cursor_field: str) -> None:
    field = str(cursor_field or "ltime").strip()
    if field == "_id":
        return
    messages = ems_db[f"EMS_MESSAGE_{month}"]
    index_name = f"{field}_1__id_1"
    existing = {
        str(index.get("name") or "")
        for index in messages.list_indexes()
    }
    if index_name in existing:
        return
    started = time.time()
    messages.create_index([(field, ASCENDING), ("_id", ASCENDING)], name=index_name, background=True)
    print(f"[source-index] month={month} index={index_name} elapsed_sec={time.time() - started:.1f}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

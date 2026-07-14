from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pymongo import MongoClient

from app.similarity_engine.text_normalizer import normalize_text_for_embedding


DEFAULT_MONGO_URI = (
    "mongodb://10.10.20.6:27018/venus"
    "?replicaSet=shard1rs&readPreference=primary&serverSelectionTimeoutMS=5000"
    "&connectTimeoutMS=10000&directConnection=true"
)


def _decode_bytes(data: bytes, charset: str | None = None) -> str:
    names = []
    if charset:
        normalized = str(charset).strip().lower()
        if normalized in {"utf8", "utf-8"}:
            names.append("utf-8")
        elif normalized in {"euckr", "euc-kr"}:
            names.append("euc-kr")
        else:
            names.append(normalized)
    names.extend(["utf-8", "cp949", "euc-kr", "latin-1"])
    for name in names:
        try:
            return data.decode(name)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def read_body_text(db, month: str, msg: dict[str, Any]) -> str:
    files = db[f"EMS_BODY_{month}.files"]
    chunks = db[f"EMS_BODY_{month}.chunks"]
    candidates = []
    if msg.get("fileName"):
        candidates.append(str(msg.get("fileName")))
    candidates.append(f"{msg['_id']}.body")
    meta = None
    for filename in candidates:
        meta = files.find_one({"filename": filename}, projection={"_id": 1, "length": 1, "filename": 1})
        if meta:
            break
    if not meta:
        return ""
    parts = []
    for chunk in chunks.find({"files_id": meta["_id"]}, projection={"_id": 0, "n": 1, "data": 1}).sort("n", 1):
        parts.append(bytes(chunk.get("data") or b""))
    if not parts:
        return ""
    charset = ((msg.get("body") or {}).get("bodyCharset") or "").strip()
    return _decode_bytes(b"".join(parts), charset=charset)


class MinioSigV4Client:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, region: str = "us-east-1"):
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region

    def get_text_by_path(self, path: str) -> str:
        bucket, key = self._bucket_key(path)
        data = self.get_object(bucket, key)
        return _decode_bytes(data)

    def get_object(self, bucket: str, key: str) -> bytes:
        parsed = urllib.parse.urlparse(self.endpoint)
        host = parsed.netloc
        encoded_key = "/".join(urllib.parse.quote(part, safe="") for part in key.split("/"))
        canonical_uri = f"/{bucket}/{encoded_key}"
        url = f"{self.endpoint}{canonical_uri}"
        now = dt.datetime.utcnow()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(b"").hexdigest()
        canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            ["GET", canonical_uri, "", canonical_headers, signed_headers, payload_hash]
        )
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = self._signing_key(date_stamp)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Host": host,
                "x-amz-date": amz_date,
                "x-amz-content-sha256": payload_hash,
                "Authorization": authorization,
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    def _signing_key(self, date_stamp: str) -> bytes:
        key = ("AWS4" + self.secret_key).encode("utf-8")
        k_date = hmac.new(key, date_stamp.encode("utf-8"), hashlib.sha256).digest()
        k_region = hmac.new(k_date, self.region.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
        return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()

    @staticmethod
    def _bucket_key(path: str) -> tuple[str, str]:
        value = str(path or "").strip()
        if not value:
            raise ValueError("empty minio path")
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme and parsed.netloc:
            value = parsed.path
        value = value.lstrip("/")
        parts = value.split("/")
        if parts[0] == "emass":
            return "emass", "/".join(parts[1:])
        if parts[0] == "msg":
            return "emass", value
        return "emass", f"msg/{value}"


def post_json(api_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        api_url.rstrip("/") + path,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def build_metadata(msg: dict[str, Any], source_type: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    user = msg.get("user") or {}
    sender = msg.get("sender") or {}
    network = msg.get("network") or {}
    http = msg.get("http") or {}
    ctime = msg.get("ctime")
    ltime = msg.get("ltime")
    metadata = {
        "source": "ems",
        "source_type": source_type,
        "msg_id": msg.get("_id"),
        "fileName": msg.get("fileName"),
        "file_name": msg.get("fileName"),
        "svc": msg.get("svc"),
        "user_id": user.get("userId") or sender.get("userId"),
        "user_email": user.get("email") or sender.get("email"),
        "user_name": user.get("name") or sender.get("name"),
        "src_ip": network.get("srcIp"),
        "dst_ip": network.get("dstIp"),
        "dst_port": network.get("dstPort"),
        "host": http.get("host"),
        "direction": msg.get("direction"),
        "directionSvc": msg.get("directionSvc"),
        "ctime": ctime.isoformat() if hasattr(ctime, "isoformat") else None,
        "ltime": ltime.isoformat() if hasattr(ltime, "isoformat") else None,
    }
    if extra:
        metadata.update(extra)
    return {k: v for k, v in metadata.items() if v is not None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill EMS_MESSAGE_YYYYMM body and attachment text into xcn-similarity.")
    parser.add_argument("--month", default=os.getenv("EMS_MONTH", "202605"))
    parser.add_argument("--mongo-uri", default=os.getenv("EMS_MONGO_URI", DEFAULT_MONGO_URI))
    parser.add_argument("--api-url", default=os.getenv("SIM_API_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--minio-endpoint", default=os.getenv("MINIO_ENDPOINT", "http://10.10.20.6:19000"))
    parser.add_argument("--minio-access-key", default=os.getenv("MINIO_ACCESS_KEY", "minioadmin"))
    parser.add_argument("--minio-secret-key", default=os.getenv("MINIO_SECRET_KEY", "minioadmin"))
    parser.add_argument("--limit", type=int, default=int(os.getenv("BACKFILL_LIMIT", "0")))
    parser.add_argument("--skip", type=int, default=int(os.getenv("BACKFILL_SKIP", "0")))
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("BACKFILL_BATCH_SIZE", "1000")))
    parser.add_argument("--state-file", default=os.getenv("BACKFILL_STATE_FILE", "logs/backfill_ems_202605.state"))
    parser.add_argument("--after-id", default=os.getenv("BACKFILL_AFTER_ID", ""))
    parser.add_argument("--body", action="store_true", default=os.getenv("BACKFILL_BODY", "true").lower() != "false")
    parser.add_argument("--attach", action="store_true", default=os.getenv("BACKFILL_ATTACH", "true").lower() != "false")
    parser.add_argument("--max-text-chars", type=int, default=int(os.getenv("BACKFILL_MAX_TEXT_CHARS", "2000000")))
    parser.add_argument("--progress-every", type=int, default=int(os.getenv("BACKFILL_PROGRESS_EVERY", "100")))
    parser.add_argument(
        "--exclude-svc",
        default=os.getenv("BACKFILL_EXCLUDE_SVC", "FGIS"),
        help="Comma-separated exact svc values to exclude in addition to X/U prefixes.",
    )
    parser.add_argument(
        "--exclude-svc-prefix",
        default=os.getenv("BACKFILL_EXCLUDE_SVC_PREFIX", "FGI"),
        help="Comma-separated svc prefixes to exclude in addition to exact values.",
    )
    args = parser.parse_args()

    client = MongoClient(args.mongo_uri)
    db = client["venus"]
    messages = db[f"EMS_MESSAGE_{args.month}"]
    minio = MinioSigV4Client(args.minio_endpoint, args.minio_access_key, args.minio_secret_key)

    excluded_svc = [value.strip() for value in str(args.exclude_svc or "").split(",") if value.strip()]
    excluded_svc_prefixes = [
        value.strip() for value in str(args.exclude_svc_prefix or "").split(",") if value.strip()
    ]
    svc_filter: dict[str, Any] = {"$not": {"$regex": "^[XU]"}}
    if excluded_svc:
        svc_filter["$nin"] = excluded_svc
    if excluded_svc_prefixes:
        excluded_prefix_regex = "|".join(re.escape(prefix) for prefix in excluded_svc_prefixes)
        svc_filter["$not"] = {"$regex": f"^(?:[XU]|(?:{excluded_prefix_regex}))"}
    query = {
        "svc": svc_filter,
        "$or": [{"body.size": {"$gt": 0}}, {"attach.0": {"$exists": True}}],
    }
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
    started = time.time()
    last_id = args.after_id or _read_state(args.state_file)
    remaining = args.limit if args.limit > 0 else None
    skipped_initial = 0
    while True:
        page_query = dict(query)
        if last_id:
            page_query["_id"] = {"$gt": last_id}
        page_limit = max(1, int(args.batch_size))
        if remaining is not None:
            page_limit = min(page_limit, remaining)
            if page_limit <= 0:
                break
        docs = list(messages.find(page_query, projection=projection).sort("_id", 1).limit(page_limit))
        if not docs:
            break
        for msg in docs:
            if args.skip and skipped_initial < args.skip:
                skipped_initial += 1
                last_id = str(msg["_id"])
                _write_state(args.state_file, last_id)
                continue
            _process_message(args, db, minio, msg, stats, started)
            last_id = str(msg["_id"])
            _write_state(args.state_file, last_id)
            if remaining is not None:
                remaining -= 1
                if remaining <= 0:
                    break
        if remaining is not None and remaining <= 0:
            break

    print(f"[done] {stats} last_id={last_id} elapsed_sec={time.time() - started:.1f}", flush=True)
    return 0


def _process_message(args, db, minio: MinioSigV4Client, msg: dict[str, Any], stats: dict[str, int], started: float) -> None:
        stats["messages"] += 1
        msg_id = str(msg["_id"])
        if args.body and int((msg.get("body") or {}).get("size") or 0) > 0:
            try:
                text = normalize_text_for_embedding(read_body_text(db, args.month, msg))
                if text:
                    post_json(
                        args.api_url,
                        "/similarity/logs",
                        {
                            "log_id": f"{msg_id}:body",
                            "text": text[: args.max_text_chars],
                            "svc": msg.get("svc"),
                            "user_id": (msg.get("user") or {}).get("userId") or (msg.get("sender") or {}).get("userId"),
                            "ctime": msg.get("ctime").isoformat() if hasattr(msg.get("ctime"), "isoformat") else None,
                            "metadata": build_metadata(msg, "body"),
                        },
                    )
                    stats["body_ok"] += 1
                else:
                    stats["skipped_empty"] += 1
            except Exception as exc:
                stats["body_fail"] += 1
                print(f"[warn] body failed msg_id={msg_id} err={exc}", flush=True)

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
                    post_json(
                        args.api_url,
                        "/similarity/logs",
                        {
                            "log_id": f"{msg_id}:attach:{idx}",
                            "text": text[: args.max_text_chars],
                            "svc": msg.get("svc"),
                            "user_id": (msg.get("user") or {}).get("userId") or (msg.get("sender") or {}).get("userId"),
                            "ctime": msg.get("ctime").isoformat() if hasattr(msg.get("ctime"), "isoformat") else None,
                            "metadata": build_metadata(
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
                        },
                    )
                    stats["attach_ok"] += 1
                except Exception as exc:
                    stats["attach_fail"] += 1
                    print(f"[warn] attach failed msg_id={msg_id} idx={idx} path={path} err={exc}", flush=True)

        if stats["messages"] % max(1, args.progress_every) == 0:
            elapsed = max(0.001, time.time() - started)
            print(f"[progress] {stats} elapsed_sec={elapsed:.1f}", flush=True)


def _read_state(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _write_state(path: str, value: str) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(value or ""))
    os.replace(tmp, path)


if __name__ == "__main__":
    raise SystemExit(main())

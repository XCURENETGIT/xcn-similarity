from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

from pymongo import MongoClient


logger = logging.getLogger(__name__)


def read_ems_source(
    *,
    mongo_uri: str,
    minio_endpoint: str,
    minio_access_key: str,
    minio_secret_key: str,
    svc: str,
    source_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    month = _month_from_source_id(source_id)
    client = MongoClient(mongo_uri)
    db = client["venus"]
    collection_name = f"EMS_MESSAGE_{month}"
    msg = db[f"EMS_MESSAGE_{month}"].find_one(_message_query(svc=svc, source_id=source_id), projection=_message_projection())
    if not msg:
        logger.info(
            "ems source not found svc=%s source_id=%s collection=%s elapsed_ms=%.1f",
            svc,
            source_id,
            collection_name,
            _elapsed_ms(started),
        )
        return {}
    minio = MinioSigV4Client(minio_endpoint, minio_access_key, minio_secret_key)
    result: dict[str, Any] = {"message": msg, "body": {}, "attachments": []}
    body_started = time.perf_counter()
    body_text = read_body_text(db, month, msg)
    logger.info(
        "ems body text read svc=%s source_id=%s chars=%d elapsed_ms=%.1f",
        svc,
        source_id,
        len(body_text),
        _elapsed_ms(body_started),
    )
    if body_text:
        result["body"] = {"text": body_text}
    attachments = []
    attach_with_text = 0
    for idx, attach in enumerate(msg.get("attach") or []):
        if not isinstance(attach, dict):
            continue
        item = dict(attach)
        item["attachment_index"] = idx
        item["attach_index"] = idx
        attach_started = time.perf_counter()
        text = read_attachment_text(db, minio, msg, attach)
        if attach.get("text_source"):
            item["text_source"] = attach.get("text_source")
        if text:
            item["text"] = text
            attach_with_text += 1
        logger.info(
            "ems attachment text read svc=%s source_id=%s attach_index=%d name=%s ext=%s size=%s is_ocr=%s hash=%s chars=%d source=%s elapsed_ms=%.1f",
            svc,
            source_id,
            idx,
            attach.get("name"),
            attach.get("ext"),
            attach.get("size"),
            attach.get("isOcr"),
            attach.get("hash"),
            len(text),
            item.get("text_source") or "none",
            _elapsed_ms(attach_started),
        )
        attachments.append(item)
    result["attachments"] = attachments
    logger.info(
        "ems source read completed svc=%s source_id=%s collection=%s attach_count=%d attach_text_count=%d body_chars=%d elapsed_ms=%.1f",
        svc,
        source_id,
        collection_name,
        len(attachments),
        attach_with_text,
        len(body_text),
        _elapsed_ms(started),
    )
    return result


def build_ems_log_rows(*, svc: str, source_id: str, source: dict[str, Any], request_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    msg = dict(source.get("message") or {})
    if not msg:
        return []
    effective_svc = str(svc or msg.get("svc") or "")
    base_metadata = build_metadata(msg, "body")
    base_metadata.update(dict(request_metadata or {}))
    base_metadata["svc"] = effective_svc
    rows: list[dict[str, Any]] = []
    body = source.get("body") or {}
    body_text = body.get("text") if isinstance(body, dict) else ""
    if isinstance(body_text, str) and body_text.strip():
        rows.append(
            {
                "log_id": f"{source_id}:body",
                "text": body_text,
                "svc": effective_svc,
                "user_id": base_metadata.get("user_id") or "",
                "ctime": base_metadata.get("ctime"),
                "metadata": {**base_metadata, "source_type": "body"},
            }
        )
    for idx, attach in enumerate(source.get("attachments") or []):
        if not isinstance(attach, dict):
            continue
        text = attach.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        attach_index = _safe_int(attach.get("attachment_index"), _safe_int(attach.get("attach_index"), idx))
        metadata = build_metadata(
            msg,
            "attachment",
            {
                "attachment_index": attach_index,
                "attach_index": attach_index,
                "attach_id": attach.get("id"),
                "attach_name": attach.get("name"),
                "attachment_name": attach.get("name"),
                "file_name": attach.get("name"),
                "attach_ext": attach.get("ext"),
                "attach_size": attach.get("size"),
                "attach_path": attach.get("path"),
                "attach_textPath": attach.get("textPath"),
                "attach_text_source": attach.get("text_source"),
            },
        )
        metadata.update(dict(request_metadata or {}))
        metadata["svc"] = effective_svc
        rows.append(
            {
                "log_id": f"{source_id}:attach:{attach_index}",
                "text": text,
                "svc": effective_svc,
                "user_id": metadata.get("user_id") or "",
                "ctime": metadata.get("ctime"),
                "metadata": metadata,
            }
        )
    return rows


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


def read_attachment_text(db, minio: "MinioSigV4Client", msg: dict[str, Any], attach: dict[str, Any]) -> str:
    attach_hash = str(attach.get("hash") or "").strip()
    msg_id = str(msg.get("_id") or "").strip()
    if attach_hash and msg_id:
        row = db["EMS_ATTACHTEXT"].find_one(
            {"msgId": msg_id, "attachHash": attach_hash},
            projection={"_id": 0, "text": 1},
        )
        text = row.get("text") if row else ""
        if isinstance(text, str) and text.strip():
            attach["text_source"] = "EMS_ATTACHTEXT"
            return text

    text_path = str(attach.get("textPath") or "").strip()
    if not text_path:
        return ""
    try:
        text = minio.get_text_by_path(text_path)
        if text:
            attach["text_source"] = "textPath"
        return text
    except Exception as exc:
        logger.warning(
            "ems attachment textPath read failed msgid=%s name=%s textPath=%s error=%s",
            msg.get("_id"),
            attach.get("name"),
            text_path,
            exc,
        )
        return ""


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
        canonical_request = "\n".join(["GET", canonical_uri, "", canonical_headers, signed_headers, payload_hash])
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(self._signing_key(date_stamp), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
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


def _message_query(*, svc: str, source_id: str) -> dict[str, Any]:
    query: dict[str, Any] = {"_id": str(source_id)}
    if str(svc or "").strip():
        query["svc"] = str(svc).strip()
    return query


def _message_projection() -> dict[str, int]:
    return {
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


def _month_from_source_id(source_id: str) -> str:
    value = str(source_id or "").strip()
    if len(value) < 6 or not value[:6].isdigit():
        raise ValueError("_id must start with yyyymm to resolve EMS monthly collection")
    return value[:6]


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


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)

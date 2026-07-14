from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def as_kst(value: datetime, *, naive_timezone=KST) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=naive_timezone)
    return value.astimezone(KST)


def kst_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return as_kst(value).isoformat()
    return str(value or "")


def kst_naive_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return as_kst(value).replace(tzinfo=None).isoformat()
    text = str(value or "").strip()
    if not text:
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return as_kst(parsed).replace(tzinfo=None).isoformat() if parsed.tzinfo else parsed.isoformat()


def normalize_kst_payload(value: Any, *, key: str = "") -> Any:
    if isinstance(value, datetime):
        return as_kst(value)
    if isinstance(value, dict):
        return {item_key: normalize_kst_payload(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [normalize_kst_payload(item, key=key) for item in value]
    if isinstance(value, str) and (key.endswith("_at") or key.endswith("_hour")):
        text = value.strip()
        if not text:
            return value
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return value
        return as_kst(parsed).isoformat() if parsed.tzinfo else parsed.replace(tzinfo=KST).isoformat()
    return value

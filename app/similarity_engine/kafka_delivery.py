from __future__ import annotations

import json
import logging
import socket
import struct
import time
import zlib
from datetime import date, datetime
from typing import Any

from app.time_utils import KST, as_kst


logger = logging.getLogger(__name__)


def _build_crc32c_table() -> list[int]:
    table: list[int] = []
    polynomial = 0x82F63B78
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ polynomial
            else:
                crc >>= 1
        table.append(crc & 0xFFFFFFFF)
    return table


_CRC32C_TABLE = _build_crc32c_table()


class KafkaDeliveryError(RuntimeError):
    pass


class SimpleKafkaProducer:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic: str,
        client_id: str = "xcn-similarity",
        timeout_sec: int = 5,
    ):
        self.bootstrap_servers = _parse_bootstrap_servers(bootstrap_servers)
        self.topic = str(topic or "").strip()
        self.client_id = str(client_id or "xcn-similarity").strip()
        self.timeout_sec = max(1, int(timeout_sec or 5))
        if not self.bootstrap_servers:
            raise ValueError("bootstrap_servers is required")
        if not self.topic:
            raise ValueError("topic is required")

    def send_json(self, value: dict[str, Any], *, key: str | None = None) -> dict[str, Any]:
        payload = json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":")).encode("utf-8")
        key_bytes = key.encode("utf-8") if key else None
        last_error: Exception | None = None
        for host, port in self.bootstrap_servers:
            try:
                return self._send_to_broker(host, port, payload, key_bytes)
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = exc
                logger.warning("kafka delivery failed broker=%s:%s topic=%s error=%s", host, port, self.topic, exc)
        raise KafkaDeliveryError(str(last_error or "no kafka broker available"))

    def _send_to_broker(
        self,
        host: str,
        port: int,
        value: bytes,
        key: bytes | None,
    ) -> dict[str, Any]:
        request = _build_produce_v3_request(
            topic=self.topic,
            value=value,
            key=key,
            client_id=self.client_id,
            correlation_id=1,
        )
        with socket.create_connection((host, int(port)), timeout=self.timeout_sec) as sock:
            sock.settimeout(self.timeout_sec)
            sock.sendall(request)
            size_raw = _recv_exact(sock, 4)
            size = struct.unpack(">i", size_raw)[0]
            response = _recv_exact(sock, size)
        error_code, offset = _parse_produce_v3_response(response)
        if error_code != 0:
            raise KafkaDeliveryError(f"kafka produce error_code={error_code}")
        return {"topic": self.topic, "partition": 0, "offset": offset}


def _build_produce_v3_request(
    *,
    topic: str,
    value: bytes,
    key: bytes | None,
    client_id: str,
    correlation_id: int,
) -> bytes:
    record_set = _build_record_batch_v2(value=value, key=key)
    body = (
        struct.pack(">h", -1)
        + struct.pack(">h", 1)
        + struct.pack(">i", 10000)
        + struct.pack(">i", 1)
        + _kafka_string(topic)
        + struct.pack(">i", 1)
        + struct.pack(">i", 0)
        + struct.pack(">i", len(record_set))
        + record_set
    )
    header = (
        struct.pack(">h", 0)
        + struct.pack(">h", 3)
        + struct.pack(">i", correlation_id)
        + _kafka_string(client_id)
    )
    request = header + body
    return struct.pack(">i", len(request)) + request


def _build_message_v0(*, value: bytes, key: bytes | None) -> bytes:
    key_part = struct.pack(">i", -1) if key is None else struct.pack(">i", len(key)) + key
    value_part = struct.pack(">i", len(value)) + value
    body = b"\x00\x00" + key_part + value_part
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return struct.pack(">I", crc) + body


def _build_record_batch_v2(*, value: bytes, key: bytes | None) -> bytes:
    timestamp_ms = int(time.time() * 1000)
    key_part = _varint(-1) if key is None else _varint(len(key)) + key
    value_part = _varint(len(value)) + value
    record_body = b"\x00" + _varlong(0) + _varint(0) + key_part + value_part + _varint(0)
    record = _varint(len(record_body)) + record_body
    crc_body = (
        struct.pack(">h", 0)
        + struct.pack(">i", 0)
        + struct.pack(">q", timestamp_ms)
        + struct.pack(">q", timestamp_ms)
        + struct.pack(">q", -1)
        + struct.pack(">h", -1)
        + struct.pack(">i", -1)
        + struct.pack(">i", 1)
        + record
    )
    crc = _crc32c(crc_body)
    batch_body = struct.pack(">i", 0) + b"\x02" + struct.pack(">I", crc) + crc_body
    return struct.pack(">q", 0) + struct.pack(">i", len(batch_body)) + batch_body


def _parse_produce_v3_response(response: bytes) -> tuple[int, int]:
    pos = 0
    _correlation_id = struct.unpack_from(">i", response, pos)[0]
    pos += 4
    topic_count = struct.unpack_from(">i", response, pos)[0]
    pos += 4
    if topic_count < 1:
        raise KafkaDeliveryError("empty kafka produce response")
    topic_len = struct.unpack_from(">h", response, pos)[0]
    pos += 2 + topic_len
    partition_count = struct.unpack_from(">i", response, pos)[0]
    pos += 4
    if partition_count < 1:
        raise KafkaDeliveryError("empty kafka partition response")
    _partition = struct.unpack_from(">i", response, pos)[0]
    pos += 4
    error_code = struct.unpack_from(">h", response, pos)[0]
    pos += 2
    offset = struct.unpack_from(">q", response, pos)[0]
    return error_code, offset


def _varint(value: int) -> bytes:
    unsigned = (int(value) << 1) ^ (int(value) >> 31)
    return _unsigned_varint(unsigned)


def _varlong(value: int) -> bytes:
    unsigned = (int(value) << 1) ^ (int(value) >> 63)
    return _unsigned_varint(unsigned)


def _unsigned_varint(value: int) -> bytes:
    value = int(value)
    out = bytearray()
    while (value & ~0x7F) != 0:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def _crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc = _CRC32C_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = int(size)
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise KafkaDeliveryError("kafka connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _kafka_string(value: str) -> bytes:
    encoded = str(value or "").encode("utf-8")
    return struct.pack(">h", len(encoded)) + encoded


def _parse_bootstrap_servers(value: str) -> list[tuple[str, int]]:
    servers: list[tuple[str, int]] = []
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            servers.append((item, 9092))
            continue
        host, port = item.rsplit(":", 1)
        servers.append((host.strip(), int(port.strip())))
    return servers


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=KST)
        if isinstance(value, datetime):
            value = as_kst(value)
        return value.isoformat()
    return str(value)

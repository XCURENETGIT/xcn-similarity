from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    text: str
    start: int
    end: int


def normalize_text(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def chunk_text(
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    min_chunk_chars: int,
    max_chunks: int,
) -> list[TextChunk]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    if len(normalized) < max(1, int(min_chunk_chars)):
        return [TextChunk(chunk_id="chunk-000000", text=normalized, start=0, end=len(normalized))]

    size = max(1, int(chunk_size))
    overlap = max(0, min(int(chunk_overlap), size - 1))
    min_chars = max(1, int(min_chunk_chars))
    limit = max(1, int(max_chunks))

    chunks: list[TextChunk] = []
    pos = 0
    n = len(normalized)
    while pos < n and len(chunks) < limit:
        end = min(n, pos + size)
        if end < n:
            boundary = max(normalized.rfind("\n", pos, end), normalized.rfind(". ", pos, end))
            if boundary > pos + min_chars:
                end = boundary + 1
        part = normalized[pos:end].strip()
        if len(part) >= min_chars:
            chunks.append(TextChunk(chunk_id=f"chunk-{len(chunks):06d}", text=part, start=pos, end=end))
        if end >= n:
            break
        pos = max(end - overlap, pos + 1)
    return chunks

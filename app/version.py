from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip() or "0.1.0"
    except Exception:
        return "0.1.0"


APP_VERSION = _read_version()


from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            # Keep the service running if another Windows process holds the log file.
            self.stream = self._open()


class SafeRotatingFileHandler(RotatingFileHandler):
    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            self.stream = self._open()


def setup_file_logging() -> None:
    level = getattr(logging, os.getenv("SIM_LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if os.getenv("SIM_FILE_LOG_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return

    log_dir = Path(os.getenv("SIM_LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(os.getenv("SIM_LOG_MAX_BYTES", "0") or "0")
    backup_count = int(os.getenv("SIM_LOG_BACKUP_COUNT", os.getenv("SIM_LOG_BACKUP_DAYS", "30")) or "30")
    if max_bytes > 0:
        handler = SafeRotatingFileHandler(
            log_dir / "similarity-api.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    else:
        handler = SafeTimedRotatingFileHandler(
            log_dir / "similarity-api.log",
            when=os.getenv("SIM_LOG_ROTATE_WHEN", "midnight"),
            backupCount=backup_count,
            encoding="utf-8",
        )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    if not any(isinstance(h, TimedRotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)

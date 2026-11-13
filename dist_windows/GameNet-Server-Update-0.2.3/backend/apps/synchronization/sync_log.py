"""Persistent + in-memory diagnostic log for Edge -> Cloud synchronization."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections import deque
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("gamenet.cloud_sync")

_LOCK = threading.Lock()
_BUFFER: deque[dict[str, str]] = deque(maxlen=150)
_LAST_ERROR: dict[str, str] = {}
_LOG_PATH: Path | None = None
_MAX_FILE_BYTES = 1024 * 1024  # 1 MiB


def sync_log_path() -> Path:
    global _LOG_PATH
    if _LOG_PATH is not None:
        return _LOG_PATH

    base_dir = Path(getattr(settings, "BASE_DIR", os.getcwd()))
    candidates = [
        Path(os.environ["GAMENET_DATA_DIR"]) if os.environ.get("GAMENET_DATA_DIR") else None,
        base_dir / "data",
        base_dir / ".runtime",
        Path(tempfile.gettempdir()) / "gamenet_data",
    ]
    for cand in candidates:
        if cand is None:
            continue
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".sync_log_probe"
            probe.write_text("1", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _LOG_PATH = cand / "cloud_sync.jsonl"
            return _LOG_PATH
        except OSError:
            continue
    _LOG_PATH = Path(tempfile.gettempdir()) / "cloud_sync.jsonl"
    return _LOG_PATH


def record_sync_log(level: str, stage: str, message: str, *, also_logger: bool = True) -> None:
    lvl = level.upper()
    entry = {
        "at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "level": lvl,
        "stage": stage,
        "message": str(message)[:500],
    }
    if also_logger:
        if lvl in {"ERROR", "CRITICAL"}:
            logger.error("[%s] %s", stage, entry["message"])
        elif lvl == "WARNING":
            logger.warning("[%s] %s", stage, entry["message"])
        else:
            logger.info("[%s] %s", stage, entry["message"])

    with _LOCK:
        _BUFFER.append(entry)
        if lvl in {"ERROR", "WARNING"}:
            _LAST_ERROR.clear()
            _LAST_ERROR.update(entry)
        elif stage in {"heartbeat", "ws", "register"} and lvl == "INFO":
            _LAST_ERROR.clear()

        try:
            path = sync_log_path()
            if path.exists() and path.stat().st_size > _MAX_FILE_BYTES:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]
                path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


def read_sync_logs(limit: int = 60) -> list[dict[str, str]]:
    with _LOCK:
        if _BUFFER:
            return list(_BUFFER)[-limit:][::-1]

    try:
        path = sync_log_path()
        if path.exists():
            entries: list[dict[str, str]] = []
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        entries.append({str(k): str(v) for k, v in item.items()})
                except ValueError:
                    continue
            return entries[::-1]
    except OSError:
        pass
    return []


def last_sync_error() -> dict[str, Any] | None:
    with _LOCK:
        if _LAST_ERROR:
            return dict(_LAST_ERROR)
    for row in read_sync_logs(limit=30):
        if row.get("level") in {"ERROR", "WARNING"}:
            return row
    return None

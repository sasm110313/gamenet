from __future__ import annotations

import collections
import datetime
import logging
import os
import traceback
from typing import Any
from django.conf import settings

logger = logging.getLogger("gamenet.errors")

# Ring buffer for recent 50 exceptions
_RECENT_ERRORS: collections.deque[dict[str, Any]] = collections.deque(maxlen=50)


def _log_file_path() -> str:
    base_dir = getattr(settings, "BASE_DIR", os.getcwd())
    data_dir = os.environ.get("GAMENET_DATA_DIR") or os.path.join(base_dir, "data")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        pass
    return os.path.join(data_dir, "server_errors.log")


def record_server_error(request, exc: BaseException, context_info: str = "") -> dict[str, Any]:
    """Records an unhandled or caught severe exception into memory and server_errors.log."""
    now = datetime.datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    method = getattr(request, "method", "UNKNOWN") if request else "CLI/TASK"
    path = getattr(request, "path", "") if request else context_info
    user_label = "Anonymous"
    client_ip = "127.0.0.1"

    if request:
        try:
            user = getattr(request, "user", None)
            if user and getattr(user, "is_authenticated", False):
                user_label = getattr(user, "label", None) or getattr(user, "username", "Authenticated")
        except Exception:
            pass

        try:
            x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded:
                client_ip = x_forwarded.split(",")[0].strip()
            else:
                client_ip = request.META.get("REMOTE_ADDR", "127.0.0.1")
        except Exception:
            pass

    tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    error_id = f"ERR-{now.strftime('%y%m%d%H%M%S')}-{os.getpid()}"

    entry = {
        "id": error_id,
        "timestamp": now_str,
        "method": method,
        "path": path,
        "user": user_label,
        "ip": client_ip,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": tb_str,
    }

    _RECENT_ERRORS.appendleft(entry)

    # Append to log file
    try:
        log_path = _log_file_path()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*70}\n")
            f.write(f"[{entry['timestamp']}] ERROR_ID: {entry['id']}\n")
            f.write(f"REQUEST: {entry['method']} {entry['path']} | IP: {entry['ip']} | USER: {entry['user']}\n")
            f.write(f"EXCEPTION: {entry['error_type']}: {entry['message']}\n")
            f.write(f"TRACEBACK:\n{entry['traceback']}\n")
    except Exception as e:
        logger.error("Failed writing to server_errors.log: %s", e)

    return entry


def get_recent_errors(limit: int = 50) -> list[dict[str, Any]]:
    return list(_RECENT_ERRORS)[:limit]


def clear_recent_errors() -> None:
    _RECENT_ERRORS.clear()

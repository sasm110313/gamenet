"""Non-blocking Rahro (external loyalty system) calls.

The salon LAN often has no internet. A plain ``requests`` call to a public
hostname can block for many seconds inside DNS resolution, which used to make
the local admin panel feel frozen. Every call here runs in a daemon thread and
is abandoned after a short deadline, so a page never waits on Rahro.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("gamenet.rahro")

_FAILURE_COOLDOWN = 60.0
_last_failure = 0.0
_lock = threading.Lock()


def _base_url() -> str:
    return str(getattr(settings, "RAHRO_API_URL", "https://hammasjedy.ir/rahro/api/gamenet/"))


def _secret() -> str:
    return str(getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026"))


def _cooling_down() -> bool:
    return (time.monotonic() - _last_failure) < _FAILURE_COOLDOWN


def _mark_failed() -> None:
    global _last_failure
    with _lock:
        _last_failure = time.monotonic()


def _run(method: str, path: str, *, params=None, payload=None, deadline: float = 1.2, honor_cooldown: bool = True):
    """Execute the HTTP call in a daemon thread; return a result dict or None."""
    if honor_cooldown and _cooling_down():
        return None
    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            import requests

            url = f"{_base_url().rstrip('/')}/{path.lstrip('/')}"
            headers = {"X-Internal-Secret": _secret()}
            kwargs: dict[str, Any] = {"headers": headers, "timeout": (1.5, 3.0)}
            if params:
                kwargs["params"] = params
            if payload is not None:
                headers["Content-Type"] = "application/json"
                kwargs["json"] = payload
            response = (requests.post if method.upper() == "POST" else requests.get)(url, **kwargs)
            result["status"] = response.status_code
            try:
                result["data"] = response.json()
            except Exception:
                result["data"] = None
        except Exception as exc:  # network/DNS errors
            result["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(deadline)
    if thread.is_alive():
        logger.info("Rahro %s %s exceeded %.1fs; rendering without it", method, path, deadline)
        _mark_failed()
        return None
    if "error" in result:
        logger.info("Rahro %s %s failed: %s", method, path, result["error"])
        _mark_failed()
        return None
    return result


def fetch_status(phone: str, username: str = "", *, deadline: float = 1.2) -> dict | bool | None:
    """Return the cached Rahro status immediately and refresh it in the background.

    The admin page must never wait for the external system, even on the first view.
    """
    key = f"rahro_status_{phone or ''}_{username or ''}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    if not phone:
        return None
    _refresh_status_in_background(key, phone, username)
    return None


_inflight: set[str] = set()


def _refresh_status_in_background(key: str, phone: str, username: str) -> None:
    with _lock:
        if key in _inflight:
            return
        _inflight.add(key)

    def worker() -> None:
        try:
            if _cooling_down():
                cache.set(key, False, timeout=120)
                return
            import requests

            response = requests.get(
                f"{_base_url().rstrip('/')}/status/",
                params={"phone": phone, "username": username},
                headers={"X-Internal-Secret": _secret()},
                timeout=(1.5, 3.0),
            )
            data = response.json() if response.status_code == 200 else None
            if isinstance(data, dict) and data.get("found"):
                cache.set(key, data, timeout=600)
            else:
                cache.set(key, False, timeout=120)
        except Exception as exc:
            logger.info("Rahro status refresh failed: %s", exc)
            _mark_failed()
            cache.set(key, False, timeout=120)
        finally:
            with _lock:
                _inflight.discard(key)

    threading.Thread(target=worker, daemon=True).start()


def apply_discount(*, phone: str, username: str, discount_percent: int, session_id=None, actor_name: str = "", deadline: float = 4.0):
    """Ask Rahro to consume a coupon/quota. Returns (ok, data_or_error_message)."""
    response = _run(
        "POST",
        "apply-discount/",
        payload={
            "phone": phone,
            "username": username,
            "discount_percent": discount_percent,
            "session_id": str(session_id) if session_id else None,
            "actor_name": actor_name,
        },
        deadline=deadline,
        honor_cooldown=False,
    )
    if response is None:
        return False, "سامانه رهرو پاسخ نداد (حالت محلی/آفلاین)."
    data = response.get("data") or {}
    if response.get("status") != 200 or not data.get("success"):
        return False, data.get("error") or data.get("message") or f"خطا در ارتباط با رهرو ({response.get('status')})"
    return True, data


def record_session(payload: dict, *, deadline: float = 4.0) -> bool:
    """Best-effort session record (fire and forget)."""
    response = _run("POST", "record-session/", payload=payload, deadline=deadline, honor_cooldown=False)
    return bool(response and response.get("status") == 200)

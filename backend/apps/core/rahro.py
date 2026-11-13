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
_last_failure: float | None = None
_lock = threading.Lock()
_network_slots = threading.BoundedSemaphore(4)


def _base_url() -> str:
    return str(getattr(settings, "RAHRO_API_URL", "https://hammasjedy.ir/rahro/api/gamenet/"))


def _secret() -> str:
    return str(getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026"))


def _cooling_down() -> bool:
    return _last_failure is not None and (time.monotonic() - _last_failure) < _FAILURE_COOLDOWN


def _mark_failed() -> None:
    global _last_failure
    with _lock:
        _last_failure = time.monotonic()


def _run(method: str, path: str, *, params=None, payload=None, deadline: float = 1.2, honor_cooldown: bool = True):
    """Execute the HTTP call in a daemon thread; return a result dict or None."""
    if honor_cooldown and _cooling_down():
        return None
    if not _network_slots.acquire(blocking=False):
        return None
    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            import requests

            url = f"{_base_url().rstrip('/')}/{path.lstrip('/')}"
            headers = {"X-Internal-Secret": _secret()}
            if payload and payload.get("session_id"):
                headers["Idempotency-Key"] = f"gamenet:{path}:{payload['session_id']}"
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
        finally:
            _network_slots.release()

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
        if not _network_slots.acquire(blocking=False):
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
            _network_slots.release()
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
    data = response.get("data")
    if not isinstance(data, dict):
        return False, "پاسخ نامعتبر از سامانه رهرو دریافت شد."
    if response.get("status") != 200 or not data.get("success"):
        return False, data.get("error") or data.get("message") or f"خطا در ارتباط با رهرو ({response.get('status')})"
    cache.delete(f"rahro_status_{phone or ''}_{username or ''}")
    return True, data


def record_session(payload: dict, *, deadline: float = 4.0) -> bool:
    """Best-effort session record (fire and forget)."""
    response = _run("POST", "record-session/", payload=payload, deadline=deadline, honor_cooldown=False)
    if not response or response.get("status") not in {200, 201, 204}:
        return False
    data = response.get("data")
    if response["status"] != 204 and (
        not isinstance(data, dict) or data.get("success") is False or data.get("ok") is False or data.get("error")
    ):
        return False
    cache.delete(f"rahro_status_{payload.get('phone', '')}_{payload.get('username', '')}")
    return True


def queue_session_record(payload: dict):
    from apps.synchronization.models import RahroDelivery

    return RahroDelivery.objects.get_or_create(
        session_id=payload["session_id"], defaults={"payload": payload}
    )[0]


def drain_session_records(*, now=None, limit=10) -> int:
    from datetime import timedelta
    from django.db.models import F
    from django.utils import timezone
    from apps.synchronization.models import RahroDelivery

    now = now or timezone.now()
    delivered = 0
    due = list(RahroDelivery.objects.filter(
        delivered_at__isnull=True, next_attempt_at__lte=now
    ).order_by("next_attempt_at")[:limit])
    for record in due:
        claimed = RahroDelivery.objects.filter(
            pk=record.pk, delivered_at__isnull=True, next_attempt_at__lte=now
        ).update(next_attempt_at=now + timedelta(seconds=60), attempts=F("attempts") + 1)
        if not claimed:
            continue
        try:
            ok = record_session(record.payload)
            error = "" if ok else "Rahro did not confirm the session record"
        except Exception as exc:
            ok, error = False, str(exc)
        if ok:
            RahroDelivery.objects.filter(pk=record.pk).update(delivered_at=timezone.now(), last_error="")
            delivered += 1
        else:
            RahroDelivery.objects.filter(pk=record.pk).update(
                next_attempt_at=max(now, timezone.now()) + timedelta(seconds=min(2 ** min(record.attempts + 1, 12), 3600)),
                last_error=error[:2000],
            )
    return delivered


_delivery_started = False


def start_delivery_worker() -> None:
    global _delivery_started
    with _lock:
        if _delivery_started:
            return
        _delivery_started = True

    def worker():
        from django.db import close_old_connections

        while True:
            try:
                drain_session_records()
            except Exception:
                logger.exception("Rahro delivery cycle failed")
            finally:
                close_old_connections()
            time.sleep(5)

    threading.Thread(target=worker, name="rahro-delivery", daemon=True).start()

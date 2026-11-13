from __future__ import annotations

import hmac
import json
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def canonical_json(payload: Any) -> str:
    """Deterministic JSON for signatures and content hashes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(secret: str, payload: Any) -> str:
    return hmac.new(secret.encode(), canonical_json(payload).encode(), "sha256").hexdigest()


def verify(secret: str, payload: Any, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, payload), signature)


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def require_setting(name: str) -> Any:
    value = getattr(settings, name, None)
    if not value:
        raise ImproperlyConfigured(f"{name} is not configured")
    return value

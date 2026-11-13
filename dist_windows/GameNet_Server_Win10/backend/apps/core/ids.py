"""Small, dependency-free primitives shared by every app."""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7 (time-ordered), compatible with Python < 3.14.

    Ordering by primary key therefore roughly follows creation time, which keeps
    index locality good and makes debugging sync streams far easier.
    """
    unix_ms = int(time.time() * 1000)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0x2 << 62
    value |= rand_b
    return uuid.UUID(int=value)


def uuid7_from(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def parse_uuid(value) -> uuid.UUID | None:
    """Return a UUID for well-formed input, otherwise None (never raises)."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value or "").strip())
    except (ValueError, TypeError, AttributeError):
        return None

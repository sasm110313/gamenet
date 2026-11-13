"""PostgreSQL transaction-scoped advisory locks.

All money paths for one customer serialize on the same key. The lock is held
until the surrounding transaction ends, so two concurrent session starts cannot
both observe the same available credit.
"""

from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager

from django.db import connection, transaction

from functools import wraps


_customer_thread_locks: dict[str, threading.RLock] = {}
_locks_meta_lock = threading.Lock()


def _get_customer_rlock(customer_id) -> threading.RLock:
    key = str(customer_id)
    with _locks_meta_lock:
        if key not in _customer_thread_locks:
            _customer_thread_locks[key] = threading.RLock()
        return _customer_thread_locks[key]


@contextmanager
def customer_mutex(customer_id):
    """Reentrant in-process mutex per customer to prevent race conditions across threads/views."""
    lock = _get_customer_rlock(customer_id)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def serialized_customer(fn):
    """Serialize a money path in-process for the customer tied to the first argument."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        target = kwargs.get("customer") or (args[0] if args else None)
        cid = getattr(target, "customer_id", None) or getattr(target, "id", None)
        if cid is None:
            return fn(*args, **kwargs)
        with customer_mutex(cid):
            return fn(*args, **kwargs)

    return wrapper


def advisory_lock(key: str) -> None:
    """Take a transaction-scoped advisory lock derived deterministically from key."""
    if not connection.in_atomic_block:
        raise RuntimeError("advisory_lock requires an active transaction")
    if connection.vendor != "postgresql":
        # SQLite on Windows Edge serializes transactions at the database/table level
        # and has no pg_advisory_xact_lock. In-process mutex provides concurrency control.
        return
    digest = hashlib.sha256(key.encode()).digest()
    first = int.from_bytes(digest[:4], "big", signed=True)
    second = int.from_bytes(digest[4:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [first, second])


def customer_lock(customer_id) -> None:
    advisory_lock(f"gamenet:customer:{customer_id}")


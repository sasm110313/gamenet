"""PostgreSQL transaction-scoped advisory locks.

All money paths for one customer serialize on the same key. The lock is held
until the surrounding transaction ends, so two concurrent session starts cannot
both observe the same available credit.
"""

from __future__ import annotations

import hashlib

from django.db import connection, transaction


def advisory_lock(key: str) -> None:
    """Take a transaction-scoped advisory lock derived deterministically from key."""
    if not connection.in_atomic_block:
        raise RuntimeError("advisory_lock requires an active transaction")
    digest = hashlib.sha256(key.encode()).digest()
    first = int.from_bytes(digest[:4], "big", signed=True)
    second = int.from_bytes(digest[4:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [first, second])


def customer_lock(customer_id) -> None:
    advisory_lock(f"gamenet:customer:{customer_id}")

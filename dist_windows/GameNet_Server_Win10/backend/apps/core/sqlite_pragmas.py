"""SQLite hardening for the local hub.

The edge runs on SQLite by default. WAL lets readers and the single writer work
concurrently, and a generous busy timeout makes short write bursts wait instead
of raising ``database is locked``. ``transaction_mode=IMMEDIATE`` (see
``gamenet.settings.edge``) removes the deferred read→write upgrade deadlock.
"""

from __future__ import annotations

import logging

from django.db.backends.signals import connection_created
from django.dispatch import receiver

logger = logging.getLogger("gamenet.sqlite")

_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=20000",
    "PRAGMA synchronous=NORMAL",
)


@receiver(connection_created)
def _apply_sqlite_pragmas(sender, connection, **kwargs) -> None:
    if connection.vendor != "sqlite":
        return
    try:
        with connection.cursor() as cursor:
            for statement in _PRAGMAS:
                cursor.execute(statement)
    except Exception as exc:  # never prevent the app from starting
        logger.warning("Could not apply SQLite pragmas: %s", exc)

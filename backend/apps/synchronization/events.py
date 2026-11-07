"""Event emission on the edge. Must be called inside the business transaction."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.core.roles import require_edge
from apps.core.ids import uuid7
from apps.synchronization.models import EdgeIdentity, OutboxEvent

logger = logging.getLogger("gamenet.outbox")

# Event types the cloud knows how to project. Unknown types are still stored, but
# emitting a typo would silently vanish from the dashboards, so Phase 0 refuses
# obviously unknown names at emit time on the edge.
KNOWN_EVENT_TYPES = {
    "device.registered",
    "device.status_changed",
    "device.deactivated",
    "device.command_result",
    "command.result",
    "config.applied",
    "edge.test",
    # Phase 1 domain facts
    "tariff.created",
    "tariff.updated",
    "customer_group.created",
    "customer_group.updated",
    "customer.created",
    "customer.updated",
    "customer_rate.created",
    "customer_rate.updated",
    "ledger.entry_created",
    "session.started",
    "session.ended",
}


def emit(
    event_type: str,
    *,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any] | None = None,
    schema_version: int | None = None,
    occurred_at: datetime | None = None,
) -> OutboxEvent:
    require_edge()
    if not connection.in_atomic_block:
        raise RuntimeError(
            "outbox events must be written in the same transaction as the business fact; "
            "wrap the caller in transaction.atomic()"
        )
    if event_type not in KNOWN_EVENT_TYPES:
        raise ValueError(f"unknown event_type {event_type!r}")

    # Lock the singleton identity row: this allocates a gap-free, commit-ordered
    # sequence for this edge. A second writer waits for the first commit, so
    # sequence order always equals visibility order.
    from apps.synchronization.edge_credentials import ensure_identity

    ensure_identity()
    identity = EdgeIdentity.objects.select_for_update().get(pk=1)
    sequence = identity.next_sequence
    identity.next_sequence = sequence + 1
    identity.save(update_fields=["next_sequence", "updated_at"])

    event = OutboxEvent.objects.create(
        edge_id=identity.edge_id,
        local_sequence=sequence,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload=payload or {},
        schema_version=schema_version or 1,
        occurred_at=occurred_at or timezone.now(),
    )
    logger.debug("queued %s #%s %s", event_type, sequence, aggregate_id)
    return event

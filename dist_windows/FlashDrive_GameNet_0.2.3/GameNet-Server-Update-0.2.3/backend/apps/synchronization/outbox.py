"""Edge outbox drain: ordered, at-least-once, idempotent at the receiver.

Ordering is strict FIFO by local_sequence. A FAILED head blocks the stream on
purpose: financial events must never overtake each other. The dashboard exposes
the block and an explicit retry action.
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.roles import require_edge
from apps.synchronization.cloud_client import CloudClient, CloudRejected, CloudUnavailable
from apps.synchronization.edge_credentials import load_credentials
from apps.synchronization.models import EdgeIdentity, OutboxEvent, OutboxStatus

logger = logging.getLogger("gamenet.outbox")

TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}


def serialize(event: OutboxEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "local_sequence": event.local_sequence,
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "schema_version": event.schema_version,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": event.payload,
    }


def backoff_seconds(attempts: int, *, jitter: bool = True) -> float:
    base = min(2 ** max(attempts - 1, 0), 60)
    if not jitter:
        return float(base)
    return base * random.uniform(0.8, 1.2)


def pending_counts() -> dict[str, int]:
    counts = {choice: 0 for choice in OutboxStatus.values}
    for row in OutboxEvent.objects.values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]
    return counts


def recover_stale(now=None) -> int:
    """Events left SYNCING by a crash go back to PENDING; they were never acked."""
    return OutboxEvent.objects.filter(status=OutboxStatus.SYNCING).update(status=OutboxStatus.PENDING)


def _truncate_at_failed(events: list[OutboxEvent], now) -> tuple[list[OutboxEvent], bool]:
    eligible: list[OutboxEvent] = []
    for event in events:
        if event.status == OutboxStatus.FAILED:
            return eligible, True
        if event.next_attempt_at and event.next_attempt_at > now:
            return eligible, False
        eligible.append(event)
    return eligible, False


@transaction.atomic
def _claim(now) -> tuple[list[OutboxEvent], bool, int]:
    identity = EdgeIdentity.objects.select_for_update().get(pk=1)
    qs = (
        OutboxEvent.objects.filter(local_sequence__gt=identity.last_acked_sequence)
        .exclude(status=OutboxStatus.SYNCED)
        .order_by("local_sequence")[: settings.SYNC_BATCH_SIZE]
    )
    events, blocked = _truncate_at_failed(list(qs), now)
    if events:
        OutboxEvent.objects.filter(id__in=[e.id for e in events]).update(status=OutboxStatus.SYNCING)
        for event in events:
            event.status = OutboxStatus.SYNCING
    return events, blocked, identity.last_acked_sequence


def _defer(events: list[OutboxEvent], now, error: str) -> None:
    for event in events:
        attempts = event.attempts + 1
        OutboxEvent.objects.filter(id=event.id).update(
            status=OutboxStatus.PENDING,
            attempts=attempts,
            last_error=error[:2000],
            next_attempt_at=now + timedelta(seconds=backoff_seconds(attempts)),
        )


def drain_outbox(*, client: CloudClient | None = None, now=None) -> dict[str, Any]:
    require_edge()
    now = now or timezone.now()
    recover_stale(now)

    try:
        identity = EdgeIdentity.get_solo()
    except EdgeIdentity.DoesNotExist:
        return {"skipped": "edge is not registered"}

    stats: dict[str, Any] = {"sent": 0, "accepted": 0, "duplicates": 0, "rejected": 0}
    events, blocked, _ = _claim(now)
    if not events:
        stats.update(pending_counts())
        stats["blocked"] = blocked
        return stats

    client = client or CloudClient(load_credentials())
    stats["sent"] = len(events)
    try:
        response = client.post_events([serialize(e) for e in events])
    except CloudUnavailable as exc:
        _defer(events, now, f"cloud unavailable: {exc}")
        stats.update(pending_counts())
        stats["error"] = str(exc)
        return stats
    except CloudRejected as exc:
        if exc.status in TRANSIENT_HTTP or exc.status in {401, 403}:
            _defer(events, now, f"cloud rejected: HTTP {exc.status}")
            stats["error"] = f"HTTP {exc.status}"
        else:
            # Structural rejection: terminal until an operator intervenes.
            reason = str(exc.body)[:2000]
            OutboxEvent.objects.filter(id__in=[e.id for e in events]).update(
                status=OutboxStatus.FAILED, last_error=reason
            )
            stats["rejected"] = len(events)
            stats["error"] = reason
        stats.update(pending_counts())
        return stats

    acked = set(response.get("accepted", [])) | set(response.get("duplicates", []))
    rejected = {r["event_id"]: r.get("reason", "") for r in response.get("rejected", [])}
    ack_now = timezone.now()
    acked_sequences: list[int] = []

    for event in events:
        event_id = str(event.event_id)
        if event_id in acked:
            OutboxEvent.objects.filter(id=event.id).update(
                status=OutboxStatus.SYNCED,
                cloud_acknowledged_at=ack_now,
                attempts=event.attempts + 1,
                last_error="",
                next_attempt_at=None,
            )
            acked_sequences.append(event.local_sequence)
        else:
            OutboxEvent.objects.filter(id=event.id).update(
                status=OutboxStatus.FAILED,
                attempts=event.attempts + 1,
                last_error=rejected.get(event_id, "not acknowledged")[:2000],
            )

    stats["accepted"] = len(response.get("accepted", []))
    stats["duplicates"] = len(response.get("duplicates", []))
    stats["rejected"] = len(rejected)

    if acked_sequences:
        # Watermark may only advance over a contiguous acknowledged prefix.
        new_watermark = identity.last_acked_sequence
        for sequence in sorted(acked_sequences):
            if sequence == new_watermark + 1:
                new_watermark = sequence
            elif sequence > new_watermark + 1:
                break
        EdgeIdentity.objects.filter(pk=1).update(last_acked_sequence=new_watermark, last_sync_at=ack_now)

    stats.update(pending_counts())
    stats["blocked"] = blocked or stats["rejected"] > 0
    return stats


def retry_failed(event_id: str | None = None) -> int:
    """Operator action: unblock the queue after fixing the cause."""
    require_edge()
    qs = OutboxEvent.objects.filter(status=OutboxStatus.FAILED)
    if event_id:
        qs = qs.filter(event_id=event_id)
    return qs.update(status=OutboxStatus.PENDING, attempts=0, next_attempt_at=None, last_error="")


def unblock_for_reconnect() -> int:
    """Invoked when internet / cloud connection is restored.
    Clears backoff timers on all pending events and recovers events deferred
    due to cloud unavailability or transient network drops.
    """
    require_edge()
    count = OutboxEvent.objects.filter(status=OutboxStatus.PENDING).exclude(next_attempt_at=None).update(next_attempt_at=None)

    recovered = OutboxEvent.objects.filter(
        status=OutboxStatus.FAILED
    ).filter(
        Q(last_error__icontains="unavailable")
        | Q(last_error__icontains="timeout")
        | Q(last_error__icontains="connection")
        | Q(last_error__icontains="HTTP 5")
        | Q(last_error__icontains="HTTP 4")
        | Q(last_error__icontains="Temporary")
    ).update(
        status=OutboxStatus.PENDING,
        attempts=0,
        next_attempt_at=None,
        last_error="",
    )
    if count or recovered:
        logger.info(
            "Outbox unblocked for reconnect: %d pending timers cleared, %d transiently failed recovered",
            count,
            recovered,
        )
    return count + recovered

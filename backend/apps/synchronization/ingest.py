"""Cloud-side ingest: validate, deduplicate, project, acknowledge."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.roles import require_cloud
from apps.synchronization.handlers import apply_event
from apps.synchronization.models import EdgeNode, SyncEvent, SyncEventStatus

logger = logging.getLogger("gamenet.ingest")

MAX_BATCH = 500
REQUIRED_FIELDS = {
    "event_id",
    "local_sequence",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "schema_version",
    "occurred_at",
    "payload",
}


class InvalidEvent(ValueError):
    pass


def _parse_event(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InvalidEvent("event must be an object")
    missing = REQUIRED_FIELDS - raw.keys()
    if missing:
        raise InvalidEvent(f"missing fields: {sorted(missing)}")
    try:
        event_id = uuid.UUID(str(raw["event_id"]))
    except (ValueError, TypeError) as exc:
        raise InvalidEvent("event_id is not a UUID") from exc
    try:
        sequence = int(raw["local_sequence"])
    except (ValueError, TypeError) as exc:
        raise InvalidEvent("local_sequence must be an integer") from exc
    if sequence <= 0:
        raise InvalidEvent("local_sequence must be positive")
    if not isinstance(raw["payload"], dict):
        raise InvalidEvent("payload must be an object")
    try:
        schema_version = int(raw["schema_version"])
    except (TypeError, ValueError) as exc:
        raise InvalidEvent("schema_version must be an integer") from exc
    if schema_version != 1:
        raise InvalidEvent(f"unsupported schema_version {schema_version}")
    try:
        occurred_at = datetime.fromisoformat(str(raw["occurred_at"]))
    except ValueError as exc:
        raise InvalidEvent("occurred_at must be ISO-8601") from exc
    if occurred_at.tzinfo is None:
        raise InvalidEvent("occurred_at must be timezone-aware")
    for key in ("event_type", "aggregate_type", "aggregate_id"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise InvalidEvent(f"{key} must be a non-empty string")
    return {
        "event_id": event_id,
        "local_sequence": sequence,
        "event_type": raw["event_type"],
        "aggregate_type": raw["aggregate_type"],
        "aggregate_id": raw["aggregate_id"],
        "schema_version": 1,
        "occurred_at": occurred_at,
        "payload": raw["payload"],
    }


@transaction.atomic
def ingest_batch(edge: EdgeNode, raw_events: list[dict]) -> dict:
    require_cloud()
    if not isinstance(raw_events, list):
        raise InvalidEvent("events must be a list")
    if len(raw_events) > MAX_BATCH:
        raise InvalidEvent(f"batch too large (max {MAX_BATCH})")

    edge = EdgeNode.objects.select_for_update().get(pk=edge.pk)
    accepted: list[str] = []
    duplicates: list[str] = []
    rejected: list[dict] = []
    watermark = edge.last_acked_sequence

    for raw in raw_events:
        try:
            event = _parse_event(raw)
        except InvalidEvent as exc:
            rejected.append({"event_id": str(raw.get("event_id", "")), "reason": str(exc)})
            continue

        # Same log position with a different id means a broken producer; refuse it
        # rather than silently accepting two facts for one slot.
        if SyncEvent.objects.filter(edge=edge, local_sequence=event["local_sequence"]).exists():
            existing = SyncEvent.objects.get(edge=edge, local_sequence=event["local_sequence"])
            if existing.event_id == event["event_id"]:
                duplicates.append(str(event["event_id"]))
            else:
                rejected.append(
                    {"event_id": str(event["event_id"]), "reason": "sequence already used"}
                )
            continue

        # Per-aggregate causal order. Gaps are allowed (rolled-back transactions),
        # regression is not.
        last = (
            SyncEvent.objects.filter(
                edge=edge,
                aggregate_type=event["aggregate_type"],
                aggregate_id=event["aggregate_id"],
                status=SyncEventStatus.APPLIED,
            )
            .order_by("-local_sequence")
            .values_list("local_sequence", flat=True)
            .first()
        )
        if last is not None and event["local_sequence"] < last:
            rejected.append(
                {"event_id": str(event["event_id"]), "reason": "older than applied event"}
            )
            continue

        try:
            with transaction.atomic():
                record = SyncEvent.objects.create(edge=edge, **event)
        except IntegrityError:
            # Concurrent retry of the same batch.
            if SyncEvent.objects.filter(edge=edge, event_id=event["event_id"]).exists():
                duplicates.append(str(event["event_id"]))
                continue
            raise

        try:
            apply_event(record)
        except Exception as exc:  # DB/transport/projection bug -> edge must retry
            logger.exception("projection failed for %s", event["event_id"])
            raise RuntimeError(f"projection failed for {event['event_id']}: {exc}") from exc

        record.applied_at = timezone.now()
        record.save(update_fields=["applied_at"])
        accepted.append(str(event["event_id"]))
        if event["local_sequence"] > watermark:
            watermark = event["local_sequence"]

    edge.last_sync_at = timezone.now()
    edge.last_seen_at = timezone.now()
    edge.last_acked_sequence = watermark
    edge.save(update_fields=["last_sync_at", "last_seen_at", "last_acked_sequence", "updated_at"])

    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": rejected,
        "watermark": watermark,
    }

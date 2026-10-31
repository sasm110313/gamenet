from __future__ import annotations

import uuid
from datetime import datetime

from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.synchronization.models import EdgeNode, EdgeStatus


def apply_device_telemetry(edge: EdgeNode, devices: list[dict], *, now: datetime | None = None) -> int:
    """Presence telemetry is not financial: it is applied with last-writer-wins on
    liveness fields only. Durable facts still travel through the outbox."""
    now = now or timezone.now()
    present: list[uuid.UUID] = []
    updated = 0
    for item in devices:
        try:
            device_id = uuid.UUID(str(item.get("device_id")))
        except (ValueError, TypeError):
            continue
        present.append(device_id)
        updated += ClientDevice.objects.filter(id=device_id, edge_id=edge.id).update(
            name=str(item.get("name", ""))[:80] or "unnamed",
            status=item.get("status", ClientStatus.OFFLINE),
            last_heartbeat_at=now,
            application_version=str(item.get("application_version", ""))[:40],
        )
    ClientDevice.objects.filter(edge_id=edge.id, is_replica=True).exclude(
        id__in=present
    ).exclude(status=ClientStatus.OFFLINE).update(status=ClientStatus.OFFLINE)
    return updated


def mark_edge_seen(edge: EdgeNode, *, online: bool = True, now: datetime | None = None) -> None:
    now = now or timezone.now()
    edge.last_seen_at = now
    edge.last_heartbeat_at = now
    if online and edge.status != EdgeStatus.REVOKED:
        edge.status = EdgeStatus.ONLINE
    edge.save(update_fields=["last_seen_at", "last_heartbeat_at", "status", "updated_at"])

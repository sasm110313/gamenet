from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.clients.models import ClientDevice
from apps.core.roles import require_edge
from apps.synchronization.edge_credentials import ensure_identity, is_registered
from apps.synchronization.models import OutboxEvent
from apps.synchronization.outbox import pending_counts


class Command(BaseCommand):
    help = "Print the edge's identity, sync counters and device states as JSON."

    def handle(self, *args, **options):
        require_edge()
        identity = ensure_identity()
        payload = {
            "edge_id": str(identity.edge_id),
            "registered": is_registered(),
            "status": identity.status,
            "config_version": identity.config_version,
            "last_acked_sequence": identity.last_acked_sequence,
            "last_sync_at": identity.last_sync_at.isoformat() if identity.last_sync_at else None,
            "last_heartbeat_at": identity.last_heartbeat_at.isoformat() if identity.last_heartbeat_at else None,
            "outbox": pending_counts(),
            "oldest_pending": OutboxEvent.objects.filter(status="PENDING")
            .order_by("local_sequence")
            .values_list("local_sequence", flat=True)
            .first(),
            "devices": [
                {
                    "device_id": str(d.id),
                    "name": d.name,
                    "status": d.status,
                    "last_heartbeat_at": d.last_heartbeat_at.isoformat() if d.last_heartbeat_at else None,
                    "is_active": d.is_active,
                }
                for d in ClientDevice.objects.order_by("name")
            ],
        }
        self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))

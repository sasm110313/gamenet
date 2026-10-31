"""Cloud projections of edge events.

A handler's job is to make the cloud read model reflect a fact that already
happened on the edge. Handlers must be idempotent (the same event can be delivered
twice only via the duplicate path, but projections are still written defensively).
"""

from __future__ import annotations

import logging
from typing import Callable

from django.db import transaction
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import CommandStatus, RemoteCommand
from apps.core.roles import require_cloud
from apps.synchronization.models import EdgeNode, EdgeStatus, SyncEvent

logger = logging.getLogger("gamenet.handlers")

Handler = Callable[[SyncEvent], None]
HANDLERS: dict[str, Handler] = {}


def handles(event_type: str):
    def decorator(fn: Handler) -> Handler:
        HANDLERS[event_type] = fn
        return fn

    return decorator


def apply_event(event: SyncEvent) -> None:
    require_cloud()
    handler = HANDLERS.get(event.event_type)
    if handler is None:
        raise ValueError(f"no handler for event type {event.event_type!r}")
    with transaction.atomic():
        handler(event)


@handles("device.registered")
def device_registered(event: SyncEvent) -> None:
    p = event.payload
    ClientDevice.objects.update_or_create(
        id=p["device_id"],
        defaults={
            "edge_id": event.edge_id,
            "name": p.get("name", "unnamed"),
            "hostname": p.get("hostname", ""),
            "operating_system": p.get("operating_system", ""),
            "application_version": p.get("application_version", ""),
            "status": p.get("status", ClientStatus.OFFLINE),
            "last_heartbeat_at": event.occurred_at,
            "is_active": p.get("is_active", True),
            "is_replica": True,
            "registered_at": p.get("registered_at") or event.occurred_at,
        },
    )


@handles("device.status_changed")
def device_status_changed(event: SyncEvent) -> None:
    p = event.payload
    ClientDevice.objects.filter(id=p["device_id"]).update(
        status=p["status"],
        last_heartbeat_at=p.get("last_heartbeat_at") or event.occurred_at,
        application_version=p.get("application_version", ""),
        updated_at=timezone.now(),
    )


@handles("device.deactivated")
def device_deactivated(event: SyncEvent) -> None:
    ClientDevice.objects.filter(id=event.payload["device_id"]).update(
        is_active=False, status=ClientStatus.OFFLINE, updated_at=timezone.now()
    )


@handles("device.command_result")
def device_command_result(event: SyncEvent) -> None:
    """Device-level commands are edge-authoritative; the cloud only logs the fact
    in the event stream (queryable for support). Nothing to project here."""


@handles("command.result")
def command_result(event: SyncEvent) -> None:
    p = event.payload
    command = RemoteCommand.objects.filter(id=p.get("command_id")).first()
    if command is None:
        logger.warning("command.result for unknown command %s", p.get("command_id"))
        return
    status = p.get("status", "ACKNOWLEDGED")
    if status == "forwarded":
        command.status = CommandStatus.SENT
        command.result = p.get("result")
        command.save(update_fields=["status", "result"])
        return
    command.status = {
        "succeeded": CommandStatus.ACKNOWLEDGED,
        "failed": CommandStatus.REJECTED,
        "rejected": CommandStatus.REJECTED,
        "expired": CommandStatus.EXPIRED,
    }.get(status, CommandStatus.ACKNOWLEDGED)
    command.result = p.get("result")
    command.error = p.get("error", "")
    command.acknowledged_at = event.occurred_at
    command.save(update_fields=["status", "result", "error", "acknowledged_at"])


@handles("config.applied")
def config_applied(event: SyncEvent) -> None:
    EdgeNode.objects.filter(pk=event.edge_id).update(config_version=event.payload["version"])


@handles("edge.test")
def edge_test(event: SyncEvent) -> None:
    logger.info("edge.test event from %s: %s", event.edge_id, event.payload)

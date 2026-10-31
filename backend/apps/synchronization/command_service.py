"""Remote command lifecycle: cloud issues, edge verifies and executes once."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import (
    CommandStatus,
    DeviceCommand,
    DeviceCommandStatus,
    InboundCommandStatus,
    InboundRemoteCommand,
    RemoteCommand,
)
from apps.core.roles import require_cloud, require_edge
from apps.core.security import canonical_json
from apps.synchronization.crypto import sign_command, verify_command
from apps.synchronization.events import emit
from apps.synchronization.models import EdgeIdentity, EdgeNode

logger = logging.getLogger("gamenet.commands")

DEVICE_COMMAND_TYPES = {"client.lock", "client.unlock", "client.ping", "client.restart"}
EDGE_COMMAND_TYPES = {"edge.ping", "edge.sync_now", "edge.config_refresh", "edge.test_event"}


def edge_group(edge_id) -> str:
    return f"edge_{uuid.UUID(str(edge_id)).hex}"


def device_group(device_id) -> str:
    return f"device_{uuid.UUID(str(device_id)).hex}"


# ---------------------------------------------------------------------------
# Cloud side
# ---------------------------------------------------------------------------
def issue_command(
    edge: EdgeNode,
    command_type: str,
    payload: dict[str, Any] | None = None,
    *,
    ttl_seconds: int | None = None,
    actor=None,
    push: bool = True,
) -> RemoteCommand:
    require_cloud()
    if command_type not in DEVICE_COMMAND_TYPES | EDGE_COMMAND_TYPES:
        raise ValueError(f"unsupported command type {command_type!r}")

    now = timezone.now()
    ttl = ttl_seconds or settings.DEVICE_COMMAND_TTL_SECONDS
    command = RemoteCommand(
        edge=edge,
        command_type=command_type,
        payload=payload or {},
        issued_at=now,
        expires_at=now + timedelta(seconds=ttl),
        nonce=secrets.token_hex(16),
        created_by=actor if getattr(actor, "pk", None) else None,
        signature="",
    )
    envelope = command.envelope()
    command.signature = sign_command(edge.command_private_key_enc, canonical_json(envelope).encode())
    command.save()

    if push:
        try:
            async_to_sync(get_channel_layer().group_send)(
                edge_group(edge.id),
                {
                    "type": "edge.command",
                    "command": {**envelope, "signature": command.signature},
                },
            )
        except Exception:  # channel layer down must not lose the command
            logger.warning("could not push command %s; edge will pull it", command.id, exc_info=True)
    return command


# ---------------------------------------------------------------------------
# Edge side: receive / verify / execute
# ---------------------------------------------------------------------------
def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


@transaction.atomic
def receive_command(envelope: dict) -> tuple[InboundRemoteCommand, bool]:
    """Store a verified command exactly once. Returns (row, is_new).

    The unique command_id is the guard: a duplicate delivery returns the stored
    row without re-executing, even if the envelope is now expired.
    """
    require_edge()
    identity = EdgeIdentity.get_solo()

    try:
        command_id = uuid.UUID(str(envelope["command_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("invalid command_id") from exc

    existing = (
        InboundRemoteCommand.objects.select_for_update().filter(command_id=command_id).first()
    )
    if existing:
        return existing, False

    required = {
        "command_id",
        "edge_id",
        "command_type",
        "payload",
        "issued_at",
        "expires_at",
        "nonce",
        "signature",
    }
    missing = required - envelope.keys()
    if missing:
        raise ValueError(f"command envelope missing {sorted(missing)}")
    if str(envelope["edge_id"]) != str(identity.edge_id):
        raise ValueError("command targeted at a different edge")

    signed_fields = {k: envelope[k] for k in required if k != "signature"}
    if not verify_command(
        identity.command_public_key, canonical_json(signed_fields).encode(), envelope["signature"]
    ):
        raise ValueError("bad command signature")

    issued_at = _parse_dt(envelope["issued_at"])
    expires_at = _parse_dt(envelope["expires_at"])
    now = timezone.now()
    if issued_at > now + timedelta(seconds=settings.COMMAND_CLOCK_SKEW_SECONDS):
        raise ValueError("command issued in the future")
    if expires_at <= now:
        row = InboundRemoteCommand.objects.create(
            command_id=command_id,
            edge_id=identity.edge_id,
            command_type=envelope["command_type"],
            payload=envelope["payload"],
            issued_at=issued_at,
            expires_at=expires_at,
            signature=envelope["signature"],
            status=InboundCommandStatus.EXPIRED,
            reject_reason="expired before delivery",
        )
        return row, True

    row = InboundRemoteCommand.objects.create(
        command_id=command_id,
        edge_id=identity.edge_id,
        command_type=envelope["command_type"],
        payload=envelope["payload"],
        issued_at=issued_at,
        expires_at=expires_at,
        signature=envelope["signature"],
    )
    return row, True


def execute_command(command_id: uuid.UUID) -> dict[str, Any]:
    """Execute a stored RECEIVED command. Safe to call twice: the row is claimed
    with a row lock and moved to EXECUTING before any side effect, so a concurrent
    or duplicate call is a no-op."""
    require_edge()
    with transaction.atomic():
        row = (
            InboundRemoteCommand.objects.select_for_update()
            .filter(command_id=command_id, status=InboundCommandStatus.RECEIVED)
            .first()
        )
        if row is None:
            return {"status": "already_handled"}
        if row.expires_at <= timezone.now():
            row.status = InboundCommandStatus.EXPIRED
            row.reject_reason = "expired before execution"
            row.save(update_fields=["status", "reject_reason"])
            return {"status": "expired"}
        row.status = InboundCommandStatus.EXECUTING
        row.save(update_fields=["status"])
        command_type = row.command_type
        payload = row.payload
        row_token = str(row.command_id)

    status = "succeeded"
    result: dict[str, Any]
    error = ""
    try:
        result, status = _dispatch(command_type, payload, origin=row_token)
    except Exception as exc:
        logger.exception("command %s failed", row_token)
        status, result, error = "failed", {}, str(exc)

    with transaction.atomic():
        row = InboundRemoteCommand.objects.select_for_update().get(command_id=command_id)
        row.status = {
            "succeeded": InboundCommandStatus.SUCCEEDED,
            "forwarded": InboundCommandStatus.SUCCEEDED,
            "failed": InboundCommandStatus.FAILED,
        }[status]
        row.result = result
        row.reject_reason = error[:255]
        row.executed_at = timezone.now()
        row.save(update_fields=["status", "result", "reject_reason", "executed_at"])
        emit(
            "command.result",
            aggregate_type="remote_command",
            aggregate_id=str(command_id),
            payload={
                "command_id": str(command_id),
                "status": status,
                "result": result,
                "error": error,
            },
        )
    return {"status": status, "result": result, "error": error}


def _dispatch(command_type: str, payload: dict, *, origin: str) -> tuple[dict[str, Any], str]:
    identity = EdgeIdentity.get_solo()
    if command_type == "edge.ping":
        return (
            {"pong": True, "edge_id": str(identity.edge_id), "server_time": timezone.now().isoformat()},
            "succeeded",
        )
    if command_type == "edge.sync_now":
        return {"queued": True}, "succeeded"
    if command_type == "edge.config_refresh":
        return {"queued": True}, "succeeded"
    if command_type == "edge.test_event":
        with transaction.atomic():
            event = emit(
                "edge.test",
                aggregate_type="edge",
                aggregate_id=str(identity.edge_id),
                payload={"note": payload.get("note", "manual test"), "origin": "cloud_command"},
            )
        return {"event_id": str(event.event_id), "sequence": event.local_sequence}, "succeeded"

    if command_type in DEVICE_COMMAND_TYPES:
        device_id = payload.get("device_id")
        if not device_id:
            raise ValueError("device command requires payload.device_id")
        device = ClientDevice.objects.filter(id=device_id, is_active=True).first()
        if device is None:
            raise ValueError(f"unknown or inactive device {device_id}")
        if device.status == ClientStatus.MAINTENANCE and command_type != "client.restart":
            raise ValueError("device is in maintenance")
        with transaction.atomic():
            command = queue_device_command(
                device,
                command_type,
                {k: v for k, v in payload.items() if k != "device_id"},
                origin_remote_command_id=uuid.UUID(origin),
            )
        # Only "forwarded" until the client itself acknowledges execution; the
        # final command.result is emitted by acknowledge_device_command().
        return {"device_command_id": str(command.id), "queued": True}, "forwarded"

    raise ValueError(f"unsupported command type {command_type!r}")


def push_device_command(command_id) -> bool:
    require_edge()
    command = DeviceCommand.objects.filter(id=command_id).first()
    if command is None:
        return False
    channel_layer = get_channel_layer()
    try:
        async_to_sync(channel_layer.group_send)(
            device_group(command.client_id),
            {
                "type": "device.command",
                "command": {
                    "command_id": str(command.id),
                    "command_type": command.command_type,
                    "payload": command.payload,
                    "expires_at": command.expires_at.isoformat(),
                },
            },
        )
        return True
    except Exception:
        logger.warning("device %s offline; command %s stays pending", command.client_id, command.id)
        return False


@transaction.atomic
def acknowledge_device_command(
    device: ClientDevice, command_id: str, *, status: str, result: Any = None, error: str = ""
) -> DeviceCommand:
    require_edge()
    command = (
        DeviceCommand.objects.select_for_update()
        .filter(id=command_id, client=device)
        .first()
    )
    if command is None:
        raise ValueError("unknown command")
    if command.status == DeviceCommandStatus.ACKNOWLEDGED:
        return command
    command.status = (
        DeviceCommandStatus.ACKNOWLEDGED if status == "ok" else DeviceCommandStatus.FAILED
    )
    command.result = result
    command.error = error[:2000]
    command.acknowledged_at = timezone.now()
    command.save(update_fields=["status", "result", "error", "acknowledged_at"])

    if command.origin_remote_command_id:
        emit(
            "command.result",
            aggregate_type="remote_command",
            aggregate_id=str(command.origin_remote_command_id),
            payload={
                "command_id": str(command.origin_remote_command_id),
                "status": "succeeded" if status == "ok" else "failed",
                "result": result,
                "error": error,
            },
        )
    return command


def expire_stale_commands(now=None) -> int:
    require_edge()
    now = now or timezone.now()
    stale_devices = DeviceCommand.objects.filter(
        status__in=[DeviceCommandStatus.PENDING, DeviceCommandStatus.SENT], expires_at__lte=now
    )
    count = stale_devices.update(status=DeviceCommandStatus.EXPIRED)
    expired_remote = InboundRemoteCommand.objects.filter(
        status=InboundCommandStatus.RECEIVED, expires_at__lte=now
    )
    for row in expired_remote:
        row.status = InboundCommandStatus.EXPIRED
        row.reject_reason = "expired before execution"
        row.save(update_fields=["status", "reject_reason"])
        count += 1
    return count


@transaction.atomic
def queue_device_command(
    device: ClientDevice,
    command_type: str,
    payload: dict[str, Any] | None = None,
    *,
    actor=None,
    origin_remote_command_id=None,
    ttl_seconds: int | None = None,
) -> DeviceCommand:
    """Edge-admin path: create a device command and try to push it immediately.

    If the device is offline the row stays PENDING and is delivered on reconnect.
    """
    require_edge()
    command = DeviceCommand.objects.create(
        client=device,
        command_type=command_type,
        payload=payload or {},
        expires_at=timezone.now()
        + timedelta(seconds=ttl_seconds or settings.DEVICE_COMMAND_TTL_SECONDS),
        origin_remote_command_id=origin_remote_command_id,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    transaction.on_commit(lambda: push_device_command(command.id))
    return command

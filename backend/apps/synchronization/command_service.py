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
from django.db import IntegrityError, transaction
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
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.pricing.models import CustomerRate, Tariff
from apps.sessions.models import GamingSession
from apps.synchronization.crypto import sign_command, verify_command
from apps.synchronization.events import emit
from apps.synchronization.models import EdgeIdentity, EdgeNode

logger = logging.getLogger("gamenet.commands")

DEVICE_COMMAND_TYPES = {"client.lock", "client.unlock", "client.ping", "client.restart"}
CATALOG_COMMAND_TYPES = {
    "catalog.customer.upsert",
    "catalog.customer_rate.upsert",
    "catalog.customer_rate.deactivate",
    "catalog.group.upsert",
    "catalog.tariff.upsert",
}
SESSION_COMMAND_TYPES = {"session.start", "session.stop"}
WALLET_COMMAND_TYPES = {"wallet.deposit", "wallet.adjust"}
EDGE_COMMAND_TYPES = {
    "edge.ping",
    "edge.sync_now",
    "edge.config_refresh",
    "edge.test_event",
    "edge.create_client_code",
} | CATALOG_COMMAND_TYPES | SESSION_COMMAND_TYPES | WALLET_COMMAND_TYPES


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
    request_id=None,
    push: bool = True,
) -> RemoteCommand:
    require_cloud()
    if command_type not in DEVICE_COMMAND_TYPES | EDGE_COMMAND_TYPES:
        raise ValueError(f"unsupported command type {command_type!r}")

    if request_id is not None:
        existing = RemoteCommand.objects.filter(edge=edge, request_id=request_id).first()
        if existing is not None:
            return existing

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
        request_id=request_id,
        signature="",
    )
    envelope = command.envelope()
    command.signature = sign_command(edge.command_private_key_enc, canonical_json(envelope).encode())
    try:
        with transaction.atomic():
            command.save()
    except IntegrityError:
        if request_id is not None:
            return RemoteCommand.objects.get(edge=edge, request_id=request_id)
        raise

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
    """Execute a stored RECEIVED command exactly once.

    The whole claim -> dispatch -> status update -> result event runs in one
    transaction. If the process dies before commit, the command row stays
    RECEIVED and can be retried. If it commits, a replay sees a terminal status
    and does nothing.
    """
    require_edge()
    command_id = uuid.UUID(str(command_id))
    with transaction.atomic():
        row = (
            InboundRemoteCommand.objects.select_for_update()
            .filter(command_id=command_id)
            .first()
        )
        if row is None:
            return {"status": "unknown"}

        if row.status in {
            InboundCommandStatus.SUCCEEDED,
            InboundCommandStatus.FAILED,
            InboundCommandStatus.REJECTED,
            InboundCommandStatus.EXPIRED,
        }:
            return {"status": "already_handled"}

        if row.status == InboundCommandStatus.EXECUTING:
            # Older code committed EXECUTING before dispatch. We hold the row
            # lock now, so no live executor can exist; only reclaim after a
            # grace period to avoid racing a process that just crashed.
            if row.received_at > timezone.now() - timedelta(minutes=5):
                return {"status": "busy"}
            row.status = InboundCommandStatus.RECEIVED
            row.save(update_fields=["status"])

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

        try:
            # Roll back any partial dispatch effects before recording failure.
            # The outer transaction can then safely persist the terminal result.
            with transaction.atomic():
                result, status = _dispatch(command_type, payload, origin=row_token)
            error = ""
        except Exception as exc:
            logger.exception("command %s failed", row_token)
            status, result, error = "failed", {}, str(exc)

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


def _require(payload: dict, key: str):
    value = payload.get(key)
    if value in (None, ""):
        raise ValueError(f"payload.{key} is required")
    return value


def _require_int(payload: dict, key: str) -> int:
    value = _require(payload, key)
    if isinstance(value, bool):
        raise ValueError(f"payload.{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"payload.{key} must be an integer") from exc


def _base_revision(payload: dict) -> int:
    value = payload.get("base_revision")
    if value is None:
        raise ValueError("payload.base_revision is required")
    if isinstance(value, bool):
        raise ValueError("payload.base_revision must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload.base_revision must be an integer") from exc


def _check_revision(obj, base: int) -> None:
    if obj.revision != base:
        raise ValueError(
            f"stale revision: edge has {obj.revision}, command based on {base}"
        )


def _customer_result(customer: Customer) -> dict:
    return {
        "customer_id": str(customer.id),
        "revision": customer.revision,
        "is_active": customer.is_active,
    }


def _rate_result(rate: CustomerRate) -> dict:
    return {
        "customer_rate_id": str(rate.id),
        "customer_id": str(rate.customer_id),
        "name": rate.name,
        "hourly_rate": rate.hourly_rate,
        "is_default": rate.is_default,
        "is_active": rate.is_active,
        "revision": rate.revision,
    }


def _tariff_result(tariff: Tariff) -> dict:
    return {
        "tariff_id": str(tariff.id),
        "name": tariff.name,
        "hourly_rate": tariff.hourly_rate,
        "is_active": tariff.is_active,
        "revision": tariff.revision,
    }


def _group_result(group: CustomerGroup) -> dict:
    return {
        "group_id": str(group.id),
        "name": group.name,
        "tariff_id": str(group.tariff_id) if group.tariff_id else None,
        "is_active": group.is_active,
        "revision": group.revision,
    }


def _session_result(session: GamingSession) -> dict:
    return {
        "session_id": str(session.id),
        "customer_id": str(session.customer_id),
        "device_id": str(session.device_id),
        "status": session.status,
        "hourly_rate": session.hourly_rate,
        "rate_name": session.tariff_name,
        "customer_rate_id": (
            str(session.customer_rate_id) if session.customer_rate_id else None
        ),
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "elapsed_seconds": session.elapsed_seconds,
        "cost": session.cost,
    }


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

    if command_type == "edge.create_client_code":
        from apps.devices.services import create_registration_code
        label = str(payload.get("label") or "").strip()
        reg = create_registration_code(label=label)
        emit(
            "device.code_created",
            aggregate_type="registration_code",
            aggregate_id=str(reg.id),
            payload={
                "code": reg.code,
                "label": reg.label,
                "expires_at": reg.expires_at.isoformat(),
            },
        )
        return {"code": reg.code, "label": reg.label, "expires_at": reg.expires_at.isoformat()}, "succeeded"

    if command_type == "catalog.customer.upsert":
        from apps.customers.services import create_customer, update_customer

        customer_id = _require(payload, "customer_id")
        base = _base_revision(payload)
        existing = Customer.objects.filter(id=customer_id).first()
        group = None
        if payload.get("group_id"):
            group = CustomerGroup.objects.filter(id=payload["group_id"]).first()
            if group is None:
                group_name = payload.get("group_name")
                if group_name:
                    group = CustomerGroup.objects.filter(edge_id=identity.edge_id, name=group_name).first()
                if group is None:
                    group = CustomerGroup.objects.filter(edge_id=identity.edge_id).first()
            elif group.edge_id != identity.edge_id:
                raise ValueError("group belongs to another edge")

        credit_limit = (
            _require_int(payload, "credit_limit")
            if payload.get("credit_limit") is not None
            else None
        )
        if existing is None:
            if base != 0:
                raise ValueError("customer does not exist on this edge")
            customer = create_customer(
                customer_id=customer_id,
                full_name=_require(payload, "full_name"),
                username=payload.get("username", ""),
                password=payload.get("password", ""),
                phone=payload.get("phone", ""),
                group=group,
                credit_limit=credit_limit,
                notes=payload.get("notes", ""),
            )
            return {**_customer_result(customer), "created": True}, "succeeded"

        if existing.edge_id != identity.edge_id:
            raise ValueError("customer belongs to another edge")
        if base == 0:
            return {**_customer_result(existing), "created": False}, "succeeded"
        _check_revision(existing, base)
        customer = update_customer(
            existing,
            full_name=_require(payload, "full_name"),
            username=payload.get("username"),
            password=payload.get("password"),
            phone=payload.get("phone", ""),
            group=group,
            clear_group=not bool(payload.get("group_id")),
            credit_limit=credit_limit,
            notes=payload.get("notes", ""),
            is_active=bool(payload.get("is_active", True)),
            expected_revision=base,
        )
        return {**_customer_result(customer), "created": False}, "succeeded"

    if command_type == "catalog.customer_rate.upsert":
        from apps.pricing.services import create_customer_rate, update_customer_rate

        rate_id = _require(payload, "customer_rate_id")
        customer_id = _require(payload, "customer_id")
        customer = Customer.objects.filter(id=customer_id).first()
        if customer is None:
            raise ValueError(f"unknown customer {customer_id}")
        if customer.edge_id != identity.edge_id:
            raise ValueError("customer belongs to another edge")
        base = _base_revision(payload)
        existing = CustomerRate.objects.filter(id=rate_id).first()
        is_default = payload.get("is_default")
        is_active = payload.get("is_active")

        if existing is None:
            if base != 0:
                raise ValueError("customer rate does not exist on this edge")
            rate = create_customer_rate(
                customer=customer,
                name=_require(payload, "name"),
                hourly_rate=_require_int(payload, "hourly_rate"),
                is_default=bool(is_default) if is_default is not None else False,
                rate_id=rate_id,
            )
            return {**_rate_result(rate), "created": True}, "succeeded"

        if existing.customer_id != customer.id:
            raise ValueError("customer rate belongs to another customer")
        if base == 0:
            return {**_rate_result(existing), "created": False}, "succeeded"
        _check_revision(existing, base)
        rate = update_customer_rate(
            existing,
            name=_require(payload, "name"),
            hourly_rate=_require_int(payload, "hourly_rate"),
            is_active=None if is_active is None else bool(is_active),
            is_default=None if is_default is None else bool(is_default),
            expected_revision=base,
        )
        return {**_rate_result(rate), "created": False}, "succeeded"

    if command_type == "catalog.customer_rate.deactivate":
        from apps.pricing.services import deactivate_customer_rate

        rate = CustomerRate.objects.filter(
            id=_require(payload, "customer_rate_id")
        ).first()
        if rate is None:
            raise ValueError("customer rate does not exist on this edge")
        if rate.edge_id != identity.edge_id:
            raise ValueError("customer rate belongs to another edge")
        base = _base_revision(payload)
        _check_revision(rate, base)
        rate = deactivate_customer_rate(rate, expected_revision=base)
        return _rate_result(rate), "succeeded"

    if command_type == "catalog.group.upsert":
        from apps.customer_groups.services import create_group, update_group

        group_id = _require(payload, "group_id")
        base = _base_revision(payload)
        tariff = None
        if payload.get("tariff_id"):
            tariff = Tariff.objects.filter(id=payload["tariff_id"]).first()
            if tariff is None:
                raise ValueError(f"unknown tariff {payload['tariff_id']}")
            if tariff.edge_id != identity.edge_id:
                raise ValueError("tariff belongs to another edge")
        existing = CustomerGroup.objects.filter(id=group_id).first()
        if existing is None:
            if base != 0:
                raise ValueError("group does not exist on this edge")
            if tariff is None:
                raise ValueError("payload.tariff_id is required")
            group = create_group(
                name=_require(payload, "name"), tariff=tariff, group_id=group_id
            )
            return {**_group_result(group), "created": True}, "succeeded"

        if existing.edge_id != identity.edge_id:
            raise ValueError("group belongs to another edge")
        if base == 0:
            return {**_group_result(existing), "created": False}, "succeeded"
        _check_revision(existing, base)
        group = update_group(
            existing,
            name=_require(payload, "name"),
            tariff=tariff,
            is_active=bool(payload.get("is_active", True)),
            expected_revision=base,
        )
        return {**_group_result(group), "created": False}, "succeeded"

    if command_type == "catalog.tariff.upsert":
        from apps.pricing.services import create_tariff, update_tariff

        tariff_id = _require(payload, "tariff_id")
        base = _base_revision(payload)
        existing = Tariff.objects.filter(id=tariff_id).first()
        if existing is None:
            if base != 0:
                raise ValueError("tariff does not exist on this edge")
            tariff = create_tariff(
                tariff_id=tariff_id,
                name=_require(payload, "name"),
                hourly_rate=_require_int(payload, "hourly_rate"),
            )
            return {**_tariff_result(tariff), "created": True}, "succeeded"

        if existing.edge_id != identity.edge_id:
            raise ValueError("tariff belongs to another edge")
        if base == 0:
            return {**_tariff_result(existing), "created": False}, "succeeded"
        _check_revision(existing, base)
        tariff = update_tariff(
            existing,
            name=_require(payload, "name"),
            hourly_rate=_require_int(payload, "hourly_rate"),
            is_active=bool(payload.get("is_active", True)),
            expected_revision=base,
        )
        return {**_tariff_result(tariff), "created": False}, "succeeded"

    if command_type == "session.start":
        from apps.sessions.services import start_session

        session_id = _require(payload, "session_id")
        existing = GamingSession.objects.filter(id=session_id).first()
        if existing is not None:
            return _session_result(existing), "succeeded"
        customer = Customer.objects.filter(
            id=_require(payload, "customer_id")
        ).first()
        device = ClientDevice.objects.filter(
            id=_require(payload, "device_id"), is_active=True
        ).first()
        if customer is None:
            raise ValueError("unknown customer")
        if device is None:
            raise ValueError("unknown or inactive device")
        if customer.edge_id != identity.edge_id or device.edge_id != identity.edge_id:
            raise ValueError("customer or device belongs to another edge")
        rate = None
        if payload.get("customer_rate_id"):
            rate = CustomerRate.objects.filter(
                id=payload["customer_rate_id"]
            ).first()
            if rate is None:
                raise ValueError("unknown customer rate")
            if rate.customer_id != customer.id:
                raise ValueError("customer rate belongs to another customer")
        session = start_session(
            customer, device, customer_rate=rate, session_id=session_id
        )
        return _session_result(session), "succeeded"

    if command_type == "session.stop":
        from apps.sessions.services import stop_session

        session = GamingSession.objects.filter(
            id=_require(payload, "session_id")
        ).first()
        if session is None:
            raise ValueError("unknown session")
        if session.edge_id != identity.edge_id:
            raise ValueError("session belongs to another edge")
        ended, entry = stop_session(
            session, reason=str(payload.get("reason") or "پایان از ابر")[:120]
        )
        return {
            **_session_result(ended),
            "ledger_entry_id": str(entry.id) if entry is not None else None,
        }, "succeeded"

    if command_type in WALLET_COMMAND_TYPES:
        from apps.wallets.services import adjust, deposit

        customer = Customer.objects.filter(
            id=_require(payload, "customer_id")
        ).first()
        if customer is None:
            raise ValueError("unknown customer")
        if customer.edge_id != identity.edge_id:
            raise ValueError("customer belongs to another edge")
        amount = _require_int(payload, "amount")
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise ValueError("payload.reason is required")
        requested_by = str(payload.get("requested_by") or "cloud").strip()[:80]
        note = f"{reason} (از ابر: {requested_by})"[:255]
        command_uuid = uuid.UUID(origin)
        if command_type == "wallet.deposit":
            entry = deposit(
                customer,
                amount,
                note=note,
                source_command_id=command_uuid,
            )
        else:
            entry = adjust(
                customer,
                amount,
                note=note,
                source_command_id=command_uuid,
            )
        return {
            "entry_id": str(entry.id),
            "customer_id": str(customer.id),
            "entry_type": entry.entry_type,
            "amount": entry.amount,
            "balance_after": entry.balance_after,
        }, "succeeded"

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

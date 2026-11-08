"""Cloud projections of edge events.

A handler's job is to make the cloud read model reflect a fact that already
happened on the edge. Handlers must be idempotent (the same event can be delivered
twice only via the duplicate path, but projections are still written defensively).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from django.db import transaction
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import CommandStatus, RemoteCommand
from apps.core.roles import require_cloud
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.ledger.models import LedgerEntry
from apps.pricing.models import CustomerRate, Tariff
from apps.sessions.models import GamingSession, SessionStatus
from apps.synchronization.models import EdgeNode, EdgeStatus, SyncEvent
from apps.wallets.models import Wallet

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


def _owned(model, pk, edge_id, label: str):
    """Return the row only when it belongs to the event's edge.

    The same UUID can legitimately exist on two independent edges (cloned disk
    images, restored installs). A projection must never let one edge overwrite
    another edge's row; that is treated as a rejected event.
    """
    obj = model.objects.filter(pk=pk).first()
    if obj is not None and obj.edge_id != edge_id:
        raise ValueError(f"{label} {pk} belongs to another edge")
    return obj


@handles("device.registered")
def device_registered(event: SyncEvent) -> None:
    p = event.payload
    _owned(ClientDevice, p["device_id"], event.edge_id, "device")
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
    ClientDevice.objects.filter(id=p["device_id"], edge_id=event.edge_id).update(
        status=p["status"],
        last_heartbeat_at=p.get("last_heartbeat_at") or event.occurred_at,
        application_version=p.get("application_version", ""),
        updated_at=timezone.now(),
    )


@handles("device.deactivated")
def device_deactivated(event: SyncEvent) -> None:
    ClientDevice.objects.filter(
        id=event.payload["device_id"], edge_id=event.edge_id
    ).update(
        is_active=False, status=ClientStatus.OFFLINE, updated_at=timezone.now()
    )


@handles("device.command_result")
def device_command_result(event: SyncEvent) -> None:
    """Device-level commands are edge-authoritative; the cloud only logs the fact
    in the event stream (queryable for support). Nothing to project here."""


@handles("device.code_created")
def device_code_created(event: SyncEvent) -> None:
    from apps.devices.models import RegistrationCode
    p = event.payload
    RegistrationCode.objects.get_or_create(
        id=event.aggregate_id,
        defaults={
            "code": p["code"],
            "label": p.get("label", ""),
            "expires_at": p["expires_at"],
        },
    )


@handles("command.result")
def command_result(event: SyncEvent) -> None:
    p = event.payload
    command = _owned(RemoteCommand, p.get("command_id"), event.edge_id, "command")
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


# ---------------------------------------------------------------------------
# Phase 1 projections
# ---------------------------------------------------------------------------
def _iso(value, fallback):
    if not value:
        return fallback
    return datetime.fromisoformat(str(value))


@handles("tariff.created")
@handles("tariff.updated")
def tariff_upsert(event: SyncEvent) -> None:
    p = event.payload
    _owned(Tariff, p["tariff_id"], event.edge_id, "tariff")
    Tariff.objects.update_or_create(
        id=p["tariff_id"],
        defaults={
            "edge_id": event.edge_id,
            "name": p["name"],
            "hourly_rate": int(p["hourly_rate"]),
            "is_active": bool(p.get("is_active", True)),
            "revision": int(p.get("revision", 1)),
            "is_replica": True,
        },
    )


@handles("customer_group.created")
@handles("customer_group.updated")
def customer_group_upsert(event: SyncEvent) -> None:
    p = event.payload
    _owned(CustomerGroup, p["group_id"], event.edge_id, "group")
    tariff = None
    if p.get("tariff_id"):
        tariff = _owned(Tariff, p["tariff_id"], event.edge_id, "tariff")
        if tariff is None:
            raise ValueError(f"group {p['group_id']} references unknown tariff {p['tariff_id']}")
    CustomerGroup.objects.update_or_create(
        id=p["group_id"],
        defaults={
            "edge_id": event.edge_id,
            "name": p["name"],
            "tariff": tariff,
            "is_active": bool(p.get("is_active", True)),
            "revision": int(p.get("revision", 1)),
            "is_replica": True,
        },
    )


@handles("customer.created")
@handles("customer.updated")
def customer_upsert(event: SyncEvent) -> None:
    p = event.payload
    _owned(Customer, p["customer_id"], event.edge_id, "customer")
    group = None
    if p.get("group_id"):
        group = _owned(CustomerGroup, p["group_id"], event.edge_id, "group")
        if group is None:
            raise ValueError(f"customer {p['customer_id']} references unknown group {p['group_id']}")
    customer, _ = Customer.objects.update_or_create(
        id=p["customer_id"],
        defaults={
            "edge_id": event.edge_id,
            "full_name": p["full_name"],
            "username": p.get("username", ""),
            "phone": p.get("phone", ""),
            "group": group,
            "credit_limit": int(p.get("credit_limit", 0)),
            "is_active": bool(p.get("is_active", True)),
            "notes": p.get("notes", ""),
            "revision": int(p.get("revision", 1)),
            "is_replica": True,
        },
    )
    # Never overwrite an existing replica balance from a customer event: the
    # ledger stream is the only authoritative source for money.
    Wallet.objects.get_or_create(
        customer=customer,
        defaults={"balance": int(p.get("wallet_balance", 0)), "is_replica": True},
    )


@handles("customer_rate.created")
@handles("customer_rate.updated")
def customer_rate_upsert(event: SyncEvent) -> None:
    p = event.payload
    customer = _owned(Customer, p["customer_id"], event.edge_id, "customer")
    _owned(CustomerRate, p["customer_rate_id"], event.edge_id, "customer rate")
    if customer is None:
        raise ValueError(
            f"customer_rate {p['customer_rate_id']} references unknown customer "
            f"{p['customer_id']}"
        )
    is_active = bool(p.get("is_active", True))
    is_default = bool(p.get("is_default", False)) and is_active
    if is_default:
        # Clear the old default first so the partial unique constraint holds no
        # matter which order the created/updated events arrive in.
        CustomerRate.objects.filter(customer=customer, is_default=True).exclude(
            id=p["customer_rate_id"]
        ).update(is_default=False)
    CustomerRate.objects.update_or_create(
        id=p["customer_rate_id"],
        defaults={
            "edge_id": event.edge_id,
            "customer": customer,
            "name": p["name"],
            "hourly_rate": int(p["hourly_rate"]),
            "is_default": is_default,
            "is_active": is_active,
            "revision": int(p.get("revision", 1)),
            "is_replica": True,
        },
    )


@handles("ledger.entry_created")
def ledger_entry_created(event: SyncEvent) -> None:
    p = event.payload
    _owned(LedgerEntry, p["entry_id"], event.edge_id, "ledger entry")
    customer = _owned(Customer, p["customer_id"], event.edge_id, "customer")
    if customer is None:
        raise ValueError(f"ledger entry for unknown customer {p['customer_id']}")
    session = None
    if p.get("session_id"):
        session = _owned(GamingSession, p["session_id"], event.edge_id, "session")
        if session is None:
            raise ValueError(f"ledger entry references unknown session {p['session_id']}")
    reverses = None
    if p.get("reverses_id"):
        reverses = _owned(LedgerEntry, p["reverses_id"], event.edge_id, "ledger entry")
        if reverses is None:
            raise ValueError(f"ledger entry reverses unknown entry {p['reverses_id']}")

    entry, created = LedgerEntry.objects.get_or_create(
        id=p["entry_id"],
        defaults={
            "edge_id": event.edge_id,
            "customer": customer,
            "session": session,
            "entry_type": p["entry_type"],
            "amount": int(p["amount"]),
            "balance_after": int(p["balance_after"]),
            "reverses": reverses,
            "note": p.get("note", ""),
            "source_command_id": p.get("source_command_id"),
            "is_replica": True,
            "created_at": _iso(p.get("created_at"), event.occurred_at),
        },
    )
    if not created:
        return
    Wallet.objects.update_or_create(
        customer=customer,
        defaults={"balance": entry.balance_after, "is_replica": True},
    )


@handles("session.started")
def session_started(event: SyncEvent) -> None:
    p = event.payload
    _owned(GamingSession, p["session_id"], event.edge_id, "session")
    customer = _owned(Customer, p["customer_id"], event.edge_id, "customer")
    device = _owned(ClientDevice, p["device_id"], event.edge_id, "device")
    if customer is None or device is None:
        raise ValueError(
            f"session {p['session_id']} references unknown customer/device"
        )
    tariff = None
    if p.get("tariff_id"):
        tariff = _owned(Tariff, p["tariff_id"], event.edge_id, "tariff")
        if tariff is None:
            raise ValueError(f"session {p['session_id']} references unknown tariff {p['tariff_id']}")
    customer_rate = None
    if p.get("customer_rate_id"):
        customer_rate = _owned(CustomerRate, p["customer_rate_id"], event.edge_id, "customer rate")
        if customer_rate is None:
            raise ValueError(
                f"session {p['session_id']} references unknown customer_rate "
                f"{p['customer_rate_id']}"
            )
        if customer_rate.customer_id != customer.id:
            raise ValueError(
                f"session {p['session_id']} rate belongs to another customer"
            )
    GamingSession.objects.get_or_create(
        id=p["session_id"],
        defaults={
            "edge_id": event.edge_id,
            "customer": customer,
            "device": device,
            "status": SessionStatus.ACTIVE,
            "tariff": tariff,
            "customer_rate": customer_rate,
            "tariff_name": p.get("tariff_name", ""),
            "hourly_rate": int(p["hourly_rate"]),
            "started_at": _iso(p.get("started_at"), event.occurred_at),
            "is_replica": True,
        },
    )


@handles("session.ended")
def session_ended(event: SyncEvent) -> None:
    p = event.payload
    session = _owned(GamingSession, p["session_id"], event.edge_id, "session")
    if session is None:
        raise ValueError(f"session.ended for unknown session {p['session_id']}")
    session.status = p.get("status", SessionStatus.COMPLETED)
    session.ended_at = _iso(p.get("ended_at"), event.occurred_at)
    session.elapsed_seconds = int(p.get("elapsed_seconds", 0))
    session.cost = int(p.get("cost", 0))
    session.end_reason = p.get("end_reason", "")
    session.is_replica = True
    session.save(
        update_fields=[
            "status", "ended_at", "elapsed_seconds", "cost", "end_reason",
            "is_replica", "updated_at",
        ]
    )

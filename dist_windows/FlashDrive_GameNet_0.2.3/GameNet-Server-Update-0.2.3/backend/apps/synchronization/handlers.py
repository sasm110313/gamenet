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

from apps.clients.models import (
    ClientDevice,
    ClientStatus,
    ConnectionStatus,
    HealthStatus,
    KioskStatus,
    OccupancyStatus,
    PowerStatus,
)
from apps.commands.models import CommandStatus, RemoteCommand
from apps.core.roles import require_cloud
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.ledger.models import LedgerEntry, generate_tracking_code
from apps.pricing.models import CustomerRate, Tariff
from apps.sessions.models import (
    BillingMode,
    DisconnectPolicy,
    GamingSession,
    SessionStatus,
)
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
    defaults = {
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
    }
    if p.get("connection_status") in ConnectionStatus.values:
        defaults["connection_status"] = p["connection_status"]
    if p.get("power_status") in PowerStatus.values:
        defaults["power_status"] = p["power_status"]
    if p.get("kiosk_status") in KioskStatus.values:
        defaults["kiosk_status"] = p["kiosk_status"]
    if p.get("occupancy_status") in OccupancyStatus.values:
        defaults["occupancy_status"] = p["occupancy_status"]
    if p.get("health_status") in HealthStatus.values:
        defaults["health_status"] = p["health_status"]
    if "health_message" in p:
        defaults["health_message"] = str(p.get("health_message") or "")[:255]
    if p.get("ip_address"):
        defaults["ip_address"] = p["ip_address"]
    if isinstance(p.get("metadata"), dict):
        defaults["metadata"] = p["metadata"]
    ClientDevice.objects.update_or_create(id=p["device_id"], defaults=defaults)


@handles("device.status_changed")
def device_status_changed(event: SyncEvent) -> None:
    p = event.payload
    updates = {
        "status": p["status"],
        "last_heartbeat_at": p.get("last_heartbeat_at") or event.occurred_at,
        "application_version": p.get("application_version", ""),
        "updated_at": timezone.now(),
    }
    if p.get("connection_status") in ConnectionStatus.values:
        updates["connection_status"] = p["connection_status"]
    if p.get("power_status") in PowerStatus.values:
        updates["power_status"] = p["power_status"]
    if p.get("kiosk_status") in KioskStatus.values:
        updates["kiosk_status"] = p["kiosk_status"]
    if p.get("occupancy_status") in OccupancyStatus.values:
        updates["occupancy_status"] = p["occupancy_status"]
    if p.get("health_status") in HealthStatus.values:
        updates["health_status"] = p["health_status"]
    if "health_message" in p:
        updates["health_message"] = str(p.get("health_message") or "")[:255]
    if p.get("last_power_change_at"):
        updates["last_power_change_at"] = _iso(p.get("last_power_change_at"), None)
    if p.get("ip_address"):
        updates["ip_address"] = p["ip_address"]
    ClientDevice.objects.filter(id=p["device_id"], edge_id=event.edge_id).update(**updates)


@handles("device.deactivated")
def device_deactivated(event: SyncEvent) -> None:
    ClientDevice.objects.filter(
        id=event.payload["device_id"], edge_id=event.edge_id
    ).update(
        is_active=False,
        status=ClientStatus.OFFLINE,
        connection_status=ConnectionStatus.OFFLINE,
        occupancy_status=OccupancyStatus.FREE,
        updated_at=timezone.now(),
    )


@handles("device.updated")
def device_updated(event: SyncEvent) -> None:
    p = event.payload
    defaults = {
        "updated_at": timezone.now(),
    }
    if "name" in p:
        defaults["name"] = str(p["name"])[:80]
    if "metadata" in p and isinstance(p["metadata"], dict):
        defaults["metadata"] = p["metadata"]
    if "is_active" in p:
        defaults["is_active"] = bool(p["is_active"])
    ClientDevice.objects.filter(id=p["device_id"], edge_id=event.edge_id).update(**defaults)


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
    group_name = p.get("group_name")
    if p.get("group_id"):
        group = _owned(CustomerGroup, p["group_id"], event.edge_id, "group")
    if group is None and group_name:
        group = CustomerGroup.objects.filter(edge_id=event.edge_id, name=group_name).first()
    if group is None:
        notes = str(p.get("notes") or "")
        if any(k in notes for k in ["کادر", "۲۰,۰۰۰", "20000"]):
            group = CustomerGroup.objects.filter(edge_id=event.edge_id, name="کادر").first()
        elif any(k in notes for k in ["رهرو", "لیگ", "۴۰,۰۰۰", "40000"]):
            group = CustomerGroup.objects.filter(edge_id=event.edge_id, name="لیگ رهرو").first()

    existing_cust = Customer.objects.filter(id=p["customer_id"]).first()
    if group is None and existing_cust and existing_cust.group:
        group = existing_cust.group

    if group is None and p.get("group_id"):
        group = CustomerGroup.objects.filter(edge_id=event.edge_id, name="آزاد").first() or CustomerGroup.objects.filter(edge_id=event.edge_id).first()
    phone = str(p.get("phone", "") or "").strip()
    username = str(p.get("username", "") or "").strip()
    if phone and Customer.objects.filter(edge_id=event.edge_id, phone=phone).exclude(id=p["customer_id"]).exists():
        logger.warning(
            "customer %s phone %s collides on edge %s; omitting duplicate phone",
            p["customer_id"],
            phone,
            event.edge_id,
        )
        phone = ""
    if username and Customer.objects.filter(edge_id=event.edge_id, username=username).exclude(id=p["customer_id"]).exists():
        logger.warning(
            "customer %s username %s collides on edge %s; omitting duplicate username",
            p["customer_id"],
            username,
            event.edge_id,
        )
        username = ""
    defaults = {
        "edge_id": event.edge_id,
        "full_name": p["full_name"],
        "username": username,
        "phone": phone,
        "group": group,
        "credit_limit": int(p.get("credit_limit", 0)),
        "debt_balance": int(p.get("debt_balance", 0)),
        "max_debt_limit": int(p.get("max_debt_limit", 40000)),
        "is_active": bool(p.get("is_active", True)),
        "notes": p.get("notes", ""),
        "revision": int(p.get("revision", 1)),
        "is_replica": True,
    }
    if p.get("password_hash"):
        defaults["password_hash"] = p["password_hash"]

    customer, _ = Customer.objects.update_or_create(
        id=p["customer_id"],
        defaults=defaults,
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
        customer, _ = Customer.objects.get_or_create(
            id=p["customer_id"],
            defaults={
                "edge_id": event.edge_id,
                "full_name": p.get("customer_name") or "مشتری",
                "is_replica": True,
            },
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
        customer, _ = Customer.objects.get_or_create(
            id=p["customer_id"],
            defaults={
                "edge_id": event.edge_id,
                "full_name": p.get("customer_name") or "مشتری",
                "is_replica": True,
            },
        )
    session = None
    if p.get("session_id"):
        session = _owned(GamingSession, p["session_id"], event.edge_id, "session")
        if session is None:
            logger.warning("ledger entry references unprojected session %s; proceeding without session FK", p["session_id"])
    reverses = None
    if p.get("reverses_id"):
        reverses = _owned(LedgerEntry, p["reverses_id"], event.edge_id, "ledger entry")
        if reverses is None:
            logger.warning("ledger entry reverses unprojected entry %s; proceeding without reverses FK", p["reverses_id"])

    created_dt = _iso(p.get("created_at"), event.occurred_at)
    tracking_code = str(p.get("tracking_code") or "").strip()[:32] or generate_tracking_code(created_dt)
    operator_label = str(p.get("operator_label") or "").strip()[:120]

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
            "tracking_code": tracking_code,
            "operator_label": operator_label,
            "source_command_id": p.get("source_command_id"),
            "is_replica": True,
            "created_at": created_dt,
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
    if customer is None:
        customer, _ = Customer.objects.get_or_create(
            id=p["customer_id"],
            defaults={
                "edge_id": event.edge_id,
                "full_name": p.get("customer_name") or "مشتری",
                "is_replica": True,
            },
        )
    if device is None:
        device, _ = ClientDevice.objects.get_or_create(
            id=p["device_id"],
            defaults={
                "edge_id": event.edge_id,
                "name": p.get("device_name") or "سیستم",
                "is_replica": True,
            },
        )
    tariff = None
    if p.get("tariff_id"):
        tariff = _owned(Tariff, p["tariff_id"], event.edge_id, "tariff")
    customer_rate = None
    if p.get("customer_rate_id"):
        customer_rate = _owned(CustomerRate, p["customer_rate_id"], event.edge_id, "customer rate")
        if customer_rate and customer_rate.customer_id != customer.id:
            customer_rate = None
    billing_mode = p.get("billing_mode") if p.get("billing_mode") in BillingMode.values else BillingMode.CREDIT
    disconnect_policy = (
        p.get("disconnect_policy")
        if p.get("disconnect_policy") in DisconnectPolicy.values
        else DisconnectPolicy.PAUSE
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
            "billing_mode": billing_mode,
            "planned_duration_minutes": p.get("planned_duration_minutes"),
            "estimated_cost": int(p.get("estimated_cost", 0) or 0),
            "disconnect_policy": disconnect_policy,
            "paused_seconds": int(p.get("paused_seconds", 0) or 0),
            "started_at": _iso(p.get("started_at"), event.occurred_at),
            "is_replica": True,
        },
    )
    ClientDevice.objects.filter(id=device.id, edge_id=event.edge_id).update(
        occupancy_status=OccupancyStatus.BUSY,
        kiosk_status=KioskStatus.UNLOCKED,
        updated_at=timezone.now(),
    )


@handles("session.updated")
def session_updated(event: SyncEvent) -> None:
    p = event.payload
    session = _owned(GamingSession, p["session_id"], event.edge_id, "session")
    if session is None:
        return
    session.connection_lost_at = _iso(p.get("connection_lost_at"), None)
    session.paused_at = _iso(p.get("paused_at"), None)
    session.paused_seconds = int(p.get("paused_seconds", session.paused_seconds or 0) or 0)
    session.is_replica = True
    session.save(
        update_fields=["connection_lost_at", "paused_at", "paused_seconds", "is_replica", "updated_at"]
    )


@handles("session.ended")
def session_ended(event: SyncEvent) -> None:
    p = event.payload
    session = _owned(GamingSession, p["session_id"], event.edge_id, "session")
    if session is None:
        logger.warning("session.ended arrived for unprojected session %s; creating completed record", p["session_id"])
        customer = _owned(Customer, p.get("customer_id"), event.edge_id, "customer")
        if customer is None and p.get("customer_id"):
            customer, _ = Customer.objects.get_or_create(
                id=p["customer_id"],
                defaults={
                    "edge_id": event.edge_id,
                    "full_name": p.get("customer_name") or "مشتری",
                    "is_replica": True,
                },
            )
        device = _owned(ClientDevice, p.get("device_id"), event.edge_id, "device")
        if device is None and p.get("device_id"):
            device, _ = ClientDevice.objects.get_or_create(
                id=p["device_id"],
                defaults={
                    "edge_id": event.edge_id,
                    "name": p.get("device_name") or "سیستم",
                    "is_replica": True,
                },
            )
        session = GamingSession.objects.create(
            id=p["session_id"],
            edge_id=event.edge_id,
            customer=customer,
            device=device,
            status=p.get("status", SessionStatus.COMPLETED),
            hourly_rate=int(p.get("hourly_rate", 0)),
            started_at=_iso(p.get("started_at"), event.occurred_at),
            ended_at=_iso(p.get("ended_at"), event.occurred_at),
            elapsed_seconds=int(p.get("elapsed_seconds", 0)),
            cost=int(p.get("cost", 0)),
            is_replica=True,
        )
    session.status = p.get("status", SessionStatus.COMPLETED)
    session.ended_at = _iso(p.get("ended_at"), event.occurred_at)
    session.elapsed_seconds = int(p.get("elapsed_seconds", 0))
    session.paused_seconds = int(p.get("paused_seconds", session.paused_seconds or 0) or 0)
    session.paused_at = None
    session.connection_lost_at = None
    session.cost = int(p.get("cost", 0))
    session.end_reason = p.get("end_reason", "")
    session.discount_percent = int(p.get("discount_percent", session.discount_percent or 0))
    session.discount_amount = int(p.get("discount_amount", session.discount_amount or 0))
    session.discount_source = p.get("discount_source", session.discount_source or "")
    session.is_replica = True
    session.save(
        update_fields=[
            "status", "ended_at", "elapsed_seconds", "paused_seconds", "paused_at",
            "connection_lost_at", "cost", "end_reason",
            "discount_percent", "discount_amount", "discount_source",
            "is_replica", "updated_at",
        ]
    )
    if session.device_id:
        ClientDevice.objects.filter(id=session.device_id, edge_id=event.edge_id).update(
            occupancy_status=OccupancyStatus.FREE,
            kiosk_status=KioskStatus.LOCKED,
            updated_at=timezone.now(),
        )

    # همگام‌سازی تضمینی زمان بازی با سامانه رهرو از سمت ابر
    try:
        import requests
        from django.conf import settings
        rahro_url = getattr(settings, "RAHRO_API_URL", "http://127.0.0.1:8000/rahro/api/gamenet/")
        shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
        cust = session.customer
        payload = {
            "session_id": str(session.id),
            "phone": cust.phone if cust else "",
            "username": cust.username if cust else "",
            "device_name": session.device.name if session.device else "",
            "started_at": session.started_at.isoformat() if session.started_at else "",
            "ended_at": session.ended_at.isoformat() if session.ended_at else "",
            "duration_seconds": session.elapsed_seconds,
            "hourly_rate": session.hourly_rate,
            "base_cost": (session.cost or 0) + (session.discount_amount or 0),
            "discount_percent": session.discount_percent,
            "discount_amount": session.discount_amount,
            "final_cost": session.cost,
            "discount_source": session.discount_source,
        }
        requests.post(
            f"{rahro_url.rstrip('/')}/record-session/",
            json=payload,
            headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
            timeout=3,
        )
    except Exception:
        pass

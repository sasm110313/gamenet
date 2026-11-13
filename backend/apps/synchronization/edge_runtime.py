"""Edge runtime: heartbeat, command processing, config pull."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.clients.models import ClientDevice
from apps.core.roles import require_edge
from apps.core.security import canonical_json
from apps.synchronization import command_service
from apps.synchronization.cloud_client import CloudClient, CloudRejected, CloudUnavailable
from apps.synchronization.config import apply_snapshot, current_config
from apps.synchronization.events import emit
from apps.synchronization.edge_credentials import load_credentials
from apps.synchronization.models import EdgeIdentity, OutboxEvent, OutboxStatus

logger = logging.getLogger("gamenet.edge_runtime")


def build_heartbeat() -> dict[str, Any]:
    require_edge()
    identity = EdgeIdentity.get_solo()
    devices = [
        {
            "device_id": str(d.id),
            "status": d.status,
            "connection_status": d.connection_status,
            "power_status": d.power_status,
            "kiosk_status": d.kiosk_status,
            "occupancy_status": d.occupancy_status,
            "health_status": d.health_status,
            "health_message": d.health_message,
            "last_power_change_at": (
                d.last_power_change_at.isoformat() if d.last_power_change_at else None
            ),
            "last_heartbeat_at": d.last_heartbeat_at.isoformat() if d.last_heartbeat_at else None,
            "application_version": d.application_version,
            "name": d.name,
        }
        for d in ClientDevice.objects.filter(is_active=True)
    ]
    counts = {
        "pending": OutboxEvent.objects.filter(status=OutboxStatus.PENDING).count(),
        "failed": OutboxEvent.objects.filter(status=OutboxStatus.FAILED).count(),
        "total": OutboxEvent.objects.count(),
    }
    cfg = current_config()
    from apps.applications.services import get_games_catalog_state
    games_state = get_games_catalog_state()
    return {
        "edge_id": str(identity.edge_id),
        "edge_name": identity.name,
        "software_version": settings.GAMENET_VERSION,
        "sent_at": timezone.now().isoformat(),
        "config_version": cfg["version"],
        "outbox": counts,
        "devices": devices,
        "games_version": games_state["version"],
        "games_hash": games_state["hash"],
        "games_catalog": games_state["games"],
    }


def send_heartbeat(client: CloudClient) -> dict:
    require_edge()
    try:
        response = client.heartbeat(build_heartbeat())
    except Exception:
        EdgeIdentity.objects.filter(pk=1).update(status="OFFLINE")
        raise
    EdgeIdentity.objects.filter(pk=1).update(
        last_heartbeat_at=timezone.now(),
        last_connected_at=timezone.now(),
        status="ONLINE",
        cloud_base_url=client.base,
    )
    _maybe_apply_remote_games(response)
    return response


def pull_and_queue_commands(client: CloudClient) -> int:
    """Safety net for commands pushed while the WSS was down."""
    require_edge()
    response = client.fetch_commands(limit=50)
    items = response.get("commands", [])
    queued = 0
    for envelope in items:
        row, is_new = command_service.receive_command(envelope)
        if is_new:
            queued += 1
    return queued


def execute_received_commands(*, limit: int = 20) -> int:
    from apps.commands.models import InboundCommandStatus, InboundRemoteCommand

    require_edge()
    pending = list(
        InboundRemoteCommand.objects.filter(status=InboundCommandStatus.RECEIVED)
        .order_by("received_at")
        .values_list("command_id", flat=True)[:limit]
    )
    for command_id in pending:
        command_service.execute_command(command_id)
    return len(pending)


def _maybe_apply_remote_games(response: dict[str, Any]) -> bool:
    from apps.applications.services import get_games_catalog_state, save_games_catalog

    remote_games = response.get("games_catalog")
    if not isinstance(remote_games, list):
        return False
    remote_version = int(response.get("games_version") or 0)
    remote_hash = str(response.get("games_hash") or "")
    local = get_games_catalog_state()
    if remote_hash and remote_hash == local["hash"]:
        return False
    if remote_version > int(local["version"] or 0) or (
        remote_version == int(local["version"] or 0) and remote_hash != local["hash"]
    ):
        save_games_catalog(remote_games, version=remote_version)
        return True
    return False


def sync_config(client: CloudClient, *, force: bool = False) -> dict[str, Any]:
    require_edge()
    identity = EdgeIdentity.get_solo()
    response = client.fetch_config(after=0 if force else identity.config_version)
    games_updated = _maybe_apply_remote_games(response)
    if response.get("up_to_date"):
        return {"changed": False, "games_updated": games_updated, "version": identity.config_version}
    snapshot = response.get("snapshot") or {}
    version = int(snapshot.get("version", 0))
    payload = snapshot.get("payload") or {}
    expected = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    if snapshot.get("content_hash") != expected:
        raise ValueError(f"config snapshot v{version} hash mismatch")
    with transaction.atomic():
        applied = apply_snapshot(version=version, content_hash=expected, payload=payload)
    EdgeIdentity.objects.filter(pk=1).update(
        config_version=applied.version, last_config_check_at=timezone.now()
    )
    return {"changed": True, "games_updated": games_updated, "version": version}


def sync_seed_catalog_if_empty(client: CloudClient) -> int:
    """Pull initial tariffs, groups, and Rahro customers from Cloud on a fresh Edge."""
    from apps.customer_groups.models import CustomerGroup
    from apps.customers.models import Customer
    from apps.pricing.models import CustomerRate, Tariff
    from apps.synchronization.sync_log import record_sync_log
    from apps.wallets.models import Wallet

    require_edge()
    if Customer.objects.exists():
        return 0

    data = client.fetch_seed_catalog()
    edge_id = EdgeIdentity.get_solo().edge_id
    imported_customers = 0

    with transaction.atomic():
        tariff_map: dict[str, Tariff] = {}
        for t in data.get("tariffs") or []:
            obj = (
                Tariff.objects.filter(id=t["id"]).first()
                or Tariff.objects.filter(edge_id=edge_id, name=t["name"]).first()
            )
            if obj is None:
                obj = Tariff.objects.create(
                    id=t["id"],
                    edge_id=edge_id,
                    name=t["name"],
                    hourly_rate=int(t["hourly_rate"]),
                    is_active=bool(t.get("is_active", True)),
                    revision=int(t.get("revision", 1)),
                    is_replica=False,
                )
            else:
                obj.edge_id = edge_id
                obj.hourly_rate = int(t["hourly_rate"])
                obj.is_active = bool(t.get("is_active", True))
                obj.save(update_fields=["edge_id", "hourly_rate", "is_active", "updated_at"])
            tariff_map[str(t["id"])] = obj

        group_map: dict[str, CustomerGroup] = {}
        for g in data.get("groups") or []:
            t_obj = tariff_map.get(str(g.get("tariff_id") or ""))
            obj = (
                CustomerGroup.objects.filter(id=g["id"]).first()
                or CustomerGroup.objects.filter(edge_id=edge_id, name=g["name"]).first()
            )
            if obj is None:
                obj = CustomerGroup.objects.create(
                    id=g["id"],
                    edge_id=edge_id,
                    name=g["name"],
                    tariff=t_obj,
                    is_active=bool(g.get("is_active", True)),
                    revision=int(g.get("revision", 1)),
                    is_replica=False,
                )
            else:
                obj.edge_id = edge_id
                if t_obj is not None:
                    obj.tariff = t_obj
                obj.is_active = bool(g.get("is_active", True))
                obj.save(update_fields=["edge_id", "tariff", "is_active", "updated_at"])
            group_map[str(g["id"])] = obj

        for c in data.get("customers") or []:
            g_obj = group_map.get(str(c.get("group_id") or ""))
            if g_obj is None and c.get("group_name"):
                g_obj = CustomerGroup.objects.filter(edge_id=edge_id, name=c["group_name"]).first()
            if g_obj is None:
                notes = str(c.get("notes") or "")
                if any(k in notes for k in ["کادر", "۲۰,۰۰۰", "20000"]):
                    g_obj = CustomerGroup.objects.filter(edge_id=edge_id, name="کادر").first()
                elif any(k in notes for k in ["رهرو", "لیگ", "۴۰,۰۰۰", "40000"]):
                    g_obj = CustomerGroup.objects.filter(edge_id=edge_id, name="لیگ رهرو").first()
            phone = str(c.get("phone") or "").strip()
            if phone and Customer.objects.filter(edge_id=edge_id, phone=phone).exclude(id=c["id"]).exists():
                phone = ""
            cust, created = Customer.objects.update_or_create(
                id=c["id"],
                defaults={
                    "edge_id": edge_id,
                    "full_name": c["full_name"],
                    "username": str(c.get("username") or "").strip(),
                    "password_hash": str(c.get("password_hash") or ""),
                    "phone": phone,
                    "group": g_obj,
                    "credit_limit": int(c.get("credit_limit") or 0),
                    "debt_balance": int(c.get("debt_balance") or 0),
                    "max_debt_limit": int(c.get("max_debt_limit") or 40000),
                    "active_coupons": int(c.get("active_coupons") or 0),
                    "is_active": bool(c.get("is_active", True)),
                    "notes": str(c.get("notes") or ""),
                    "revision": int(c.get("revision") or 1),
                    "is_replica": False,
                },
            )
            Wallet.objects.get_or_create(
                customer=cust,
                defaults={"balance": int(c.get("wallet_balance") or 0), "is_replica": False},
            )
            for r in c.get("rates") or []:
                CustomerRate.objects.update_or_create(
                    id=r["id"],
                    defaults={
                        "edge_id": edge_id,
                        "customer": cust,
                        "name": r["name"],
                        "hourly_rate": int(r["hourly_rate"]),
                        "is_default": bool(r.get("is_default", False)),
                        "is_active": bool(r.get("is_active", True)),
                        "revision": int(r.get("revision", 1)),
                        "is_replica": False,
                    },
                )
            if created:
                imported_customers += 1

    if imported_customers:
        record_sync_log(
            "INFO",
            "seed",
            f"دریافت اولیه {imported_customers} مشتری و تعرفه‌ها از سرور آنلاین با موفقیت انجام شد.",
        )
    return imported_customers


def run_once(*, client: CloudClient | None = None, pull_commands: bool = True) -> dict[str, Any]:
    """One worker cycle. Exposed for tests and the --once mode."""
    if client is None:
        from contextlib import closing
        with closing(CloudClient(load_credentials())) as owned_client:
            return run_once(client=owned_client, pull_commands=pull_commands)
    from apps.devices.services import mark_stale_devices_offline
    from apps.sessions.services import enforce_active_session_policies
    from apps.synchronization.outbox import drain_outbox

    require_edge()
    identity = EdgeIdentity.get_solo()
    result: dict[str, Any] = {}

    queued = 0
    if pull_commands:
        try:
            queued = pull_and_queue_commands(client)
        except (CloudUnavailable, CloudRejected) as exc:
            result["command_pull_error"] = str(exc)
    executed = execute_received_commands()
    result["commands"] = {"queued": queued, "executed": executed}

    result["outbox"] = drain_outbox(client=client)

    force_config_sync = False
    if identity.last_heartbeat_at is None or (
        timezone.now() - identity.last_heartbeat_at
    ).total_seconds() >= settings.EDGE_HEARTBEAT_SECONDS:
        try:
            hb_resp = send_heartbeat(client)
            result["heartbeat"] = hb_resp
            from apps.applications.services import get_games_catalog_state

            local_games = get_games_catalog_state()
            if (
                int(hb_resp.get("games_version") or 0) > int(local_games["version"] or 0)
                and str(hb_resp.get("games_hash") or "") != local_games["hash"]
            ):
                force_config_sync = True
        except (CloudUnavailable, CloudRejected) as exc:
            result["heartbeat"] = {"error": str(exc)}

    if force_config_sync or identity.last_config_check_at is None or (
        timezone.now() - identity.last_config_check_at
    ).total_seconds() >= 30:
        try:
            result["config"] = sync_config(client)
        except (CloudUnavailable, CloudRejected) as exc:
            result["config"] = {"error": str(exc)}
        EdgeIdentity.objects.filter(pk=1).update(last_config_check_at=timezone.now())

    try:
        synced_seed = sync_seed_catalog_if_empty(client)
        if synced_seed:
            result["seed_customers"] = synced_seed
    except (CloudUnavailable, CloudRejected) as exc:
        result["seed_error"] = str(exc)

    result["stale_devices"] = mark_stale_devices_offline()
    result["session_policies"] = enforce_active_session_policies()
    result["expired_commands"] = command_service.expire_stale_commands()
    return result


def emit_test_event(note: str = "phase0 proof", extra: dict | None = None) -> OutboxEvent:
    require_edge()
    identity = EdgeIdentity.get_solo()
    with transaction.atomic():
        return emit(
            "edge.test",
            aggregate_type="edge",
            aggregate_id=str(identity.edge_id),
            payload={"note": note, "extra": extra or {}, "at": timezone.now().isoformat()},
        )

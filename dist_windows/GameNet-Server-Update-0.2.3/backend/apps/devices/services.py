"""Device lifecycle on the edge: pairing, authentication, presence, status."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
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
from apps.core.roles import require_edge
from apps.core.security import constant_time_equal
from apps.devices.models import RegistrationCode
from apps.synchronization.crypto import hash_token
from apps.synchronization.edge_credentials import ensure_identity, load_credentials
from apps.synchronization.events import emit
from apps.synchronization.models import EdgeIdentity

logger = logging.getLogger("gamenet.devices")

CANONICAL_STATIONS = [f"PC-{i:02d}" for i in range(1, 11)]

PRESENCE_STATES = {
    ClientStatus.OFFLINE,
    ClientStatus.ONLINE,
    ClientStatus.LOCKED,
    ClientStatus.IDLE,
    ClientStatus.STARTING,
    ClientStatus.ACTIVE,
    ClientStatus.STOPPING,
    ClientStatus.ERROR,
}


class RegistrationError(ValueError):
    pass


def get_client_update_info() -> dict | None:
    """Retrieve metadata about the latest client update available on Edge/Cloud."""
    import hashlib
    import json
    from pathlib import Path

    base_dir = Path(settings.BASE_DIR)

    # 1. Check static updates latest.json
    static_json = base_dir / "static" / "updates" / "latest.json"
    if static_json.exists():
        try:
            with open(static_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("version"):
                    return data
        except Exception as exc:
            logger.debug("Failed reading static updates latest.json: %s", exc)

    # 2. Check runtime updates client_update.json
    runtime_json = base_dir / ".runtime" / "client_update.json"
    if runtime_json.exists():
        try:
            with open(runtime_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("version"):
                    return data
        except Exception as exc:
            logger.debug("Failed reading runtime updates client_update.json: %s", exc)

    # 3. If app.asar exists in static/updates/ but latest.json doesn't, auto-derive info
    asar_path = base_dir / "static" / "updates" / "app.asar"
    if asar_path.exists():
        try:
            h = hashlib.sha256()
            with open(asar_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return {
                "version": getattr(settings, "CLIENT_TARGET_VERSION", "0.2.0"),
                "url": "/static/updates/app.asar",
                "sha256": h.hexdigest(),
                "notes": "بروزرسانی خودکار کلاینت بازی سرای رهرو",
            }
        except Exception as exc:
            logger.debug("Failed computing asar hash: %s", exc)

    return None


def create_registration_code(*, actor=None, label: str = "", ttl_minutes: int | None = None):
    require_edge()
    ttl = ttl_minutes or settings.DEVICE_REGISTRATION_CODE_TTL_MINUTES
    last_error = None
    for _ in range(5):
        code = RegistrationCode.generate_code()
        try:
            return RegistrationCode.objects.create(
                code=code,
                label=label,
                created_by=actor if getattr(actor, "pk", None) else None,
                expires_at=timezone.now() + timedelta(minutes=ttl),
            )
        except Exception as exc:  # unique collision, retry
            last_error = exc
    raise RuntimeError(f"could not allocate registration code: {last_error}")


def normalize_station_name(raw_name: str) -> str:
    """Normalize station number or name (e.g., '3' or 'pc-3' -> 'PC-03')."""
    text = (raw_name or "").strip()
    if not text:
        return ""
    persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
    english = "01234567890123456789"
    text = text.translate(str.maketrans(persian_arabic, english)).strip().upper()
    if text.isdigit():
        return f"PC-{int(text):02d}"
    if text.startswith("PC") and "-" not in text and text[2:].isdigit():
        return f"PC-{int(text[2:]):02d}"
    if text.startswith("PC-") and text[3:].isdigit():
        return f"PC-{int(text[3:]):02d}"
    return text[:80]


@transaction.atomic
def register_device(
    *,
    code: str,
    name: str,
    hostname: str = "",
    operating_system: str = "",
    application_version: str = "",
    ip_address: str | None = None,
    mac_address: str = "",
    device_id=None,
) -> tuple[ClientDevice, str]:
    """Pair a device and return its one-time plaintext token.

    The token is stored only as a SHA-256 hash; losing it means re-pairing.
    """
    require_edge()
    identity = ensure_identity()

    code_clean = (code or "").strip().upper()
    is_auto = code_clean in {"AUTO", "LAN_AUTO", "SMARTLAUNCH", ""}

    reg = None
    if not is_auto:
        reg = (
            RegistrationCode.objects.select_for_update()
            .filter(code=code_clean)
            .first()
        )
        if reg is None or not reg.is_usable():
            raise RegistrationError("کد ثبت دستگاه نامعتبر یا منقضی شده است.")

    from apps.sessions.models import GamingSession, SessionStatus

    token = secrets.token_urlsafe(32)
    clean_name = normalize_station_name(name)
    clean_host = (hostname or "").strip()

    device: ClientDevice | None = None
    if device_id:
        candidate = ClientDevice.objects.select_for_update().filter(id=device_id).first()
        if candidate is not None and candidate.edge_id != identity.edge_id:
            raise RegistrationError("شناسه دستگاه به این سرور تعلق ندارد.")
        if candidate is not None and (not clean_name or clean_name == candidate.name):
            device = candidate

    if device is None and clean_name:
        existing_named = (
            ClientDevice.objects.select_for_update()
            .filter(name=clean_name, edge_id=identity.edge_id)
            .order_by("-is_active")
            .first()
        )
        if existing_named is not None:
            has_active_session = GamingSession.objects.filter(
                device=existing_named, status=SessionStatus.ACTIVE
            ).exists()
            if has_active_session and existing_named.token_hash and (
                not device_id or str(existing_named.id) != str(device_id)
            ):
                raise RegistrationError(f"ایستگاه «{clean_name}» هم‌اکنون دارای نشست فعال است.")
            existing_named.is_active = True
            device = existing_named
        else:
            device = ClientDevice(
                edge_id=identity.edge_id,
                name=clean_name[:80],
                status=ClientStatus.OFFLINE,
                registered_at=timezone.now(),
            )

    if device is None:
        # 1. Exact match if valid station name requested (e.g. PC-01 .. PC-10)
        if clean_name in CANONICAL_STATIONS:
            device = ClientDevice.objects.select_for_update().filter(
                name=clean_name, edge_id=identity.edge_id, is_active=True
            ).first()

        # 2. Hostname match for returning PCs (reboot/reconnect)
        if device is None and clean_host and clean_host.lower() not in {"localhost", "127.0.0.1", "win-pc"}:
            device = ClientDevice.objects.select_for_update().filter(
                hostname=clean_host, edge_id=identity.edge_id, is_active=True
            ).first()

        # 3. IP address match for static salon LAN IPs
        if device is None and ip_address and ip_address not in {"127.0.0.1", "::1"}:
            device = ClientDevice.objects.select_for_update().filter(
                ip_address=ip_address, edge_id=identity.edge_id, is_active=True
            ).first()

        # 4. Auto-assignment from the 10 salon slots (PC-01 to PC-10)
        if device is None:
            existing = {
                d.name: d
                for d in ClientDevice.objects.select_for_update().filter(
                    edge_id=identity.edge_id, is_active=True
                )
            }
            # Find the lowest unassigned or fresh canonical slot
            for slot in CANONICAL_STATIONS:
                if slot in existing:
                    candidate = existing[slot]
                    if not candidate.token_hash or (candidate.status == ClientStatus.OFFLINE and not candidate.hostname):
                        device = candidate
                        break
                else:
                    device = ClientDevice(
                        edge_id=identity.edge_id,
                        name=slot,
                        status=ClientStatus.OFFLINE,
                        registered_at=timezone.now(),
                    )
                    break

            # If all 10 exist, look for any offline slot without an active session
            if device is None:
                for slot in CANONICAL_STATIONS:
                    if slot in existing and existing[slot].status == ClientStatus.OFFLINE:
                        device = existing[slot]
                        break

            # Fallback if salon exceeds 10
            if device is None:
                fallback_name = clean_name if clean_name and clean_name not in existing else f"PC-{len(existing) + 1:02d}"
                device = ClientDevice(
                    edge_id=identity.edge_id,
                    name=fallback_name[:80],
                    status=ClientStatus.OFFLINE,
                    registered_at=timezone.now(),
                )

    from apps.devices.wol import normalize_mac_safe, resolve_mac_from_arp

    device.hostname = hostname[:120] or device.hostname
    device.operating_system = operating_system[:120] or device.operating_system
    device.application_version = application_version[:40] or device.application_version
    device.ip_address = ip_address or device.ip_address
    meta = dict(device.metadata or {})
    resolved_mac = normalize_mac_safe(mac_address) or normalize_mac_safe(meta.get("mac_address")) or resolve_mac_from_arp(device.ip_address)
    if resolved_mac:
        meta["mac_address"] = resolved_mac
    device.metadata = meta
    device.token_hash = hash_token(token)
    device.token_issued_at = timezone.now()
    device.save()

    # If this physical PC switched stations (had another previous device_id or hostname), release old idle slots
    if device_id:
        for stale in ClientDevice.objects.select_for_update().filter(
            edge_id=identity.edge_id, is_active=True
        ).exclude(pk=device.pk):
            if str(stale.id) == str(device_id) and not GamingSession.objects.filter(
                device=stale, status=SessionStatus.ACTIVE
            ).exists():
                stale.token_hash = ""
                stale.token_issued_at = None
                stale.hostname = ""
                stale.ip_address = None
                stale.status = ClientStatus.OFFLINE
                stale.connection_status = ConnectionStatus.OFFLINE
                stale.power_status = PowerStatus.UNKNOWN
                stale.kiosk_status = KioskStatus.LOCKED
                stale.occupancy_status = OccupancyStatus.FREE
                stale.save(
                    update_fields=[
                        "token_hash",
                        "token_issued_at",
                        "hostname",
                        "ip_address",
                        "status",
                        "connection_status",
                        "power_status",
                        "kiosk_status",
                        "occupancy_status",
                        "updated_at",
                    ]
                )

    if reg is not None:
        reg.used_at = timezone.now()
        reg.used_by = device
        reg.save(update_fields=["used_at", "used_by"])

    emit(
        "device.registered",
        aggregate_type="device",
        aggregate_id=str(device.id),
        payload={
            "device_id": str(device.id),
            "name": device.name,
            "hostname": device.hostname,
            "operating_system": device.operating_system,
            "application_version": device.application_version,
            "ip_address": device.ip_address,
            "metadata": device.metadata,
            "status": device.status,
            "connection_status": device.connection_status,
            "power_status": device.power_status,
            "kiosk_status": device.kiosk_status,
            "occupancy_status": device.occupancy_status,
            "health_status": device.health_status,
            "health_message": device.health_message,
            "registered_at": device.registered_at.isoformat(),
        },
    )
    return device, token


def authenticate_device(device_id, token: str) -> ClientDevice | None:
    if not device_id or not token:
        return None
    try:
        device = ClientDevice.objects.filter(id=device_id, is_active=True).first()
    except (ValueError, TypeError, ValidationError):
        return None
    if device is None or not device.token_hash:
        return None
    if not constant_time_equal(device.token_hash, hash_token(token)):
        return None
    return device


_LAN_PROBE_CACHE: dict[str, float] = {}


def _emit_session_runtime_update(session) -> None:
    emit(
        "session.updated",
        aggregate_type="session",
        aggregate_id=str(session.id),
        payload={
            "session_id": str(session.id),
            "connection_lost_at": (
                session.connection_lost_at.isoformat() if session.connection_lost_at else None
            ),
            "paused_at": session.paused_at.isoformat() if session.paused_at else None,
            "paused_seconds": int(session.paused_seconds or 0),
        },
    )


def handle_device_disconnect(device: ClientDevice, *, now=None) -> None:
    """Apply disconnect policy bookkeeping when a device loses client connection mid-session."""
    from apps.sessions.models import DisconnectPolicy, GamingSession, SessionStatus

    now = now or timezone.now()
    session = (
        GamingSession.objects.select_for_update()
        .filter(device=device, status=SessionStatus.ACTIVE)
        .first()
    )
    if session is None:
        return

    changed_fields: list[str] = []
    if session.connection_lost_at is None:
        session.connection_lost_at = now
        changed_fields.append("connection_lost_at")
    if session.disconnect_policy == DisconnectPolicy.PAUSE and session.paused_at is None:
        session.paused_at = now
        changed_fields.append("paused_at")
    if changed_fields:
        changed_fields.append("updated_at")
        session.save(update_fields=changed_fields)
        _emit_session_runtime_update(session)


def handle_device_reconnect(device: ClientDevice, *, now=None) -> None:
    """Close disconnect/pause window on reconnect for any active session."""
    from apps.sessions.models import GamingSession, SessionStatus

    now = now or timezone.now()
    session = (
        GamingSession.objects.select_for_update()
        .filter(device=device, status=SessionStatus.ACTIVE)
        .first()
    )
    if session is None:
        return

    changed_fields: list[str] = []
    if session.paused_at is not None:
        delta = max(0, int((now - session.paused_at).total_seconds()))
        session.paused_seconds = int(session.paused_seconds or 0) + delta
        session.paused_at = None
        changed_fields.extend(["paused_seconds", "paused_at"])
    if session.connection_lost_at is not None:
        session.connection_lost_at = None
        changed_fields.append("connection_lost_at")
    if changed_fields:
        changed_fields.append("updated_at")
        session.save(update_fields=changed_fields)
        _emit_session_runtime_update(session)


def _status_payload(device: ClientDevice, now, reason: str) -> dict[str, Any]:
    return {
        "device_id": str(device.id),
        "status": device.status,
        "connection_status": device.connection_status,
        "power_status": device.power_status,
        "kiosk_status": device.kiosk_status,
        "occupancy_status": device.occupancy_status,
        "health_status": device.health_status,
        "health_message": device.health_message,
        "last_power_change_at": (
            device.last_power_change_at.isoformat() if device.last_power_change_at else None
        ),
        "ip_address": device.ip_address,
        "last_heartbeat_at": (
            device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else now.isoformat()
        ),
        "application_version": device.application_version,
        "reason": reason,
    }


@transaction.atomic
def set_status(
    device: ClientDevice,
    new_status: str | None,
    *,
    force: bool = False,
    app_version: str = "",
    ip_address: str | None = None,
    mac_address: str = "",
    reason: str = "",
    connection_status: str | None = None,
    power_status: str | None = None,
    kiosk_status: str | None = None,
    occupancy_status: str | None = None,
    health_status: str | None = None,
    health_message: str | None = None,
    bump_heartbeat: bool | None = None,
) -> bool:
    """Apply legacy + orthogonal presence transitions. Emits only on actual change."""
    require_edge()
    from apps.devices.wol import normalize_mac_safe, resolve_mac_from_arp
    from apps.sessions.models import GamingSession, SessionStatus

    device = ClientDevice.objects.select_for_update().get(pk=device.pk)
    now = timezone.now()

    prev_conn = device.connection_status
    prev_power = device.power_status
    prev_kiosk = device.kiosk_status
    prev_occ = device.occupancy_status
    prev_health = device.health_status
    prev_health_msg = device.health_message

    if ip_address:
        device.ip_address = ip_address
    if app_version:
        device.application_version = app_version[:40]

    meta = dict(device.metadata or {})
    existing_mac = normalize_mac_safe(meta.get("mac_address"))
    candidate_mac = normalize_mac_safe(mac_address)
    if not candidate_mac and not existing_mac and new_status != ClientStatus.OFFLINE:
        candidate_mac = resolve_mac_from_arp(device.ip_address)

    mac_updated = False
    if candidate_mac and candidate_mac != existing_mac:
        meta["mac_address"] = candidate_mac
        device.metadata = meta
        mac_updated = True

    has_active_session = GamingSession.objects.filter(
        device=device, status=SessionStatus.ACTIVE
    ).exists()

    changed = False
    HUB_ONLY = {ClientStatus.ACTIVE, ClientStatus.IDLE, ClientStatus.STARTING, ClientStatus.STOPPING}
    if new_status and new_status != device.status:
        may_report_active = new_status == ClientStatus.ACTIVE and not force and has_active_session
        if new_status in HUB_ONLY and not force and not may_report_active:
            logger.info("ignoring hub-only state %s reported by %s", new_status, device.name)
        elif new_status in PRESENCE_STATES and (
            force or may_report_active or device.can_transition_to(new_status)
        ):
            device.status = new_status
            changed = True
        else:
            logger.info(
                "rejected presence transition %s -> %s for %s (%s)",
                device.status, new_status, device.name, reason or "unspecified",
            )

    # Resolve orthogonal dimensions without losing independent dimensions
    target_conn = connection_status
    if target_conn is None:
        if new_status == ClientStatus.OFFLINE:
            target_conn = ConnectionStatus.OFFLINE
        elif new_status in PRESENCE_STATES or reason in {"heartbeat", "rest heartbeat", "websocket connected", "command ack"}:
            target_conn = ConnectionStatus.ONLINE
    if target_conn in ConnectionStatus.values and target_conn != device.connection_status:
        device.connection_status = target_conn
        changed = True

    target_power = power_status
    if target_power is None and device.connection_status == ConnectionStatus.ONLINE:
        target_power = PowerStatus.ON
    if target_power in PowerStatus.values and target_power != device.power_status:
        device.power_status = target_power
        device.last_power_change_at = now
        changed = True

    target_kiosk = kiosk_status
    if target_kiosk is None:
        if new_status == ClientStatus.LOCKED:
            target_kiosk = KioskStatus.LOCKED
        elif new_status in {ClientStatus.STARTING, ClientStatus.ACTIVE}:
            target_kiosk = KioskStatus.UNLOCKED
    if target_kiosk in KioskStatus.values and target_kiosk != device.kiosk_status:
        device.kiosk_status = target_kiosk
        changed = True

    target_occ = occupancy_status
    if target_occ is None:
        if new_status == ClientStatus.MAINTENANCE:
            target_occ = OccupancyStatus.MAINTENANCE
        elif has_active_session or new_status in {ClientStatus.STARTING, ClientStatus.ACTIVE}:
            target_occ = OccupancyStatus.BUSY
        elif device.connection_status == ConnectionStatus.ONLINE and new_status in {
            ClientStatus.LOCKED,
            ClientStatus.IDLE,
            ClientStatus.ONLINE,
            ClientStatus.STOPPING,
        }:
            target_occ = OccupancyStatus.FREE
        elif new_status == ClientStatus.OFFLINE and not has_active_session and device.occupancy_status != OccupancyStatus.MAINTENANCE:
            target_occ = OccupancyStatus.FREE
    if target_occ in OccupancyStatus.values and target_occ != device.occupancy_status:
        device.occupancy_status = target_occ
        changed = True

    target_health = health_status
    target_health_msg = health_message
    if target_health is None and new_status == ClientStatus.ERROR:
        target_health = HealthStatus.ERROR
    elif (
        target_health is None
        and prev_health == HealthStatus.ERROR
        and reason in {"websocket connected", "session started", "session ended"}
        and new_status in {ClientStatus.LOCKED, ClientStatus.STARTING, ClientStatus.ACTIVE}
    ):
        target_health = HealthStatus.HEALTHY
        if target_health_msg is None:
            target_health_msg = ""

    if target_health in HealthStatus.values and target_health != device.health_status:
        device.health_status = target_health
        changed = True
    if target_health_msg is not None:
        clean_msg = str(target_health_msg).strip()[:255]
        if clean_msg != device.health_message:
            device.health_message = clean_msg
            changed = True
    elif device.health_status == HealthStatus.HEALTHY and device.health_message:
        device.health_message = ""
        changed = True

    if bump_heartbeat is None:
        bump_heartbeat = device.connection_status == ConnectionStatus.ONLINE and reason != "lan power probe"
    if bump_heartbeat:
        device.last_heartbeat_at = now

    update_fields = [
        "status",
        "connection_status",
        "power_status",
        "kiosk_status",
        "occupancy_status",
        "health_status",
        "health_message",
        "last_power_change_at",
        "last_heartbeat_at",
        "ip_address",
        "application_version",
        "updated_at",
    ]
    if mac_updated:
        update_fields.append("metadata")
    device.save(update_fields=update_fields)

    if device.connection_status == ConnectionStatus.OFFLINE and (
        prev_conn != ConnectionStatus.OFFLINE or has_active_session
    ):
        handle_device_disconnect(device, now=now)
    elif device.connection_status == ConnectionStatus.ONLINE and prev_conn != ConnectionStatus.ONLINE:
        handle_device_reconnect(device, now=now)

    if mac_updated:
        emit(
            "device.updated",
            aggregate_type="device",
            aggregate_id=str(device.id),
            payload={
                "device_id": str(device.id),
                "name": device.name,
                "metadata": device.metadata,
                "is_active": device.is_active,
            },
        )
    if changed or any(
        [
            device.connection_status != prev_conn,
            device.power_status != prev_power,
            device.kiosk_status != prev_kiosk,
            device.occupancy_status != prev_occ,
            device.health_status != prev_health,
            device.health_message != prev_health_msg,
        ]
    ):
        emit(
            "device.status_changed",
            aggregate_type="device",
            aggregate_id=str(device.id),
            payload=_status_payload(device, now, reason),
        )
    return changed


@transaction.atomic
def update_device_power(
    device: ClientDevice,
    power_status: str,
    *,
    reason: str = "lan power probe",
) -> bool:
    """Update only power_status on an offline/stale device without overwriting other states."""
    require_edge()
    if power_status not in PowerStatus.values:
        return False
    device = ClientDevice.objects.select_for_update().get(pk=device.pk)
    if device.power_status == power_status:
        return False
    now = timezone.now()
    device.power_status = power_status
    device.last_power_change_at = now
    device.save(update_fields=["power_status", "last_power_change_at", "updated_at"])
    emit(
        "device.status_changed",
        aggregate_type="device",
        aggregate_id=str(device.id),
        payload=_status_payload(device, now, reason),
    )
    return True


@transaction.atomic
def reset_device_pairing(device: ClientDevice, *, actor=None, notify_client: bool = True) -> None:
    """Clear client credentials and hardware binding so the slot is ready for a new PC."""
    require_edge()
    from apps.sessions.models import GamingSession, SessionStatus
    from apps.synchronization.command_service import queue_device_command

    device = ClientDevice.objects.select_for_update().get(pk=device.pk)
    if GamingSession.objects.filter(device=device, status=SessionStatus.ACTIVE).exists():
        raise RegistrationError("ابتدا نشست بازی فعال روی این سیستم را پایان دهید.")

    had_token = bool(device.token_hash)
    if notify_client and had_token:
        try:
            queue_device_command(device, "client.unpair", {"reason": "admin_reset"}, actor=actor)
        except Exception:
            logger.debug("Could not enqueue client.unpair during reset of %s", device.name)

    meta = dict(device.metadata or {})
    for key in ("mac_address", "active_app", "current_game", "foreground_window"):
        meta.pop(key, None)

    device.token_hash = ""
    device.token_issued_at = None
    device.hostname = ""
    device.ip_address = None
    device.operating_system = ""
    device.application_version = ""
    device.status = ClientStatus.OFFLINE
    device.connection_status = ConnectionStatus.OFFLINE
    device.power_status = PowerStatus.UNKNOWN
    device.kiosk_status = KioskStatus.LOCKED
    device.occupancy_status = OccupancyStatus.FREE
    device.health_status = HealthStatus.HEALTHY
    device.health_message = ""
    device.metadata = meta
    device.save(
        update_fields=[
            "token_hash",
            "token_issued_at",
            "hostname",
            "ip_address",
            "operating_system",
            "application_version",
            "status",
            "connection_status",
            "power_status",
            "kiosk_status",
            "occupancy_status",
            "health_status",
            "health_message",
            "metadata",
            "updated_at",
        ]
    )
    emit(
        "device.updated",
        aggregate_type="device",
        aggregate_id=str(device.id),
        payload={
            "device_id": str(device.id),
            "name": device.name,
            "metadata": device.metadata,
            "is_active": device.is_active,
        },
    )
    emit(
        "device.status_changed",
        aggregate_type="device",
        aggregate_id=str(device.id),
        payload=_status_payload(device, timezone.now(), "device reset"),
    )


@transaction.atomic
def deactivate_device(device: ClientDevice, *, actor=None) -> None:
    require_edge()
    from apps.sessions.models import GamingSession, SessionStatus
    from apps.synchronization.command_service import queue_device_command

    device = ClientDevice.objects.select_for_update().get(pk=device.pk)
    if GamingSession.objects.filter(device=device, status=SessionStatus.ACTIVE).exists():
        raise RegistrationError("ابتدا نشست بازی فعال روی این سیستم را پایان دهید.")

    if device.token_hash:
        try:
            queue_device_command(device, "client.unpair", {"reason": "device_deleted"}, actor=actor)
        except Exception:
            logger.debug("Could not enqueue client.unpair during deactivate of %s", device.name)

    meta = dict(device.metadata or {})
    meta.pop("mac_address", None)
    device.token_hash = ""
    device.token_issued_at = None
    device.hostname = ""
    device.ip_address = None
    device.is_active = False
    device.status = ClientStatus.OFFLINE
    device.connection_status = ConnectionStatus.OFFLINE
    device.power_status = PowerStatus.UNKNOWN
    device.kiosk_status = KioskStatus.LOCKED
    device.occupancy_status = OccupancyStatus.FREE
    device.metadata = meta
    device.save(
        update_fields=[
            "token_hash",
            "token_issued_at",
            "hostname",
            "ip_address",
            "is_active",
            "status",
            "connection_status",
            "power_status",
            "kiosk_status",
            "occupancy_status",
            "metadata",
            "updated_at",
        ]
    )
    emit(
        "device.deactivated",
        aggregate_type="device",
        aggregate_id=str(device.id),
        payload={"device_id": str(device.id)},
    )


@transaction.atomic
def create_station(
    name: str,
    *,
    idle_shutdown_minutes: int = 15,
    tariff_id: str = "",
) -> ClientDevice:
    require_edge()
    identity = ensure_identity()
    clean_name = normalize_station_name(name)
    if not clean_name:
        raise RegistrationError("نام یا شماره ایستگاه الزامی است.")

    existing = ClientDevice.objects.select_for_update().filter(
        edge_id=identity.edge_id, name=clean_name
    ).first()
    meta: dict[str, Any] = {"idle_shutdown_minutes": max(0, min(720, int(idle_shutdown_minutes)))}
    if tariff_id:
        meta["default_tariff_id"] = str(tariff_id).strip()

    if existing is not None:
        if existing.is_active:
            raise RegistrationError(f"ایستگاهی با نام «{clean_name}» از قبل وجود دارد.")
        existing.is_active = True
        existing.token_hash = ""
        existing.token_issued_at = None
        existing.hostname = ""
        existing.ip_address = None
        existing.status = ClientStatus.OFFLINE
        existing.connection_status = ConnectionStatus.OFFLINE
        existing.power_status = PowerStatus.UNKNOWN
        existing.kiosk_status = KioskStatus.LOCKED
        existing.occupancy_status = OccupancyStatus.FREE
        existing.health_status = HealthStatus.HEALTHY
        existing.health_message = ""
        existing.metadata = meta
        existing.save()
        device = existing
    else:
        device = ClientDevice.objects.create(
            edge_id=identity.edge_id,
            name=clean_name,
            status=ClientStatus.OFFLINE,
            connection_status=ConnectionStatus.OFFLINE,
            power_status=PowerStatus.UNKNOWN,
            kiosk_status=KioskStatus.LOCKED,
            occupancy_status=OccupancyStatus.FREE,
            is_active=True,
            metadata=meta,
            registered_at=timezone.now(),
        )

    emit(
        "device.updated",
        aggregate_type="device",
        aggregate_id=str(device.id),
        payload={
            "device_id": str(device.id),
            "name": device.name,
            "metadata": device.metadata,
            "is_active": device.is_active,
        },
    )
    return device


def mark_stale_devices_offline(now=None) -> int:
    """Heartbeat + LAN power watchdog. Runs on the edge worker every few seconds."""
    from django.db.models import Q
    from apps.devices.wol import is_lan_host_reachable
    import time

    require_edge()
    now = now or timezone.now()
    cfg = _runtime_heartbeat()
    threshold = now - timedelta(seconds=cfg[0] * cfg[1])
    stale = ClientDevice.objects.filter(
        is_active=True, last_heartbeat_at__lt=threshold
    ).filter(
        Q(connection_status=ConnectionStatus.ONLINE)
        | ~Q(status__in=[ClientStatus.OFFLINE, ClientStatus.MAINTENANCE])
    )
    count = 0
    for device in stale:
        reachable = is_lan_host_reachable(device.ip_address)
        set_status(
            device,
            ClientStatus.OFFLINE,
            force=True,
            connection_status=ConnectionStatus.OFFLINE,
            power_status=PowerStatus.ON if reachable else PowerStatus.OFF,
            bump_heartbeat=False,
            reason="heartbeat timeout",
        )
        _LAN_PROBE_CACHE[str(device.id)] = time.monotonic()
        count += 1

    # Periodically probe offline devices that have a known LAN IP so "روشن ولی آفلاین" stays accurate
    mono_now = time.monotonic()
    offline_with_ip = ClientDevice.objects.filter(
        is_active=True,
        connection_status=ConnectionStatus.OFFLINE,
        ip_address__isnull=False,
    )
    for device in offline_with_ip:
        key = str(device.id)
        if mono_now - _LAN_PROBE_CACHE.get(key, 0.0) < 20.0:
            continue
        _LAN_PROBE_CACHE[key] = mono_now
        reachable = is_lan_host_reachable(device.ip_address)
        desired_power = PowerStatus.ON if reachable else PowerStatus.OFF
        if device.power_status != desired_power:
            update_device_power(device, desired_power, reason="lan power probe")

    return count


def _runtime_heartbeat() -> tuple[int, int]:
    from apps.synchronization.config import current_config

    cfg = current_config()
    return (
        int(cfg.get("device_heartbeat_seconds", settings.DEVICE_HEARTBEAT_SECONDS)),
        int(cfg.get("device_offline_after_missed", settings.DEVICE_OFFLINE_AFTER_MISSED)),
    )


def device_snapshot(device: ClientDevice) -> dict[str, Any]:
    return {
        "device_id": str(device.id),
        "name": device.name,
        "hostname": device.hostname,
        "ip_address": device.ip_address,
        "mac_address": (device.metadata or {}).get("mac_address", ""),
        "status": device.status,
        "connection_status": device.connection_status,
        "power_status": device.power_status,
        "kiosk_status": device.kiosk_status,
        "occupancy_status": device.occupancy_status,
        "health_status": device.health_status,
        "health_message": device.health_message,
        "last_power_change_at": (
            device.last_power_change_at.isoformat() if device.last_power_change_at else None
        ),
        "application_version": device.application_version,
        "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
        "is_active": device.is_active,
    }

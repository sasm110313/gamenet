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

from apps.clients.models import ClientDevice, ClientStatus
from apps.core.roles import require_edge
from apps.core.security import constant_time_equal
from apps.devices.models import RegistrationCode
from apps.synchronization.crypto import hash_token
from apps.synchronization.edge_credentials import ensure_identity, load_credentials
from apps.synchronization.events import emit
from apps.synchronization.models import EdgeIdentity

logger = logging.getLogger("gamenet.devices")

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


@transaction.atomic
def register_device(
    *,
    code: str,
    name: str,
    hostname: str = "",
    operating_system: str = "",
    application_version: str = "",
    ip_address: str | None = None,
    device_id=None,
) -> tuple[ClientDevice, str]:
    """Pair a device and return its one-time plaintext token.

    The token is stored only as a SHA-256 hash; losing it means re-pairing.
    """
    require_edge()
    identity = ensure_identity()

    reg = (
        RegistrationCode.objects.select_for_update()
        .filter(code=(code or "").strip().upper())
        .first()
    )
    if reg is None or not reg.is_usable():
        raise RegistrationError("invalid or expired registration code")

    device: ClientDevice | None = None
    if device_id:
        device = ClientDevice.objects.select_for_update().filter(id=device_id).first()
        if device is not None and device.edge_id != identity.edge_id:
            raise RegistrationError("device belongs to another edge")

    token = secrets.token_urlsafe(32)
    if device is None:
        if ClientDevice.objects.filter(name=name, is_active=True).exists():
            raise RegistrationError("a device with this name already exists")
        device = ClientDevice(
            edge_id=identity.edge_id,
            name=name.strip()[:80],
            hostname=hostname[:120],
            operating_system=operating_system[:120],
            application_version=application_version[:40],
            ip_address=ip_address,
            status=ClientStatus.OFFLINE,
            registered_at=timezone.now(),
        )
    device.hostname = hostname[:120] or device.hostname
    device.operating_system = operating_system[:120] or device.operating_system
    device.application_version = application_version[:40] or device.application_version
    device.ip_address = ip_address or device.ip_address
    device.token_hash = hash_token(token)
    device.token_issued_at = timezone.now()
    device.save()

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
            "status": device.status,
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


@transaction.atomic
def set_status(
    device: ClientDevice,
    new_status: str,
    *,
    force: bool = False,
    app_version: str = "",
    ip_address: str | None = None,
    reason: str = "",
) -> bool:
    """Apply a presence transition. Emits only on actual change.

    A client may not promote itself out of LOCKED (Phase 1 will gate ACTIVE on a
    real session); the hub forces those states instead.
    """
    require_edge()
    device = ClientDevice.objects.select_for_update().get(pk=device.pk)
    now = timezone.now()
    device.last_heartbeat_at = now
    if ip_address:
        device.ip_address = ip_address
    if app_version:
        device.application_version = app_version[:40]

    changed = False
    HUB_ONLY = {ClientStatus.ACTIVE, ClientStatus.IDLE, ClientStatus.STARTING, ClientStatus.STOPPING}
    if new_status and new_status != device.status:
        may_report_active = False
        if new_status == ClientStatus.ACTIVE and not force:
            # A client may confirm ACTIVE only while the edge has a real session.
            from apps.sessions.models import GamingSession, SessionStatus

            may_report_active = GamingSession.objects.filter(
                device=device, status=SessionStatus.ACTIVE
            ).exists()
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
    device.save(update_fields=["status", "last_heartbeat_at", "ip_address",
                               "application_version", "updated_at"])
    if changed:
        emit(
            "device.status_changed",
            aggregate_type="device",
            aggregate_id=str(device.id),
            payload={
                "device_id": str(device.id),
                "status": device.status,
                "last_heartbeat_at": now.isoformat(),
                "application_version": device.application_version,
                "reason": reason,
            },
        )
    return changed


@transaction.atomic
def deactivate_device(device: ClientDevice) -> None:
    require_edge()
    device.is_active = False
    device.status = ClientStatus.OFFLINE
    device.save(update_fields=["is_active", "status", "updated_at"])
    emit(
        "device.deactivated",
        aggregate_type="device",
        aggregate_id=str(device.id),
        payload={"device_id": str(device.id)},
    )


def mark_stale_devices_offline(now=None) -> int:
    """Heartbeat watchdog. Runs on the edge worker every few seconds."""
    require_edge()
    now = now or timezone.now()
    cfg = _runtime_heartbeat()
    threshold = now - timedelta(seconds=cfg[0] * cfg[1])
    stale = ClientDevice.objects.filter(
        is_active=True, last_heartbeat_at__lt=threshold
    ).exclude(status__in=[ClientStatus.OFFLINE, ClientStatus.MAINTENANCE])
    count = 0
    for device in stale:
        set_status(device, ClientStatus.OFFLINE, force=True, reason="heartbeat timeout")
        count += 1
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
        "status": device.status,
        "application_version": device.application_version,
        "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
        "is_active": device.is_active,
    }

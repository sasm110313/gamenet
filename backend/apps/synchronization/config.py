"""Runtime configuration: cloud-published snapshot with safe local defaults."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction

from apps.synchronization.models import AppliedConfig

DEFAULTS: dict[str, Any] = {
    "device_heartbeat_seconds": 10,
    "device_offline_after_missed": 3,
    "default_hourly_rate": 40_000,
    "default_credit_limit": 60_000,
    "command_ttl_seconds": 120,
    "version": 0,
}


def current_config() -> dict[str, Any]:
    applied = AppliedConfig.objects.order_by("-version").first()
    if applied is None:
        cfg = dict(DEFAULTS)
        cfg["device_heartbeat_seconds"] = settings.DEVICE_HEARTBEAT_SECONDS
        cfg["device_offline_after_missed"] = settings.DEVICE_OFFLINE_AFTER_MISSED
        cfg["default_hourly_rate"] = settings.DEFAULT_HOURLY_RATE
        cfg["default_credit_limit"] = settings.DEFAULT_CREDIT_LIMIT
        cfg["command_ttl_seconds"] = settings.DEVICE_COMMAND_TTL_SECONDS
        return cfg
    merged = dict(DEFAULTS)
    merged.update(applied.payload)
    merged["version"] = applied.version
    return merged


@transaction.atomic
def apply_snapshot(*, version: int, content_hash: str, payload: dict) -> AppliedConfig:
    """Apply an already-validated snapshot atomically (idempotent by version)."""
    existing = AppliedConfig.objects.filter(version=version, content_hash=content_hash).first()
    if existing:
        return existing
    if AppliedConfig.objects.filter(version=version).exists():
        raise ValueError(f"config v{version} exists with a different hash")
    applied = AppliedConfig.objects.create(version=version, content_hash=content_hash, payload=payload)
    # The event is what tells the cloud "this edge is now running vN".
    from apps.synchronization.events import emit

    emit(
        "config.applied",
        aggregate_type="config",
        aggregate_id=str(version),
        payload={"version": version, "content_hash": content_hash},
    )
    return applied

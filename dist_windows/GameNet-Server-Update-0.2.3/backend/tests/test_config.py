from __future__ import annotations

import pytest

from apps.synchronization.config import apply_snapshot, current_config
from apps.synchronization.models import AppliedConfig, OutboxEvent


@pytest.mark.django_db
def test_defaults_are_local_and_sane(identity) -> None:
    cfg = current_config()
    assert cfg["version"] == 0
    assert cfg["default_hourly_rate"] == 40_000
    assert cfg["default_credit_limit"] == 60_000
    assert cfg["device_heartbeat_seconds"] >= 1


@pytest.mark.django_db
def test_apply_snapshot_is_atomic_and_reported(identity) -> None:
    applied = apply_snapshot(
        version=1,
        content_hash="abc",
        payload={"device_heartbeat_seconds": 5, "default_hourly_rate": 45_000},
    )

    assert AppliedConfig.objects.count() == 1
    assert applied.version == 1
    cfg = current_config()
    assert cfg["device_heartbeat_seconds"] == 5
    assert cfg["default_hourly_rate"] == 45_000
    event = OutboxEvent.objects.get(event_type="config.applied")
    assert event.payload == {"version": 1, "content_hash": "abc"}


@pytest.mark.django_db
def test_apply_snapshot_is_idempotent(identity) -> None:
    first = apply_snapshot(version=2, content_hash="h", payload={"a": 1})
    second = apply_snapshot(version=2, content_hash="h", payload={"a": 1})

    assert first.pk == second.pk
    assert OutboxEvent.objects.filter(event_type="config.applied").count() == 1


@pytest.mark.django_db
def test_same_version_with_different_content_is_refused(identity) -> None:
    apply_snapshot(version=3, content_hash="h1", payload={"a": 1})
    with pytest.raises(ValueError, match="different hash"):
        apply_snapshot(version=3, content_hash="h2", payload={"a": 2})

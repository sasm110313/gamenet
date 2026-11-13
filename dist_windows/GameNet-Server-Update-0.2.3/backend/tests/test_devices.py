from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.devices.models import RegistrationCode
from apps.devices.services import (
    RegistrationError,
    authenticate_device,
    create_registration_code,
    deactivate_device,
    mark_stale_devices_offline,
    register_device,
    set_status,
)
from apps.synchronization.crypto import hash_token
from apps.synchronization.models import OutboxEvent


def _register(name: str = "PC-01"):
    code = create_registration_code(label=name)
    return register_device(
        code=code.code,
        name=name,
        hostname=f"WIN7-{name}",
        operating_system="Windows 7 SP1 x64",
        application_version="0.1.0",
        ip_address="192.168.1.20",
    )


@pytest.mark.django_db
def test_registration_code_is_one_time(identity) -> None:
    code = create_registration_code(label="PC-01")
    assert len(code.code) == 8
    assert code.is_usable()

    device, token = register_device(code=code.code, name="PC-01")

    code.refresh_from_db()
    assert code.used_at is not None
    assert code.used_by_id == device.id
    assert token
    assert device.token_hash == hash_token(token)
    assert token not in device.token_hash


@pytest.mark.django_db
def test_registration_rejects_expired_and_reused_codes(identity) -> None:
    code = create_registration_code(label="PC-01")
    register_device(code=code.code, name="PC-01")

    with pytest.raises(RegistrationError, match="invalid or expired"):
        register_device(code=code.code, name="PC-02")

    expired = create_registration_code(label="PC-03")
    RegistrationCode.objects.filter(pk=expired.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    with pytest.raises(RegistrationError, match="invalid or expired"):
        register_device(code=expired.code, name="PC-03")


@pytest.mark.django_db
def test_duplicate_device_name_is_refused(identity) -> None:
    _register("PC-01")
    code = create_registration_code()
    with pytest.raises(RegistrationError, match="already exists"):
        register_device(code=code.code, name="PC-01")


@pytest.mark.django_db
def test_registration_emits_outbox_event_in_same_transaction(identity) -> None:
    device, _ = _register("PC-01")

    event = OutboxEvent.objects.get(event_type="device.registered")
    assert event.aggregate_id == str(device.id)
    assert event.payload["name"] == "PC-01"
    assert event.edge_id == identity.edge_id


@pytest.mark.django_db
def test_authenticate_device(identity) -> None:
    device, token = _register("PC-01")

    assert authenticate_device(device.id, token).id == device.id
    assert authenticate_device(device.id, token + "x") is None
    assert authenticate_device(device.id, "") is None
    assert authenticate_device("not-a-uuid", token) is None


@pytest.mark.django_db
def test_status_transitions_are_guarded_and_emitted(identity) -> None:
    device, _ = _register("PC-01")

    assert set_status(device, ClientStatus.ONLINE, force=True) is True
    assert set_status(device, ClientStatus.LOCKED) is True
    # A client may not promote itself into an active session.
    assert set_status(device, ClientStatus.ACTIVE) is False
    assert set_status(device, ClientStatus.ACTIVE, force=True) is True

    statuses = list(
        OutboxEvent.objects.filter(event_type="device.status_changed")
        .order_by("local_sequence")
        .values_list("payload__status", flat=True)
    )
    assert statuses == ["ONLINE", "LOCKED", "ACTIVE"]
    device.refresh_from_db()
    assert device.status == ClientStatus.ACTIVE


@pytest.mark.django_db
def test_heartbeat_updates_without_emitting_when_status_is_unchanged(identity) -> None:
    device, _ = _register("PC-01")
    set_status(device, ClientStatus.ONLINE, force=True)
    before = OutboxEvent.objects.count()

    set_status(device, ClientStatus.ONLINE, app_version="0.1.1")

    assert OutboxEvent.objects.count() == before
    device.refresh_from_db()
    assert device.application_version == "0.1.1"
    assert device.last_heartbeat_at is not None


@pytest.mark.django_db
def test_deactivate_device_removes_it_from_service(identity) -> None:
    device, _ = _register("PC-01")
    deactivate_device(device)

    device.refresh_from_db()
    assert device.is_active is False
    assert device.status == ClientStatus.OFFLINE
    assert OutboxEvent.objects.filter(event_type="device.deactivated").exists()
    # A revoked device token can no longer authenticate.
    assert authenticate_device(device.id, "anything") is None


@pytest.mark.django_db
def test_stale_devices_go_offline(identity) -> None:
    device, _ = _register("PC-01")
    set_status(device, ClientStatus.ONLINE, force=True)
    ClientDevice.objects.filter(pk=device.pk).update(
        last_heartbeat_at=timezone.now() - timedelta(minutes=10)
    )

    count = mark_stale_devices_offline()

    assert count == 1
    device.refresh_from_db()
    assert device.status == ClientStatus.OFFLINE
    assert OutboxEvent.objects.filter(
        event_type="device.status_changed", payload__status="OFFLINE"
    ).exists()

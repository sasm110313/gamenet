from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import DeviceCommand, DeviceCommandStatus
from apps.devices.models import RegistrationCode
from apps.devices.services import create_registration_code
from apps.synchronization.crypto import hash_token
from apps.synchronization.models import OutboxEvent


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_device_registration_over_http(api, synced_identity) -> None:
    code = create_registration_code(label="PC-09")

    response = api.post(
        "/api/v1/device/register",
        {
            "code": code.code,
            "name": "PC-09",
            "hostname": "WIN7-PC09",
            "operating_system": "Windows 7 SP1 x64",
            "application_version": "0.1.0",
        },
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["device_id"]
    assert body["token"]
    assert body["ws_path"] == "/ws/device/"
    assert body["cloud_registered"] is True
    assert isinstance(body["device_heartbeat_seconds"], int)
    assert ClientDevice.objects.filter(id=body["device_id"]).exists()
    assert OutboxEvent.objects.filter(event_type="device.registered").exists()


@pytest.mark.django_db
def test_bad_registration_code_is_rejected(api, identity) -> None:
    response = api.post(
        "/api/v1/device/register",
        {"code": "NOPE1234", "name": "PC-10"},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "registration_failed"


@pytest.mark.django_db
def test_heartbeat_requires_device_credentials(api, identity) -> None:
    response = api.post("/api/v1/device/heartbeat", {"state": "LOCKED"}, format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_heartbeat_and_me(api, device) -> None:
    api.credentials(HTTP_AUTHORIZATION=f"Device {device.id}.{device._plain_token}")

    # OFFLINE -> ONLINE -> LOCKED: the API only accepts legal presence moves.
    online = api.post("/api/v1/device/heartbeat", {"state": "ONLINE"}, format="json")
    assert online.status_code == 200
    assert online.json()["desired_state"] == ClientStatus.ONLINE

    response = api.post(
        "/api/v1/device/heartbeat",
        {"state": "LOCKED", "app_version": "0.1.2"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["desired_state"] == ClientStatus.LOCKED
    assert body["config_version"] == 0
    device.refresh_from_db()
    assert device.application_version == "0.1.2"
    assert device.status == ClientStatus.LOCKED

    me = api.get("/api/v1/device/me")
    assert me.status_code == 200
    assert me.json()["device"]["device_id"] == str(device.id)


@pytest.mark.django_db
def test_pending_commands_and_acknowledgement(api, device) -> None:
    api.credentials(HTTP_AUTHORIZATION=f"Device {device.id}.{device._plain_token}")
    command = DeviceCommand.objects.create(
        client=device,
        command_type="client.lock",
        expires_at=timezone.now() + timedelta(seconds=60),
    )
    expired = DeviceCommand.objects.create(
        client=device,
        command_type="client.unlock",
        expires_at=timezone.now() - timedelta(seconds=1),
        status=DeviceCommandStatus.PENDING,
    )

    pending = api.get("/api/v1/device/commands/pending")
    assert pending.status_code == 200
    ids = [item["command_id"] for item in pending.json()["commands"]]
    assert str(command.id) in ids
    assert str(expired.id) not in ids

    ack = api.post(
        f"/api/v1/device/commands/{command.id}/ack",
        {"status": "ok", "result": {"locked": True}},
        format="json",
    )
    assert ack.status_code == 200
    command.refresh_from_db()
    assert command.status == DeviceCommandStatus.ACKNOWLEDGED
    assert command.result == {"locked": True}

    unknown = api.post(
        f"/api/v1/device/commands/{uuid.uuid4()}/ack", {"status": "ok"}, format="json"
    )
    assert unknown.status_code == 404


@pytest.mark.django_db
def test_device_from_another_edge_is_rejected(api, identity) -> None:
    foreign = ClientDevice.objects.create(
        edge_id=uuid.uuid4(),
        name="FOREIGN",
        token_hash=hash_token("tok"),
        status=ClientStatus.LOCKED,
    )
    api.credentials(HTTP_AUTHORIZATION=f"Device {foreign.id}.tok")
    response = api.get("/api/v1/device/me")
    assert response.status_code == 401

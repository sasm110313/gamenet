from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commands.models import (
    CommandStatus,
    DeviceCommand,
    DeviceCommandStatus,
    InboundCommandStatus,
    InboundRemoteCommand,
    RemoteCommand,
)
from apps.synchronization.command_service import (
    acknowledge_device_command,
    execute_command,
    issue_command,
    receive_command,
)
from apps.synchronization.models import OutboxEvent


@pytest.fixture
def cloud(settings):
    settings.GAMENET_ROLE = "cloud"
    return settings


@pytest.mark.django_db
def test_issued_command_is_signed_and_expires(cloud, edge_node) -> None:
    command = issue_command(edge_node, "edge.ping", {"a": 1}, push=False)

    assert command.signature
    assert command.nonce
    assert command.expires_at > command.issued_at
    envelope = command.envelope()
    assert envelope["edge_id"] == str(edge_node.id)
    assert envelope["payload"] == {"a": 1}
    assert set(envelope) == {
        "command_id",
        "edge_id",
        "command_type",
        "payload",
        "issued_at",
        "expires_at",
        "nonce",
    }


@pytest.mark.django_db
def test_unknown_command_type_is_refused(cloud, edge_node) -> None:
    with pytest.raises(ValueError, match="unsupported command type"):
        issue_command(edge_node, "edge.format_disk", push=False)


@pytest.mark.django_db
def test_receive_verifies_and_stores_once(cloud, edge_node, synced_identity) -> None:
    cloud.GAMENET_ROLE = "cloud"
    command = issue_command(edge_node, "edge.ping", push=False)

    cloud.GAMENET_ROLE = "edge"
    row, is_new = receive_command({**command.envelope(), "signature": command.signature})

    assert is_new is True
    assert row.command_id == command.id
    assert row.status == InboundCommandStatus.RECEIVED

    # A replay is remembered, never re-executed and never duplicated.
    again, is_new_again = receive_command({**command.envelope(), "signature": command.signature})
    assert is_new_again is False
    assert again.pk == row.pk
    assert InboundRemoteCommand.objects.filter(command_id=command.id).count() == 1


@pytest.mark.django_db
def test_tampered_payload_fails_signature(cloud, edge_node, synced_identity) -> None:
    command = issue_command(edge_node, "edge.ping", {"a": 1}, push=False)
    cloud.GAMENET_ROLE = "edge"
    envelope = {**command.envelope(), "signature": command.signature}
    envelope["payload"] = {"a": 2}

    with pytest.raises(ValueError, match="bad command signature"):
        receive_command(envelope)
    assert InboundRemoteCommand.objects.count() == 0


@pytest.mark.django_db
def test_command_for_another_edge_is_refused(cloud, edge_node, synced_identity) -> None:
    command = issue_command(edge_node, "edge.ping", push=False)
    cloud.GAMENET_ROLE = "edge"
    envelope = {**command.envelope(), "signature": command.signature}
    envelope["edge_id"] = str(uuid.uuid4())

    with pytest.raises(ValueError, match="different edge"):
        receive_command(envelope)


@pytest.mark.django_db
def test_expired_command_is_recorded_but_not_executable(cloud, edge_node, synced_identity) -> None:
    command = issue_command(edge_node, "edge.ping", ttl_seconds=-1, push=False)
    cloud.GAMENET_ROLE = "edge"

    row, is_new = receive_command({**command.envelope(), "signature": command.signature})

    assert is_new is True
    assert row.status == InboundCommandStatus.EXPIRED
    assert execute_command(command.id) == {"status": "already_handled"}


@pytest.mark.django_db
def test_execute_is_exactly_once(cloud, edge_node, synced_identity) -> None:
    command = issue_command(edge_node, "edge.ping", push=False)
    cloud.GAMENET_ROLE = "edge"
    receive_command({**command.envelope(), "signature": command.signature})

    first = execute_command(command.id)
    second = execute_command(command.id)

    assert first["status"] == "succeeded"
    assert first["result"]["pong"] is True
    assert second == {"status": "already_handled"}
    assert OutboxEvent.objects.filter(event_type="command.result").count() == 1


@pytest.mark.django_db
def test_test_event_command_creates_a_real_outbox_event(cloud, edge_node, synced_identity) -> None:
    command = issue_command(edge_node, "edge.test_event", {"note": "from cloud"}, push=False)
    cloud.GAMENET_ROLE = "edge"
    receive_command({**command.envelope(), "signature": command.signature})

    result = execute_command(command.id)

    assert result["status"] == "succeeded"
    event = OutboxEvent.objects.get(event_type="edge.test")
    assert event.payload["note"] == "from cloud"
    assert result["result"]["event_id"] == str(event.event_id)


@pytest.mark.django_db
def test_device_command_is_forwarded_then_acknowledged(cloud, edge_node, synced_identity, device) -> None:
    command = issue_command(
        edge_node, "client.lock", {"device_id": str(device.id)}, push=False
    )
    cloud.GAMENET_ROLE = "edge"
    receive_command({**command.envelope(), "signature": command.signature})

    result = execute_command(command.id)

    assert result["status"] == "forwarded"
    device_command = DeviceCommand.objects.get(client=device)
    assert device_command.command_type == "client.lock"
    assert device_command.status == DeviceCommandStatus.PENDING
    forwarded = OutboxEvent.objects.get(event_type="command.result")
    assert forwarded.payload["status"] == "forwarded"

    acknowledge_device_command(device, str(device_command.id), status="ok", result={"locked": True})

    device_command.refresh_from_db()
    assert device_command.status == DeviceCommandStatus.ACKNOWLEDGED
    assert device_command.result == {"locked": True}
    final = OutboxEvent.objects.filter(event_type="command.result").order_by("-local_sequence").first()
    assert final.payload["status"] == "succeeded"


@pytest.mark.django_db
def test_device_command_for_unknown_device_fails_cleanly(cloud, edge_node, synced_identity) -> None:
    command = issue_command(
        edge_node, "client.lock", {"device_id": str(uuid.uuid4())}, push=False
    )
    cloud.GAMENET_ROLE = "edge"
    receive_command({**command.envelope(), "signature": command.signature})

    result = execute_command(command.id)

    assert result["status"] == "failed"
    assert "unknown or inactive device" in result["error"]
    row = InboundRemoteCommand.objects.get(command_id=command.id)
    assert row.status == InboundCommandStatus.FAILED


@pytest.mark.django_db
def test_device_cannot_be_commanded_while_in_maintenance(cloud, edge_node, synced_identity, device) -> None:
    device.status = "MAINTENANCE"
    device.save(update_fields=["status"])
    command = issue_command(
        edge_node, "client.lock", {"device_id": str(device.id)}, push=False
    )
    cloud.GAMENET_ROLE = "edge"
    receive_command({**command.envelope(), "signature": command.signature})

    result = execute_command(command.id)

    assert result["status"] == "failed"
    assert "maintenance" in result["error"]

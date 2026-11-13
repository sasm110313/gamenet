from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import CommandStatus, RemoteCommand
from apps.core.ids import uuid7
from apps.synchronization.ingest import InvalidEvent, ingest_batch
from apps.synchronization.models import SyncEvent, SyncEventStatus


@pytest.fixture
def cloud(settings):
    settings.GAMENET_ROLE = "cloud"
    return settings


def _event(sequence: int = 1, **overrides) -> dict:
    base = {
        "event_id": str(uuid7()),
        "local_sequence": sequence,
        "event_type": "edge.test",
        "aggregate_type": "edge",
        "aggregate_id": "agg-1",
        "schema_version": 1,
        "occurred_at": timezone.now().isoformat(),
        "payload": {"note": "hi"},
    }
    base.update(overrides)
    return base


@pytest.mark.django_db
def test_ingest_applies_and_advances_watermark(cloud, edge_node) -> None:
    raw = _event(7)

    result = ingest_batch(edge_node, [raw])

    assert result["accepted"] == [raw["event_id"]]
    assert result["duplicates"] == []
    assert result["rejected"] == []
    assert result["watermark"] == 7
    record = SyncEvent.objects.get(event_id=raw["event_id"])
    assert record.status == SyncEventStatus.APPLIED
    assert record.applied_at is not None
    edge_node.refresh_from_db()
    assert edge_node.last_acked_sequence == 7
    assert edge_node.last_sync_at is not None


@pytest.mark.django_db
def test_duplicate_event_id_is_not_reapplied(cloud, edge_node) -> None:
    raw = _event(1)
    ingest_batch(edge_node, [raw])

    result = ingest_batch(edge_node, [raw])

    assert result["duplicates"] == [raw["event_id"]]
    assert result["accepted"] == []
    assert SyncEvent.objects.filter(event_id=raw["event_id"]).count() == 1
    assert SyncEvent.objects.get(event_id=raw["event_id"]).payload == {"note": "hi"}


@pytest.mark.django_db
def test_reused_sequence_with_new_event_id_is_rejected(cloud, edge_node) -> None:
    ingest_batch(edge_node, [_event(1)])

    result = ingest_batch(edge_node, [_event(1)])

    assert result["rejected"][0]["reason"] == "sequence already used"
    assert result["accepted"] == []


@pytest.mark.django_db
def test_per_aggregate_regression_is_rejected(cloud, edge_node) -> None:
    ingest_batch(edge_node, [_event(5)])

    result = ingest_batch(edge_node, [_event(3)])

    assert result["rejected"][0]["reason"] == "older than applied event"
    assert SyncEvent.objects.filter(local_sequence=3).exists() is False


@pytest.mark.django_db
def test_gaps_in_sequence_are_allowed(cloud, edge_node) -> None:
    # A rolled-back edge transaction consumes a sequence number locally.
    result = ingest_batch(edge_node, [_event(4)])
    assert result["accepted"]


@pytest.mark.django_db
def test_structural_errors_are_reported_per_event(cloud, edge_node) -> None:
    good = _event(2)
    result = ingest_batch(
        edge_node,
        [
            {"event_id": "not-a-uuid"},
            _event(1, schema_version=99),
            _event(2, payload="nope"),
            good,
        ],
    )

    assert result["accepted"] == [good["event_id"]]
    assert len(result["rejected"]) == 3
    reasons = " ".join(item["reason"] for item in result["rejected"])
    assert "missing fields" in reasons
    assert "unsupported schema_version" in reasons
    assert "payload must be an object" in reasons


@pytest.mark.django_db
def test_naive_timestamp_is_rejected(cloud, edge_node) -> None:
    result = ingest_batch(edge_node, [_event(1, occurred_at="2026-01-01T00:00:00")])
    assert result["rejected"][0]["reason"] == "occurred_at must be timezone-aware"


@pytest.mark.django_db
def test_batch_must_be_a_list(cloud, edge_node) -> None:
    with pytest.raises(InvalidEvent):
        ingest_batch(edge_node, {"events": []})


@pytest.mark.django_db
def test_device_registered_projects_into_cloud_replica(cloud, edge_node) -> None:
    device_id = uuid7()
    raw = _event(
        1,
        event_type="device.registered",
        aggregate_type="device",
        aggregate_id=str(device_id),
        payload={
            "device_id": str(device_id),
            "name": "PC-07",
            "hostname": "WIN7-07",
            "operating_system": "Windows 7 SP1 x64",
            "application_version": "0.1.0",
            "status": "OFFLINE",
            "registered_at": timezone.now().isoformat(),
        },
    )

    ingest_batch(edge_node, [raw])

    device = ClientDevice.objects.get(id=device_id)
    assert device.name == "PC-07"
    assert device.is_replica is True
    assert device.edge_id == edge_node.id


@pytest.mark.django_db
def test_device_status_projection(cloud, edge_node) -> None:
    device_id = uuid7()
    ingest_batch(
        edge_node,
        [
            _event(
                1,
                event_type="device.registered",
                aggregate_type="device",
                aggregate_id=str(device_id),
                payload={"device_id": str(device_id), "name": "PC-08", "status": "OFFLINE"},
            ),
            _event(
                2,
                event_type="device.status_changed",
                aggregate_type="device",
                aggregate_id=str(device_id),
                payload={"device_id": str(device_id), "status": "LOCKED"},
            ),
        ],
    )
    assert ClientDevice.objects.get(id=device_id).status == ClientStatus.LOCKED


@pytest.mark.django_db
def test_command_result_mapping_including_forwarded(cloud, edge_node) -> None:
    from apps.synchronization.crypto import generate_command_keypair

    public_key, encrypted = generate_command_keypair()
    command = RemoteCommand.objects.create(
        edge=edge_node,
        command_type="client.lock",
        expires_at=timezone.now() + timezone.timedelta(minutes=1),
        nonce=uuid.uuid4().hex,
        signature="sig",
        status=CommandStatus.PENDING,
    )

    def result(seq: int, status: str) -> dict:
        return _event(
            seq,
            event_type="command.result",
            aggregate_type="remote_command",
            aggregate_id=str(command.id),
            payload={"command_id": str(command.id), "status": status, "result": {}},
        )

    ingest_batch(edge_node, [result(1, "forwarded")])
    command.refresh_from_db()
    assert command.status == CommandStatus.SENT
    assert command.acknowledged_at is None

    ingest_batch(edge_node, [result(2, "succeeded")])
    command.refresh_from_db()
    assert command.status == CommandStatus.ACKNOWLEDGED
    assert command.acknowledged_at is not None

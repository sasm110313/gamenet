from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clients.models import ClientDevice
from apps.commands.models import CommandStatus, RemoteCommand
from apps.synchronization.models import (
    ConfigSnapshot,
    EdgeNode,
    EdgeRegistrationCode,
    EdgeStatus,
    SyncEvent,
)


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def cloud(settings):
    settings.GAMENET_ROLE = "cloud"
    settings.ROOT_URLCONF = "gamenet.urls_cloud"
    return settings


def _edge_auth(edge: EdgeNode) -> dict:
    return {"HTTP_AUTHORIZATION": f"Edge {edge.id}.{edge._plain_secret}"}


@pytest.mark.django_db
def test_edge_registration_and_secret_rotation(api, cloud, django_user_model) -> None:
    admin = django_user_model.objects.create_user("bootstrap", password="x")
    code = EdgeRegistrationCode.objects.create(
        code="TESTCODE",
        note="unit",
        created_by=admin,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    payload = {"code": "TESTCODE", "name": "Unit Floor", "software_version": "0.1.0"}

    first = api.post("/api/v1/edge/register", payload, format="json")

    assert first.status_code == 201
    body = first.json()
    edge_id = body["edge_id"]
    assert body["secret"]
    assert body["command_public_key"]
    edge = EdgeNode.objects.get(id=edge_id)
    assert edge.status == EdgeStatus.REGISTERED

    # Lost response: the same code + same edge id within 10 minutes rotates the
    # secret instead of bricking the site.
    retry = api.post(
        "/api/v1/edge/register", {**payload, "edge_id": edge_id}, format="json"
    )
    assert retry.status_code == 200
    assert retry.json()["secret"] != body["secret"]
    edge.refresh_from_db()
    assert edge.secret_hash == hashlib.sha256(retry.json()["secret"].encode()).hexdigest()

    # A different edge cannot reuse the code.
    other = api.post(
        "/api/v1/edge/register",
        {**payload, "edge_id": str(uuid.uuid4())},
        format="json",
    )
    assert other.status_code == 401
    code.refresh_from_db()
    assert code.used_at is not None


@pytest.mark.django_db
def test_expired_edge_code_is_rejected(api, cloud) -> None:
    EdgeRegistrationCode.objects.create(
        code="EXPIRED1",
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    response = api.post(
        "/api/v1/edge/register",
        {"code": "EXPIRED1", "name": "X"},
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_event_ingest_requires_edge_credentials(api, cloud, edge_node) -> None:
    response = api.post("/api/v1/edge/events:batch", {"events": []}, format="json")
    assert response.status_code == 401


@pytest.mark.django_db
def test_event_ingest_and_duplicate_replay(api, cloud, edge_node) -> None:
    event = {
        "event_id": str(uuid.uuid4()),
        "local_sequence": 1,
        "event_type": "edge.test",
        "aggregate_type": "edge",
        "aggregate_id": str(edge_node.id),
        "schema_version": 1,
        "occurred_at": timezone.now().isoformat(),
        "payload": {"note": "http"},
    }

    first = api.post(
        "/api/v1/edge/events:batch", {"events": [event]}, format="json", **_edge_auth(edge_node)
    )
    assert first.status_code == 200
    assert first.json()["accepted"] == [event["event_id"]]

    replay = api.post(
        "/api/v1/edge/events:batch", {"events": [event]}, format="json", **_edge_auth(edge_node)
    )
    assert replay.status_code == 200
    assert replay.json()["duplicates"] == [event["event_id"]]
    assert SyncEvent.objects.filter(edge=edge_node).count() == 1


@pytest.mark.django_db
def test_heartbeat_updates_replica_and_edge_state(api, cloud, edge_node) -> None:
    device = ClientDevice.objects.create(
        edge_id=edge_node.id,
        name="PC-01",
        status="ONLINE",
        is_replica=True,
    )
    response = api.post(
        "/api/v1/edge/heartbeat",
        {
            "devices": [{"device_id": str(device.id), "name": "PC-01", "status": "LOCKED"}],
            "software_version": "0.1.0",
            "last_acked_sequence": 4,
        },
        format="json",
        **_edge_auth(edge_node),
    )

    assert response.status_code == 200
    device.refresh_from_db()
    edge_node.refresh_from_db()
    assert device.status == "LOCKED"
    assert device.last_heartbeat_at is not None
    assert edge_node.status == EdgeStatus.ONLINE
    assert edge_node.last_acked_sequence == 4


@pytest.mark.django_db
def test_missing_device_in_heartbeat_goes_offline(api, cloud, edge_node) -> None:
    device = ClientDevice.objects.create(
        edge_id=edge_node.id, name="PC-01", status="ONLINE", is_replica=True
    )
    api.post(
        "/api/v1/edge/heartbeat",
        {"devices": []},
        format="json",
        **_edge_auth(edge_node),
    )
    device.refresh_from_db()
    assert device.status == "OFFLINE"


@pytest.mark.django_db
def test_pending_commands_are_delivered_with_signature(api, cloud, edge_node) -> None:
    live = RemoteCommand.objects.create(
        edge=edge_node,
        command_type="edge.ping",
        nonce=uuid.uuid4().hex,
        signature="sig",
        expires_at=timezone.now() + timedelta(minutes=1),
    )
    expired = RemoteCommand.objects.create(
        edge=edge_node,
        command_type="edge.ping",
        nonce=uuid.uuid4().hex,
        signature="sig",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    response = api.get("/api/v1/edge/commands/pending", **_edge_auth(edge_node))

    assert response.status_code == 200
    ids = [item["command_id"] for item in response.json()["commands"]]
    assert str(live.id) in ids
    assert str(expired.id) not in ids
    expired.refresh_from_db()
    assert expired.status == CommandStatus.EXPIRED


@pytest.mark.django_db
def test_config_endpoint_returns_versioned_snapshot(api, cloud, edge_node) -> None:
    payload = {"device_heartbeat_seconds": 10, "default_hourly_rate": 40_000}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    ConfigSnapshot.objects.create(version=1, payload=payload, content_hash=digest)

    first = api.get("/api/v1/edge/config?after=0", **_edge_auth(edge_node))
    assert first.status_code == 200
    body = first.json()
    assert body["up_to_date"] is False
    assert body["snapshot"]["version"] == 1
    assert body["snapshot"]["content_hash"] == digest

    second = api.get("/api/v1/edge/config?after=1", **_edge_auth(edge_node))
    assert second.json()["up_to_date"] is True

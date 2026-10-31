from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.db import connections

from apps.clients.models import ClientDevice
from apps.devices.consumers import DeviceConsumer
from apps.ingress.consumers import EdgeConsumer
from apps.synchronization.crypto import generate_command_keypair, hash_token, new_secret
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.models import EdgeIdentity, EdgeNode


def _create_device(name: str = "WS-01") -> tuple[str, str]:
    ensure_identity()
    identity = EdgeIdentity.objects.get(pk=1)
    token = new_secret()
    device = ClientDevice.objects.create(
        edge_id=identity.edge_id,
        name=name,
        hostname=name,
        token_hash=hash_token(token),
        status="OFFLINE",
    )
    return str(device.id), token


def _create_edge() -> tuple[str, str]:
    public_key, encrypted = generate_command_keypair()
    secret = new_secret()
    edge = EdgeNode.objects.create(
        name="WS Edge",
        secret_hash=hash_token(secret),
        command_public_key=public_key,
        command_private_key_enc=encrypted,
    )
    return str(edge.id), secret


async def _close_connections() -> None:
    # database_sync_to_async runs in the thread-sensitive executor; close that
    # thread's connection so the test database can be torn down cleanly.
    await sync_to_async(connections.close_all)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_device_websocket_handshake_heartbeat_and_state() -> None:
    device_id, token = await sync_to_async(_create_device)()
    communicator = WebsocketCommunicator(DeviceConsumer.as_asgi(), "/ws/device/")

    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to(
        {
            "type": "hello",
            "device_id": device_id,
            "token": token,
            "state": "LOCKED",
            "app_version": "0.1.0",
        }
    )
    welcome = await communicator.receive_json_from(timeout=5)
    assert welcome["type"] == "welcome"
    assert welcome["device_id"] == device_id
    hub_name = await sync_to_async(lambda: EdgeIdentity.objects.get(pk=1).name)()
    assert welcome["hub_name"] == hub_name
    assert welcome["desired_state"] == "LOCKED"
    assert welcome["heartbeat_seconds"] >= 1
    assert welcome["pending_commands"] == []

    await communicator.send_json_to(
        {"type": "heartbeat", "state": "LOCKED", "app_version": "0.1.0"}
    )
    ack = await communicator.receive_json_from(timeout=5)
    assert ack["type"] == "heartbeat_ack"
    assert "server_time" in ack

    await communicator.send_json_to({"type": "state", "state": "ONLINE"})
    state_ack = await communicator.receive_json_from(timeout=5)
    assert state_ack == {"type": "state_ack", "state": "ONLINE"}

    await communicator.disconnect()
    await _close_connections()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_device_websocket_rejects_bad_token() -> None:
    device_id, _ = await sync_to_async(_create_device)(name="WS-BAD")
    communicator = WebsocketCommunicator(DeviceConsumer.as_asgi(), "/ws/device/")
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to(
        {"type": "hello", "device_id": device_id, "token": "wrong"}
    )
    output = await communicator.receive_output(timeout=5)
    assert output["type"] == "websocket.close"
    assert output["code"] == 4401
    await communicator.wait()
    await _close_connections()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_edge_tunnel_handshake_and_ping() -> None:
    edge_id, secret = await sync_to_async(_create_edge)()
    communicator = WebsocketCommunicator(EdgeConsumer.as_asgi(), "/ws/edge/")

    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to(
        {"type": "hello", "edge_id": edge_id, "secret": secret, "software_version": "0.1.0"}
    )
    welcome = await communicator.receive_json_from(timeout=5)
    assert welcome["type"] == "welcome"
    assert welcome["edge_id"] == edge_id

    await communicator.send_json_to({"type": "ping"})
    pong = await communicator.receive_json_from(timeout=5)
    assert pong["type"] == "pong"

    await communicator.send_json_to(
        {"type": "heartbeat", "devices": [{"device_id": str(__import__("uuid").uuid4())}]}
    )
    ack = await communicator.receive_json_from(timeout=5)
    assert ack["type"] == "heartbeat_ack"

    await communicator.disconnect()
    await _close_connections()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_edge_tunnel_rejects_bad_secret() -> None:
    edge_id, _ = await sync_to_async(_create_edge)()
    communicator = WebsocketCommunicator(EdgeConsumer.as_asgi(), "/ws/edge/")
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({"type": "hello", "edge_id": edge_id, "secret": "nope"})
    output = await communicator.receive_output(timeout=5)
    assert output["type"] == "websocket.close"
    assert output["code"] == 4401
    await communicator.wait()
    await _close_connections()

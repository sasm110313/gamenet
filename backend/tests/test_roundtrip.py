"""The edge→cloud contract, exercised end to end inside one process.

The live Phase 0 proof runs this same path over TLS with two databases and two
processes; this test locks the contract (serialization, validation, dedupe,
projection, ack/watermark) into CI.
"""

from __future__ import annotations

import pytest

from apps.clients.models import ClientDevice
from apps.devices.services import create_registration_code, register_device
from apps.synchronization.ingest import ingest_batch
from apps.synchronization.models import EdgeIdentity, OutboxEvent, OutboxStatus, SyncEvent
from apps.synchronization.outbox import drain_outbox


class IngestingCloud:
    """A CloudClient stand-in that calls the real cloud ingest function."""

    def __init__(self, settings, edge):
        self.settings = settings
        self.edge = edge
        self.captured: list[dict] = []

    def post_events(self, events: list[dict]) -> dict:
        self.captured.extend(events)
        previous = self.settings.GAMENET_ROLE
        self.settings.GAMENET_ROLE = "cloud"
        try:
            return ingest_batch(self.edge, events)
        finally:
            self.settings.GAMENET_ROLE = previous


@pytest.mark.django_db
def test_edge_fact_replicates_and_replay_is_deduplicated(settings, identity, edge_node) -> None:
    identity.edge_id = edge_node.id
    identity.command_public_key = edge_node.command_public_key
    identity.save()

    code = create_registration_code(label="PC-01")
    device, token = register_device(
        code=code.code,
        name="PC-01",
        hostname="WIN7-PC01",
        operating_system="Windows 7 SP1 x64",
        application_version="0.1.0",
    )
    assert OutboxEvent.objects.filter(event_type="device.registered").count() == 1

    cloud = IngestingCloud(settings, edge_node)
    stats = drain_outbox(client=cloud)

    assert stats["sent"] == 1
    assert stats["accepted"] == 1
    assert stats["SYNCED"] == 1
    assert SyncEvent.objects.filter(edge=edge_node, event_type="device.registered").count() == 1
    replica = ClientDevice.objects.get(id=device.id)
    assert replica.is_replica is True
    assert replica.name == "PC-01"
    assert replica.token_hash == device.token_hash  # replication never leaks/rewrites credentials
    assert EdgeIdentity.get_solo().last_acked_sequence == 1
    assert OutboxEvent.objects.get(event_type="device.registered").cloud_acknowledged_at

    # At-least-once delivery: the same batch is replayed; the cloud must report
    # duplicates and must not create a second fact or a second device.
    previous = settings.GAMENET_ROLE
    settings.GAMENET_ROLE = "cloud"
    try:
        replay = ingest_batch(edge_node, cloud.captured)
    finally:
        settings.GAMENET_ROLE = previous
    assert replay["duplicates"] == [cloud.captured[0]["event_id"]]
    assert replay["accepted"] == []
    assert SyncEvent.objects.count() == 1
    assert ClientDevice.objects.filter(name="PC-01").count() == 1

"""Phase 1 edge→cloud projection: customers, wallet, ledger and sessions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.core.roles import WrongRole
from apps.customer_groups.models import CustomerGroup
from apps.customer_groups.services import create_group
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.devices.services import create_registration_code, register_device, set_status
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.pricing.models import Tariff
from apps.pricing.services import create_tariff
from apps.sessions.models import GamingSession, SessionStatus
from apps.sessions.services import start_session, stop_session
from apps.synchronization.ingest import ingest_batch
from apps.synchronization.models import EdgeNode, OutboxEvent, OutboxStatus, SyncEvent
from apps.synchronization.outbox import drain_outbox
from apps.wallets.models import Wallet
from apps.wallets.services import deposit


class IngestingCloud:
    def __init__(self, settings, edge: EdgeNode):
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
def test_phase1_facts_replicate_and_replay_is_idempotent(
    settings, identity, edge_node
) -> None:
    identity.edge_id = edge_node.id
    identity.command_public_key = edge_node.command_public_key
    identity.save()
    settings.SYNC_BATCH_SIZE = 200

    tariff = create_tariff(name="Standard", hourly_rate=40_000)
    group = create_group(name="Regular", tariff=tariff)
    customer = create_customer(
        full_name="Ali Rezaei", phone="09120000000", group=group, credit_limit=60_000
    )
    deposit(customer, 100_000, note="counter deposit")

    code = create_registration_code(label="PC-01")
    device, _token = register_device(
        code=code.code,
        name="PC-01",
        hostname="WIN7-PC01",
        operating_system="Windows 7 SP1 x64",
        application_version="0.1.0",
    )
    set_status(device, ClientStatus.ONLINE, force=True)

    session = start_session(customer, device)
    GamingSession.objects.filter(pk=session.pk).update(
        started_at=timezone.now() - timedelta(minutes=90)
    )
    ended, charge = stop_session(session)
    assert ended.cost == 60_000
    assert charge is not None

    cloud = IngestingCloud(settings, edge_node)
    stats = drain_outbox(client=cloud)

    assert stats["PENDING"] == 0
    assert stats["SYNCED"] == OutboxEvent.objects.count()
    assert OutboxEvent.objects.exclude(status=OutboxStatus.SYNCED).count() == 0
    assert not SyncEvent.objects.filter(status="REJECTED").exists()

    cloud_tariff = Tariff.objects.get(id=tariff.id)
    assert cloud_tariff.is_replica is True
    assert cloud_tariff.hourly_rate == 40_000

    cloud_group = CustomerGroup.objects.get(id=group.id)
    assert cloud_group.is_replica is True
    assert cloud_group.tariff_id == tariff.id

    cloud_customer = Customer.objects.get(id=customer.id)
    assert cloud_customer.is_replica is True
    assert cloud_customer.full_name == "Ali Rezaei"
    assert cloud_customer.group_id == group.id

    cloud_wallet = Wallet.objects.get(customer_id=customer.id)
    assert cloud_wallet.balance == 40_000

    cloud_entries = LedgerEntry.objects.filter(customer_id=customer.id).order_by("created_at")
    assert cloud_entries.count() == 2
    assert [e.entry_type for e in cloud_entries] == [
        LedgerEntryType.DEPOSIT,
        LedgerEntryType.SESSION_CHARGE,
    ]
    assert [e.amount for e in cloud_entries] == [100_000, -60_000]
    assert cloud_entries[1].session_id == session.id

    cloud_session = GamingSession.objects.get(id=session.id)
    assert cloud_session.is_replica is True
    assert cloud_session.status == SessionStatus.COMPLETED
    assert cloud_session.cost == 60_000
    assert cloud_session.hourly_rate == 40_000
    assert cloud_session.customer_id == customer.id
    assert cloud_session.device_id == device.id

    device_replica = ClientDevice.objects.get(id=device.id)
    assert device_replica.is_replica is True

    replay = cloud.captured
    previous = settings.GAMENET_ROLE
    settings.GAMENET_ROLE = "cloud"
    try:
        result = ingest_batch(edge_node, replay)
    finally:
        settings.GAMENET_ROLE = previous

    assert result["accepted"] == []
    assert len(result["duplicates"]) == len(replay)
    assert SyncEvent.objects.count() == len(replay)
    assert LedgerEntry.objects.filter(customer_id=customer.id).count() == 2
    assert GamingSession.objects.filter(id=session.id).count() == 1


@pytest.mark.django_db
def test_cloud_ledger_projection_creates_balance_and_dedupes(settings, edge_node) -> None:
    from apps.core.ids import uuid7

    settings.GAMENET_ROLE = "cloud"
    customer_id = uuid7()
    entry_id = uuid7()
    now = timezone.now().isoformat()

    created = {
        "event_id": str(uuid7()),
        "local_sequence": 1,
        "event_type": "customer.created",
        "aggregate_type": "customer",
        "aggregate_id": str(customer_id),
        "schema_version": 1,
        "occurred_at": now,
        "payload": {
            "customer_id": str(customer_id),
            "full_name": "Cloud Customer",
            "phone": "09123333333",
            "group_id": None,
            "credit_limit": 60_000,
            "is_active": True,
            "notes": "",
            "wallet_balance": 0,
        },
    }
    deposit_event = {
        "event_id": str(uuid7()),
        "local_sequence": 2,
        "event_type": "ledger.entry_created",
        "aggregate_type": "customer",
        "aggregate_id": str(customer_id),
        "schema_version": 1,
        "occurred_at": now,
        "payload": {
            "entry_id": str(entry_id),
            "customer_id": str(customer_id),
            "session_id": None,
            "entry_type": "DEPOSIT",
            "amount": 50_000,
            "balance_after": 50_000,
            "reverses_id": None,
            "note": "deposit",
            "created_at": now,
        },
    }

    result = ingest_batch(edge_node, [created, deposit_event])

    assert result["accepted"] == [created["event_id"], deposit_event["event_id"]]
    customer = Customer.objects.get(id=customer_id)
    assert customer.is_replica is True
    wallet = Wallet.objects.get(customer_id=customer_id)
    assert wallet.is_replica is True
    assert wallet.balance == 50_000
    entry = LedgerEntry.objects.get(id=entry_id)
    assert entry.entry_type == LedgerEntryType.DEPOSIT
    assert entry.amount == 50_000
    assert entry.is_replica is True

    replay = ingest_batch(edge_node, [created, deposit_event])
    assert replay["duplicates"] == [created["event_id"], deposit_event["event_id"]]
    assert LedgerEntry.objects.filter(customer_id=customer_id).count() == 1
    assert Wallet.objects.get(customer_id=customer_id).balance == 50_000


@pytest.mark.django_db
def test_cloud_replica_is_read_only_by_role_services(settings, customer) -> None:
    settings.GAMENET_ROLE = "cloud"
    with pytest.raises(WrongRole):
        deposit(customer, 1_000)


@pytest.mark.django_db
def test_session_projection_requires_order(settings, edge_node) -> None:
    """A session without its customer/device replicas is a hard error, not silent
    financial loss. FIFO delivery makes this unreachable in normal operation."""
    from apps.core.ids import uuid7

    settings.GAMENET_ROLE = "cloud"
    raw = {
        "event_id": str(uuid7()),
        "local_sequence": 1,
        "event_type": "session.started",
        "aggregate_type": "session",
        "aggregate_id": str(uuid7()),
        "schema_version": 1,
        "occurred_at": timezone.now().isoformat(),
        "payload": {
            "session_id": str(uuid7()),
            "customer_id": str(uuid7()),
            "device_id": str(uuid7()),
            "tariff_id": None,
            "tariff_name": "Standard",
            "hourly_rate": 40_000,
            "started_at": timezone.now().isoformat(),
        },
    }
    with pytest.raises(RuntimeError, match="projection failed"):
        ingest_batch(edge_node, [raw])
    assert not SyncEvent.objects.filter(event_id=raw["event_id"], status="APPLIED").exists()

"""Phase 2: personal rates, revision control and remote management commands."""

from __future__ import annotations

import uuid

import pytest

from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import CommandStatus, RemoteCommand
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.devices.services import set_status
from apps.ledger.models import LedgerEntry
from apps.pricing.models import CustomerRate, Tariff
from apps.pricing.services import (
    CustomerRateError,
    create_customer_rate,
    deactivate_customer_rate,
    set_default_customer_rate,
    update_customer_rate,
)
from apps.sessions.models import GamingSession, SessionStatus
from apps.sessions.services import start_session, stop_session
from apps.synchronization.command_service import (
    execute_command,
    issue_command,
    receive_command,
)
from apps.synchronization.ingest import ingest_batch
from apps.synchronization.models import EdgeNode, OutboxEvent, SyncEvent
from apps.synchronization.outbox import drain_outbox
from apps.wallets.models import Wallet
from apps.wallets.services import deposit


class IngestingCloud:
    """Minimal CloudClient stand-in that ingests into the same test database."""

    def __init__(self, settings, edge: EdgeNode):
        self.settings = settings
        self.edge = edge

    def post_events(self, events: list[dict]) -> dict:
        previous = self.settings.GAMENET_ROLE
        self.settings.GAMENET_ROLE = "cloud"
        try:
            return ingest_batch(self.edge, events)
        finally:
            self.settings.GAMENET_ROLE = previous


@pytest.fixture
def cloud(settings):
    settings.GAMENET_ROLE = "cloud"
    return settings


@pytest.fixture
def online_device(device):
    set_status(device, ClientStatus.ONLINE, force=True)
    return device


def _new_device(identity, name: str, status=ClientStatus.ONLINE) -> ClientDevice:
    return ClientDevice.objects.create(
        edge_id=identity.edge_id,
        name=name,
        hostname=f"WIN7-{name}",
        operating_system="Windows 7 SP1",
        application_version="0.1.0",
        status=status,
    )


@pytest.mark.django_db
def test_personal_rate_keeps_exactly_one_default(synced_identity, customer) -> None:
    first = create_customer_rate(customer=customer, name="Standard", hourly_rate=50_000)
    assert first.is_default is True

    with pytest.raises(CustomerRateError, match="فعال"):
        update_customer_rate(
            first, is_active=False, is_default=True, expected_revision=first.revision
        )

    second = create_customer_rate(
        customer=customer, name="Night", hourly_rate=70_000, is_default=True
    )
    first.refresh_from_db()
    assert second.is_default is True
    assert first.is_default is False

    # Explicitly clearing a default promotes another active rate instead of
    # leaving the customer without one.
    second = update_customer_rate(second, is_default=False, expected_revision=second.revision)
    first.refresh_from_db()
    assert second.is_default is False
    assert first.is_default is True

    second = set_default_customer_rate(second)
    first.refresh_from_db()
    assert second.is_default is True
    assert first.is_default is False

    # Deactivating the default promotes the remaining active rate.
    second = deactivate_customer_rate(second)
    first.refresh_from_db()
    assert second.is_active is False
    assert first.is_default is True

    # Promoting it back through the dedicated action is idempotent.
    first = set_default_customer_rate(first)
    assert first.is_default is True


@pytest.mark.django_db
def test_rate_update_rejects_a_stale_revision(synced_identity, customer) -> None:
    rate = create_customer_rate(customer=customer, name="Standard", hourly_rate=50_000)
    base = rate.revision

    updated = update_customer_rate(rate, name="Standard+", expected_revision=base)
    assert updated.revision == base + 1

    with pytest.raises(CustomerRateError, match="نسخه"):
        update_customer_rate(updated, name="Stale", expected_revision=base)


@pytest.mark.django_db
def test_edit_after_start_does_not_reprice_the_session(
    synced_identity, customer, online_device
) -> None:
    deposit(customer, 200_000, note="test")
    rate = create_customer_rate(customer=customer, name="VIP", hourly_rate=90_000)

    session = start_session(customer, online_device, customer_rate=rate)

    assert session.customer_rate_id == rate.id
    assert session.tariff_id is None
    assert session.hourly_rate == 90_000
    assert session.tariff_name == "VIP"

    update_customer_rate(rate, hourly_rate=120_000, expected_revision=rate.revision)
    session.refresh_from_db()
    assert session.hourly_rate == 90_000
    assert session.tariff_name == "VIP"

    event = OutboxEvent.objects.get(event_type="session.started")
    assert event.payload["customer_rate_id"] == str(rate.id)
    assert event.payload["hourly_rate"] == 90_000


@pytest.mark.django_db
def test_session_rate_falls_back_from_personal_to_group_tariff(
    synced_identity, customer, tariff
) -> None:
    deposit(customer, 300_000, note="test")
    first_device = _new_device(synced_identity, "PC-A")
    second_device = _new_device(synced_identity, "PC-B")

    personal = create_customer_rate(customer=customer, name="Personal", hourly_rate=55_000)
    first = start_session(customer, first_device)
    assert first.hourly_rate == 55_000
    assert first.customer_rate_id == personal.id

    deactivate_customer_rate(personal, expected_revision=personal.revision)
    second = start_session(customer, second_device)
    assert second.customer_rate_id is None
    assert second.tariff_id == tariff.id
    assert second.hourly_rate == 40_000


@pytest.mark.django_db
def test_remote_wallet_command_is_exactly_once(
    settings, edge_node, synced_identity, customer
) -> None:
    settings.GAMENET_ROLE = "cloud"
    request_id = uuid.uuid4()
    payload = {
        "customer_id": str(customer.id),
        "amount": 50_000,
        "reason": "remote deposit",
    }
    first = issue_command(
        edge_node, "wallet.deposit", payload, request_id=request_id, push=False
    )
    replay = issue_command(
        edge_node, "wallet.deposit", payload, request_id=request_id, push=False
    )
    assert first.id == replay.id
    assert RemoteCommand.objects.count() == 1

    settings.GAMENET_ROLE = "edge"
    receive_command({**first.envelope(), "signature": first.signature})
    result = execute_command(first.id)
    again = execute_command(first.id)

    assert result["status"] == "succeeded"
    assert again == {"status": "already_handled"}
    assert LedgerEntry.objects.filter(source_command_id=first.id).count() == 1
    assert Wallet.objects.get(customer=customer).balance == 50_000
    assert OutboxEvent.objects.filter(event_type="ledger.entry_created").count() == 1


@pytest.mark.django_db
def test_remote_negative_adjustment_respects_the_credit_limit(
    settings, edge_node, synced_identity, customer
) -> None:
    settings.GAMENET_ROLE = "cloud"
    customer.credit_limit = 60_000
    customer.save(update_fields=["credit_limit"])

    command = issue_command(
        edge_node,
        "wallet.adjust",
        {
            "customer_id": str(customer.id),
            "amount": -70_000,
            "reason": "over limit",
        },
        push=False,
    )
    settings.GAMENET_ROLE = "edge"
    receive_command({**command.envelope(), "signature": command.signature})

    result = execute_command(command.id)

    assert result["status"] == "failed"
    assert "کافی نیست" in result["error"]
    assert LedgerEntry.objects.filter(customer=customer).count() == 0
    assert Wallet.objects.get(customer=customer).balance == 0


@pytest.mark.django_db
def test_remote_catalog_command_applies_and_uses_revisions(
    settings, edge_node, synced_identity, customer
) -> None:
    settings.GAMENET_ROLE = "cloud"
    rate_id = uuid.uuid4()
    create = {
        "customer_rate_id": str(rate_id),
        "customer_id": str(customer.id),
        "base_revision": 0,
        "name": "Remote VIP",
        "hourly_rate": 80_000,
        "is_default": True,
        "is_active": True,
    }
    command = issue_command(
        edge_node, "catalog.customer_rate.upsert", create, push=False
    )
    settings.GAMENET_ROLE = "edge"
    receive_command({**command.envelope(), "signature": command.signature})
    first = execute_command(command.id)

    assert first["status"] == "succeeded"
    rate = CustomerRate.objects.get(id=rate_id)
    assert rate.is_default is True
    assert rate.hourly_rate == 80_000

    update = {**create, "base_revision": rate.revision, "hourly_rate": 85_000}
    settings.GAMENET_ROLE = "cloud"
    update_command = issue_command(
        edge_node, "catalog.customer_rate.upsert", update, push=False
    )
    settings.GAMENET_ROLE = "edge"
    receive_command(
        {**update_command.envelope(), "signature": update_command.signature}
    )
    second = execute_command(update_command.id)
    assert second["status"] == "succeeded"
    rate.refresh_from_db()
    assert rate.hourly_rate == 85_000
    assert rate.revision == 2

    stale = {**create, "base_revision": 1, "name": "Stale Update"}
    settings.GAMENET_ROLE = "cloud"
    stale_command = issue_command(
        edge_node, "catalog.customer_rate.upsert", stale, push=False
    )
    settings.GAMENET_ROLE = "edge"
    receive_command(
        {**stale_command.envelope(), "signature": stale_command.signature}
    )
    third = execute_command(stale_command.id)
    assert third["status"] == "failed"
    assert "stale revision" in third["error"]
    rate.refresh_from_db()
    assert rate.name == "Remote VIP"


@pytest.mark.django_db
def test_rates_and_session_rate_project_to_the_cloud(
    settings, synced_identity, edge_node, customer, online_device
) -> None:
    settings.SYNC_BATCH_SIZE = 200
    settings.GAMENET_ROLE = "edge"
    deposit(customer, 200_000, note="test")
    rate = create_customer_rate(customer=customer, name="VIP", hourly_rate=90_000)
    session = start_session(customer, online_device, customer_rate=rate)
    stop_session(session, reason="test")

    cloud = IngestingCloud(settings, edge_node)
    stats = drain_outbox(client=cloud)

    assert stats["PENDING"] == 0
    assert not SyncEvent.objects.filter(status="REJECTED").exists()

    cloud_rate = CustomerRate.objects.get(id=rate.id)
    assert cloud_rate.is_replica is True
    assert cloud_rate.is_default is True
    assert cloud_rate.revision == 1

    cloud_session = GamingSession.objects.get(id=session.id)
    assert cloud_session.is_replica is True
    assert cloud_session.customer_rate_id == rate.id
    assert cloud_session.hourly_rate == 90_000
    assert cloud_session.tariff_id is None

    ledger = LedgerEntry.objects.get(customer_id=customer.id)
    assert ledger.amount == 200_000


@pytest.mark.django_db
def test_edge_ui_manages_rates_and_starts_with_a_rate(
    client, django_user_model, synced_identity, customer, online_device
) -> None:
    staff = django_user_model.objects.create_user(
        "operator", password="x", is_staff=True
    )
    deposit(customer, 200_000, note="test")
    client.force_login(staff)

    response = client.post(
        f"/customers/{customer.id}/rates/create",
        {"name": "Night VIP", "hourly_rate": "65000", "is_default": "1"},
    )
    assert response.status_code == 302
    rate = CustomerRate.objects.get(customer=customer, name="Night VIP")
    assert rate.is_default is True

    response = client.post(
        f"/customers/{customer.id}/rates/{rate.id}/update",
        {
            "name": "Night VIP Plus",
            "hourly_rate": "70000",
            "is_active": "1",
            "is_default": "1",
            "expected_revision": str(rate.revision),
        },
    )
    assert response.status_code == 302
    rate.refresh_from_db()
    assert rate.hourly_rate == 70_000
    assert rate.revision == 2

    response = client.post(
        "/sessions/start",
        {
            "customer_id": str(customer.id),
            "device_id": str(online_device.id),
            "customer_rate_id": str(rate.id),
        },
    )
    assert response.status_code == 302
    session = GamingSession.objects.get(customer=customer, status=SessionStatus.ACTIVE)
    assert session.customer_rate_id == rate.id
    assert session.hourly_rate == 70_000

    assert client.get(f"/customers/{customer.id}/").status_code == 200
    assert client.get("/sessions/").status_code == 200


@pytest.mark.django_db
def test_cloud_management_ui_issues_idempotent_commands(
    client, django_user_model, settings, edge_node
) -> None:
    settings.GAMENET_ROLE = "cloud"
    settings.ROOT_URLCONF = "gamenet.urls_cloud"

    staff = django_user_model.objects.create_user(
        "cloud-operator", password="x", is_staff=True
    )
    customer = Customer.objects.create(
        edge_id=edge_node.id, full_name="Cloud Customer", credit_limit=60_000, is_replica=True
    )
    tariff = Tariff.objects.create(
        edge_id=edge_node.id, name="Cloud Tariff", hourly_rate=45_000, is_replica=True
    )
    group = CustomerGroup.objects.create(
        edge_id=edge_node.id, name="Cloud Group", tariff=tariff, is_replica=True
    )
    customer.group = group
    customer.save(update_fields=["group"])
    CustomerRate.objects.create(
        edge_id=edge_node.id,
        customer=customer,
        name="Cloud Rate",
        hourly_rate=80_000,
        is_default=True,
        is_replica=True,
    )
    Wallet.objects.create(customer=customer, balance=10_000, is_replica=True)
    client.force_login(staff)

    for path in (
        "/manage/customers/",
        "/manage/pricing/",
        f"/manage/customers/{customer.id}/",
    ):
        assert client.get(path).status_code == 200, path

    request_id = str(uuid.uuid4())
    payload = {
        "request_id": request_id,
        "action": "deposit",
        "amount": "25000",
        "reason": "cloud top-up",
    }
    response = client.post(f"/manage/customers/{customer.id}/wallet", payload)
    assert response.status_code == 302
    response = client.post(f"/manage/customers/{customer.id}/wallet", payload)
    assert response.status_code == 302

    command = RemoteCommand.objects.get(edge=edge_node, request_id=request_id)
    assert command.command_type == "wallet.deposit"
    assert command.status == CommandStatus.PENDING
    assert command.payload["amount"] == 25_000
    assert RemoteCommand.objects.count() == 1

    response = client.post(
        f"/manage/customers/{customer.id}/rates/create",
        {
            "request_id": str(uuid.uuid4()),
            "name": "Cloud Rate",
            "hourly_rate": "80000",
            "is_default": "1",
        },
    )
    assert response.status_code == 302
    rate_command = RemoteCommand.objects.get(
        command_type="catalog.customer_rate.upsert",
    )
    assert rate_command.payload["base_revision"] == 0
    assert rate_command.payload["customer_id"] == str(customer.id)

    response = client.post(
        "/manage/pricing/tariffs/create",
        {
            "request_id": str(uuid.uuid4()),
            "edge_id": str(edge_node.id),
            "name": "Cloud Tariff",
            "hourly_rate": "45000",
        },
    )
    assert response.status_code == 302
    assert RemoteCommand.objects.filter(command_type="catalog.tariff.upsert").exists()

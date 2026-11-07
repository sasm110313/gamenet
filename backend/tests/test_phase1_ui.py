from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.devices.services import set_status
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.pricing.models import Tariff
from apps.sessions.models import GamingSession, SessionStatus
from apps.synchronization.models import EdgeNode
from apps.wallets.models import Wallet


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user("operator", password="x", is_staff=True)


@pytest.mark.django_db
def test_edge_phase1_pages_and_actions(client, staff, customer, device, tariff) -> None:
    set_status(device, ClientStatus.ONLINE, force=True)
    client.force_login(staff)

    for path in ("/customers/", "/sessions/", "/ledger/", "/pricing/"):
        response = client.get(path)
        assert response.status_code == 200, path

    response = client.post(
        "/customers/create",
        {"full_name": "New Customer", "phone": "09129999999", "credit_limit": "70000"},
    )
    assert response.status_code == 302
    created = Customer.objects.get(full_name="New Customer")
    assert created.wallet.balance == 0
    assert created.credit_limit == 70_000

    response = client.post(f"/customers/{customer.id}/deposit", {"amount": "50,000"})
    assert response.status_code == 302
    assert Wallet.objects.get(customer=customer).balance == 50_000

    assert client.get(f"/customers/{customer.id}/").status_code == 200

    response = client.post(
        "/sessions/start", {"customer_id": str(customer.id), "device_id": str(device.id)}
    )
    assert response.status_code == 302
    session = GamingSession.objects.get(customer=customer, status=SessionStatus.ACTIVE)
    assert client.get("/sessions/").status_code == 200

    response = client.post(f"/sessions/{session.id}/stop")
    assert response.status_code == 302
    session.refresh_from_db()
    assert session.status == SessionStatus.COMPLETED

    response = client.post(
        "/pricing/tariffs/create", {"name": "Night", "hourly_rate": "25000"}
    )
    assert response.status_code == 302
    night = Tariff.objects.get(name="Night")
    response = client.post(
        "/pricing/groups/create", {"name": "Night Group", "tariff_id": str(night.id)}
    )
    assert response.status_code == 302
    group = CustomerGroup.objects.get(name="Night Group")
    response = client.post(
        f"/pricing/groups/{group.id}/update",
        {"name": "Night Group 2", "tariff_id": str(night.id), "is_active": "1"},
    )
    assert response.status_code == 302
    group.refresh_from_db()
    assert group.name == "Night Group 2"


@pytest.mark.django_db
def test_cloud_phase1_pages_are_read_only(
    client, staff, settings, edge_node
) -> None:
    settings.GAMENET_ROLE = "cloud"
    settings.ROOT_URLCONF = "gamenet.urls_cloud"

    tariff = Tariff.objects.create(
        edge_id=edge_node.id, name="Cloud Rate", hourly_rate=50_000, is_replica=True
    )
    group = CustomerGroup.objects.create(
        edge_id=edge_node.id, name="Cloud Group", tariff=tariff, is_replica=True
    )
    customer = Customer.objects.create(
        edge_id=edge_node.id, full_name="Cloud Customer", group=group, is_replica=True
    )
    Wallet.objects.create(customer=customer, balance=25_000, is_replica=True)
    device = ClientDevice.objects.create(
        edge_id=edge_node.id, name="CLOUD-PC", status=ClientStatus.ONLINE, is_replica=True
    )
    now = timezone.now()
    GamingSession.objects.create(
        edge_id=edge_node.id,
        customer=customer,
        device=device,
        status=SessionStatus.COMPLETED,
        tariff=tariff,
        tariff_name=tariff.name,
        hourly_rate=tariff.hourly_rate,
        started_at=now - timedelta(hours=1),
        ended_at=now,
        elapsed_seconds=3600,
        cost=50_000,
        is_replica=True,
    )
    LedgerEntry.objects.create(
        edge_id=edge_node.id,
        customer=customer,
        entry_type=LedgerEntryType.DEPOSIT,
        amount=25_000,
        balance_after=25_000,
        note="replica",
        is_replica=True,
    )

    client.force_login(staff)
    for path in (
        "/customers/",
        f"/customers/{customer.id}/",
        "/sessions/",
        "/ledger/",
        "/pricing/",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert b"Cloud Customer" in response.content or path in {"/sessions/", "/ledger/", "/pricing/"}

    # The cloud dashboard exposes no mutation endpoints for these read models.
    assert client.post(f"/customers/{customer.id}/deposit", {"amount": "1"}).status_code in {404, 405}

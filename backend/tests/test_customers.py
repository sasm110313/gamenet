from __future__ import annotations

import pytest

from apps.core.roles import WrongRole
from apps.customers.models import Customer
from apps.customers.services import CustomerError, create_customer, update_customer
from apps.synchronization.models import OutboxEvent
from apps.wallets.models import Wallet
from apps.wallets.services import adjust, deposit


@pytest.mark.django_db
def test_create_customer_creates_wallet_and_event(identity, customer_group) -> None:
    customer = create_customer(
        full_name="Sara Ahmadi",
        phone="09121111111",
        group=customer_group,
        credit_limit=80_000,
    )

    assert customer.edge_id == identity.edge_id
    assert customer.group_id == customer_group.id
    assert customer.credit_limit == 80_000
    wallet = Wallet.objects.get(customer=customer)
    assert wallet.balance == 0
    event = OutboxEvent.objects.get(event_type="customer.created", aggregate_id=str(customer.id))
    assert event.payload["full_name"] == "Sara Ahmadi"
    assert event.payload["wallet_balance"] == 0
    assert event.payload["credit_limit"] == 80_000


@pytest.mark.django_db
def test_duplicate_phone_is_refused(customer) -> None:
    with pytest.raises(CustomerError, match="شماره تماس"):
        create_customer(full_name="Other", phone=customer.phone)


@pytest.mark.django_db
def test_update_customer_cannot_set_credit_limit_below_current_debt(customer) -> None:
    adjust(customer, -60_000, note="debt")
    with pytest.raises(CustomerError, match="بدهی"):
        update_customer(customer, credit_limit=50_000)


@pytest.mark.django_db
def test_update_customer_emits_updated_event(customer) -> None:
    before = OutboxEvent.objects.count()
    update_customer(customer, full_name="Ali Rezaei 2", notes="VIP")

    customer.refresh_from_db()
    assert customer.full_name == "Ali Rezaei 2"
    assert customer.notes == "VIP"
    assert OutboxEvent.objects.count() == before + 1
    event = OutboxEvent.objects.order_by("-local_sequence").first()
    assert event.event_type == "customer.updated"
    assert event.payload["full_name"] == "Ali Rezaei 2"


@pytest.mark.django_db
def test_deactivating_customer_with_active_session_is_refused(customer, device, settings) -> None:
    from apps.clients.models import ClientStatus
    from apps.devices.services import set_status
    from apps.sessions.services import start_session

    set_status(device, ClientStatus.ONLINE, force=True)
    start_session(customer, device)

    with pytest.raises(CustomerError, match="نشست فعال"):
        update_customer(customer, is_active=False)


@pytest.mark.django_db
def test_customer_writes_are_edge_only(customer, settings) -> None:
    settings.GAMENET_ROLE = "cloud"
    with pytest.raises(WrongRole):
        deposit(customer, 10_000)
    assert Customer.objects.count() == 1

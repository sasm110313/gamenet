from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import DeviceCommand
from apps.devices.services import set_status
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.sessions.models import GamingSession, SessionStatus
from apps.sessions.services import SessionError, start_session, stop_session
from apps.synchronization.models import OutboxEvent
from apps.wallets.models import Wallet


def _online_device(identity, name: str = "PC-01", status: str = ClientStatus.ONLINE):
    return ClientDevice.objects.create(
        edge_id=identity.edge_id,
        name=name,
        hostname=f"WIN7-{name}",
        operating_system="Windows 7 SP1",
        application_version="0.1.0",
        status=status,
    )


@pytest.mark.django_db
def test_start_session_snapshots_tariff_and_unlocks_device(customer, device, tariff) -> None:
    set_status(device, ClientStatus.ONLINE, force=True)

    session = start_session(customer, device)

    assert session.status == SessionStatus.ACTIVE
    assert session.hourly_rate == 40_000
    assert session.tariff_id == tariff.id
    assert session.tariff_name == "Standard"
    assert session.ended_at is None
    device.refresh_from_db()
    assert device.status == ClientStatus.STARTING
    command = DeviceCommand.objects.get(client=device)
    assert command.command_type == "client.unlock"
    assert command.payload["session_id"] == str(session.id)
    event = OutboxEvent.objects.get(event_type="session.started")
    assert event.payload["hourly_rate"] == 40_000
    assert event.payload["tariff_name"] == "Standard"


@pytest.mark.django_db
def test_rate_change_does_not_reprice_active_session(customer, device, tariff) -> None:
    from apps.pricing.services import update_tariff

    set_status(device, ClientStatus.ONLINE, force=True)
    session = start_session(customer, device)
    update_tariff(tariff, hourly_rate=90_000)
    session.refresh_from_db()
    assert session.hourly_rate == 40_000


@pytest.mark.django_db
def test_stop_session_charges_elapsed_time_exactly_once(customer, device) -> None:
    set_status(device, ClientStatus.ONLINE, force=True)
    session = start_session(customer, device)
    GamingSession.objects.filter(pk=session.pk).update(
        started_at=timezone.now() - timedelta(minutes=90)
    )

    ended, entry = stop_session(session)

    assert ended.status == SessionStatus.COMPLETED
    assert ended.elapsed_seconds >= 5_400
    assert ended.cost == 60_000
    assert entry is not None
    assert entry.entry_type == LedgerEntryType.SESSION_CHARGE
    assert entry.amount == -60_000
    assert entry.session_id == session.id
    assert Wallet.objects.get(customer=customer).balance == -60_000
    device.refresh_from_db()
    assert device.status == ClientStatus.STOPPING
    assert DeviceCommand.objects.filter(client=device, command_type="client.lock").exists()

    count = LedgerEntry.objects.count()
    again, same_entry = stop_session(session)
    assert again.status == SessionStatus.COMPLETED
    assert same_entry.id == entry.id
    assert LedgerEntry.objects.count() == count
    assert OutboxEvent.objects.filter(event_type="session.ended").count() == 1


@pytest.mark.django_db
def test_zero_duration_session_costs_zero_and_writes_no_ledger_row(customer, device) -> None:
    set_status(device, ClientStatus.ONLINE, force=True)
    session = start_session(customer, device)

    ended, entry = stop_session(session)

    assert ended.cost == 0
    assert ended.elapsed_seconds == 0
    assert entry is None
    assert LedgerEntry.objects.filter(session=session).count() == 0
    assert Wallet.objects.get(customer=customer).balance == 0


@pytest.mark.django_db
def test_start_requires_one_hour_of_available_credit(customer, device) -> None:
    from apps.customers.services import update_customer

    update_customer(customer, credit_limit=0)
    set_status(device, ClientStatus.ONLINE, force=True)

    with pytest.raises(SessionError, match="کافی نیست"):
        start_session(customer, device)


@pytest.mark.django_db
def test_offline_device_cannot_start(customer, device) -> None:
    assert device.status == ClientStatus.OFFLINE
    with pytest.raises(SessionError, match="وضعیت قابل شروع"):
        start_session(customer, device)


@pytest.mark.django_db
def test_client_can_only_confirm_active_with_a_real_session(customer, device) -> None:
    set_status(device, ClientStatus.LOCKED, force=True)
    assert set_status(device, ClientStatus.ACTIVE) is False

    set_status(device, ClientStatus.ONLINE, force=True)
    session = start_session(customer, device)
    assert set_status(device, ClientStatus.ACTIVE) is True
    device.refresh_from_db()
    assert device.status == ClientStatus.ACTIVE
    assert session.status == SessionStatus.ACTIVE


@pytest.mark.django_db
def test_active_session_reconciles_after_network_drop(customer, device) -> None:
    set_status(device, ClientStatus.ONLINE, force=True)
    start_session(customer, device)

    # The edge marks the PC offline as network truth, then the client reconnects
    # and reports ACTIVE. The persisted session is what makes that report valid.
    set_status(device, ClientStatus.OFFLINE, force=True, reason="network drop")
    assert set_status(device, ClientStatus.ACTIVE) is True
    device.refresh_from_db()
    assert device.status == ClientStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_concurrent_starts_cannot_both_pass_the_credit_check(customer, identity) -> None:
    devices = [
        _online_device(identity, "PC-A"),
        _online_device(identity, "PC-B"),
    ]
    barrier = Barrier(2)

    def worker(device) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            start_session(customer, device)
            return "started"
        except SessionError:
            return "blocked"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, devices))

    assert sorted(results) == ["blocked", "started"]
    assert GamingSession.objects.filter(customer=customer, status=SessionStatus.ACTIVE).count() == 1
    assert GamingSession.objects.filter(customer=customer).count() == 1

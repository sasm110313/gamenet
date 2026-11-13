from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections

from apps.core.roles import WrongRole
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.synchronization.models import OutboxEvent
from apps.wallets.models import Wallet
from apps.wallets.services import WalletError, adjust, deposit, reverse_entry


@pytest.mark.django_db
def test_deposit_updates_balance_and_appends_ledger(customer) -> None:
    entry = deposit(customer, 100_000, note="counter")

    wallet = Wallet.objects.get(customer=customer)
    assert wallet.balance == 100_000
    assert entry.entry_type == LedgerEntryType.DEPOSIT
    assert entry.amount == 100_000
    assert entry.balance_after == 100_000
    assert LedgerEntry.objects.filter(customer=customer).count() == 1
    event = OutboxEvent.objects.get(event_type="ledger.entry_created")
    assert event.payload["entry_id"] == str(entry.id)
    assert event.payload["balance_after"] == 100_000


@pytest.mark.django_db
@pytest.mark.parametrize("amount", [0, -1])
def test_deposit_rejects_non_positive_amounts(customer, amount) -> None:
    with pytest.raises(WalletError):
        deposit(customer, amount)
    assert LedgerEntry.objects.count() == 0


@pytest.mark.django_db
def test_adjustment_stops_at_credit_limit(customer) -> None:
    adjust(customer, -60_000, note="max debt")
    with pytest.raises(WalletError, match="کافی نیست"):
        adjust(customer, -1)
    assert Wallet.objects.get(customer=customer).balance == -60_000


@pytest.mark.django_db
def test_reversal_is_append_only_and_idempotent(customer) -> None:
    original = deposit(customer, 100_000)
    reversal = reverse_entry(original, note="wrong deposit")

    assert reversal.entry_type == LedgerEntryType.REVERSAL
    assert reversal.amount == -100_000
    assert reversal.reverses_id == original.id
    assert Wallet.objects.get(customer=customer).balance == 0
    assert LedgerEntry.objects.count() == 2

    again = reverse_entry(original)
    assert again.id == reversal.id
    assert LedgerEntry.objects.count() == 2
    assert OutboxEvent.objects.filter(event_type="ledger.entry_created").count() == 2

    original.refresh_from_db()
    assert original.amount == 100_000
    assert original.balance_after == 100_000


@pytest.mark.django_db
def test_ledger_rows_cannot_be_updated_or_deleted(customer) -> None:
    entry = deposit(customer, 10_000)
    original_note = entry.note
    entry.note = "tamper"
    with pytest.raises(ValueError, match="append-only"):
        entry.save()
    with pytest.raises(ValueError, match="append-only"):
        entry.delete()
    assert LedgerEntry.objects.get(pk=entry.pk).note == original_note


@pytest.mark.django_db
def test_wallet_writes_are_edge_only(customer, settings) -> None:
    settings.GAMENET_ROLE = "cloud"
    with pytest.raises(WrongRole):
        deposit(customer, 10_000)


@pytest.mark.django_db(transaction=True)
def test_concurrent_deposits_do_not_lose_money(customer) -> None:
    barrier = Barrier(2)

    def worker(amount: int) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            deposit(customer, amount)
            return "ok"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [10_000, 25_000]))

    assert results == ["ok", "ok"]
    assert Wallet.objects.get(customer=customer).balance == 35_000
    assert LedgerEntry.objects.filter(customer=customer).count() == 2

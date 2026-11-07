"""Wallet mutations: the only way a balance may change.

Every mutation runs in one transaction that (1) takes the customer advisory lock,
(2) locks the wallet row with SELECT FOR UPDATE, (3) inserts an append-only
ledger entry, and (4) emits the outbox event. No other code path writes
`Wallet.balance`.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.locks import customer_lock
from apps.core.roles import require_edge
from apps.customers.models import Customer
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.events import emit
from apps.wallets.models import Wallet


class WalletError(ValueError):
    pass


def _locked_wallet(customer: Customer) -> tuple[Customer, Wallet]:
    # Canonical lock order: customer row -> advisory lock -> wallet row.
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    customer_lock(customer.id)
    wallet = Wallet.objects.select_for_update().filter(customer=customer).first()
    if wallet is None:
        wallet = Wallet.objects.create(customer=customer, balance=0)
    return customer, wallet


def _entry_payload(entry: LedgerEntry) -> dict:
    return {
        "entry_id": str(entry.id),
        "customer_id": str(entry.customer_id),
        "session_id": str(entry.session_id) if entry.session_id else None,
        "entry_type": entry.entry_type,
        "amount": entry.amount,
        "balance_after": entry.balance_after,
        "reverses_id": str(entry.reverses_id) if entry.reverses_id else None,
        "note": entry.note,
        "source_command_id": (
            str(entry.source_command_id) if entry.source_command_id else None
        ),
        "created_at": entry.created_at.isoformat(),
    }


@transaction.atomic
def post_entry(
    *,
    customer: Customer,
    amount: int,
    entry_type: str,
    session=None,
    note: str = "",
    actor=None,
    reverses: LedgerEntry | None = None,
    allow_over_limit: bool = False,
    created_at=None,
    source_command_id=None,
) -> LedgerEntry:
    require_edge()
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise WalletError("مبلغ باید عدد صحیح تومان باشد.")
    if amount == 0:
        raise WalletError("مبلغ تراکنش نمی‌تواند صفر باشد.")
    if entry_type not in LedgerEntryType.values:
        raise WalletError("نوع تراکنش نامعتبر است.")
    if session is not None and session.customer_id != customer.id:
        raise WalletError("نشست به مشتری دیگری تعلق دارد.")

    if source_command_id is not None:
        existing = LedgerEntry.objects.filter(
            source_command_id=source_command_id
        ).first()
        if existing is not None:
            return existing

    identity = ensure_identity()
    customer, wallet = _locked_wallet(customer)
    new_balance = wallet.balance + amount
    if not allow_over_limit and new_balance < -customer.credit_limit:
        raise WalletError("موجودی و سقف اعتبار برای این تراکنش کافی نیست.")

    entry = LedgerEntry.objects.create(
        edge_id=identity.edge_id,
        customer=customer,
        session=session,
        entry_type=entry_type,
        amount=amount,
        balance_after=new_balance,
        reverses=reverses,
        note=(note or "")[:255],
        source_command_id=source_command_id,
        created_by=actor if getattr(actor, "pk", None) else None,
        created_at=created_at or timezone.now(),
    )
    wallet.balance = new_balance
    wallet.save(update_fields=["balance", "updated_at"])
    emit(
        "ledger.entry_created",
        aggregate_type="customer",
        aggregate_id=str(customer.id),
        payload=_entry_payload(entry),
    )
    return entry


def deposit(
    customer: Customer,
    amount: int,
    *,
    actor=None,
    note: str = "",
    source_command_id=None,
) -> LedgerEntry:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise WalletError("مبلغ شارژ باید عدد صحیح بزرگ‌تر از صفر باشد.")
    return post_entry(
        customer=customer,
        amount=amount,
        entry_type=LedgerEntryType.DEPOSIT,
        note=note or "شارژ کیف پول",
        actor=actor,
        source_command_id=source_command_id,
    )


def adjust(
    customer: Customer,
    amount: int,
    *,
    actor=None,
    note: str = "",
    source_command_id=None,
) -> LedgerEntry:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0:
        raise WalletError("مبلغ اصلاح باید عدد صحیح و غیرصفر باشد.")
    return post_entry(
        customer=customer,
        amount=amount,
        entry_type=LedgerEntryType.ADJUSTMENT,
        note=note or "اصلاح دستی",
        actor=actor,
        source_command_id=source_command_id,
    )


@transaction.atomic
def reverse_entry(
    entry: LedgerEntry, *, actor=None, note: str = ""
) -> LedgerEntry:
    """Append the opposite entry. The original row is never modified."""
    require_edge()
    entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
    existing = LedgerEntry.objects.filter(reverses=entry).first()
    if existing is not None:
        return existing
    if entry.entry_type == LedgerEntryType.REVERSAL:
        raise WalletError("تراکنش اصلاحی را نمی‌توان دوباره اصلاح کرد.")
    return post_entry(
        customer=entry.customer,
        amount=-entry.amount,
        entry_type=LedgerEntryType.REVERSAL,
        session=entry.session,
        reverses=entry,
        note=note or f"برگشت تراکنش {str(entry.id)[:8]}",
        actor=actor,
        # A reversal undoes a fact that should never have been applied; it must
        # be possible even when the original deposit was already spent.
        allow_over_limit=True,
    )


def available_credit(customer: Customer) -> int:
    wallet = Wallet.objects.filter(customer=customer).first()
    if wallet is None:
        return customer.credit_limit
    return wallet.balance + customer.credit_limit

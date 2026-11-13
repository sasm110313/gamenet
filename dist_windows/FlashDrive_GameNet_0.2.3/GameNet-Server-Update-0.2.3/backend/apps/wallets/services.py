"""Wallet mutations: the only way a balance may change.

Every mutation runs in one transaction that (1) takes the customer advisory lock,
(2) locks the wallet row with SELECT FOR UPDATE, (3) inserts an append-only
ledger entry, and (4) emits the outbox event. No other code path writes
`Wallet.balance`.
"""

from __future__ import annotations

from django.db import models, transaction
from django.utils import timezone

from apps.core.locks import customer_lock
from apps.core.roles import require_edge
from apps.customers.models import Customer
from apps.ledger.models import LedgerEntry, LedgerEntryType, generate_tracking_code
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
        "is_debt": getattr(entry, "is_debt", False),
        "reverses_id": str(entry.reverses_id) if entry.reverses_id else None,
        "note": entry.note,
        "tracking_code": entry.tracking_code,
        "operator_label": entry.operator_label,
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
    is_debt: bool = False,
    created_at=None,
    source_command_id=None,
    entry_id=None,
    tracking_code: str | None = None,
    operator_label: str = "",
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

    if entry_id is not None:
        existing_by_id = LedgerEntry.objects.filter(id=entry_id).first()
        if existing_by_id is not None:
            return existing_by_id

    identity = ensure_identity()
    customer, wallet = _locked_wallet(customer)
    new_balance = wallet.balance + amount
    # بدهی کلاً غیرمجاز است: سقف اعتبار همواره 0 در نظر گرفته می‌شود
    effective_limit = min(0, -getattr(customer, "credit_limit", 0)) if getattr(customer, "credit_limit", 0) < 0 else 0
    if not allow_over_limit and new_balance < effective_limit:
        raise WalletError("موجودی کیف‌پول کافی نیست. بدهی مجاز نمی‌باشد.")

    op_label = (operator_label or "").strip()[:120]
    if not op_label and getattr(actor, "pk", None):
        op_label = str(getattr(actor, "label", "") or getattr(actor, "username", ""))[:120]
    when = created_at or timezone.now()
    code = (tracking_code or "").strip()[:32] or generate_tracking_code(when)

    create_kwargs = dict(
        edge_id=identity.edge_id,
        customer=customer,
        session=session,
        entry_type=entry_type,
        amount=amount,
        balance_after=new_balance,
        reverses=reverses,
        note=(note or "")[:255],
        tracking_code=code,
        operator_label=op_label,
        is_debt=is_debt,
        source_command_id=source_command_id,
        created_by=actor if getattr(actor, "pk", None) else None,
        created_at=when,
    )
    if entry_id is not None:
        create_kwargs["id"] = entry_id

    entry = LedgerEntry.objects.create(**create_kwargs)
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
    is_debt: bool = False,
    actor=None,
    note: str = "",
    source_command_id=None,
    entry_id=None,
    tracking_code: str | None = None,
    operator_label: str = "",
) -> LedgerEntry:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise WalletError("مبلغ شارژ باید عدد صحیح بزرگ‌تر از صفر باشد.")
    if is_debt:
        max_limit = getattr(customer, "max_debt_limit", 40_000) or 40_000
        current_debt = getattr(customer, "debt_balance", 0) or 0
        if current_debt + amount > max_limit:
            remaining = max(0, max_limit - current_debt)
            raise WalletError(
                f"سقف بدهی این کاربر حداکثر {max_limit:,} تومان است (بدهی فعلی: {current_debt:,} تومان). "
                f"حداکثر می‌توانید {remaining:,} تومان دیگر به صورت بدهی ثبت کنید."
            )
        Customer.objects.filter(pk=customer.pk).update(
            debt_balance=models.F("debt_balance") + amount,
            updated_at=timezone.now(),
        )
    return post_entry(
        customer=customer,
        amount=amount,
        entry_type=LedgerEntryType.DEPOSIT,
        note=note or ("شارژ به صورت بدهی (نسیه)" if is_debt else "شارژ کیف پول"),
        actor=actor,
        is_debt=is_debt,
        source_command_id=source_command_id,
        entry_id=entry_id,
        tracking_code=tracking_code,
        operator_label=operator_label,
    )


@transaction.atomic
def settle_debt(
    customer: Customer,
    amount: int | None = None,
    *,
    actor=None,
    note: str = "",
    operator_label: str = "",
) -> tuple[int, LedgerEntry]:
    require_edge()
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    current_debt = int(getattr(customer, "debt_balance", 0) or 0)
    if current_debt <= 0:
        raise WalletError("این مشتری هیچ بدهی پرداخت‌نشده‌ای ندارد.")

    paid = current_debt if amount is None or amount <= 0 else min(int(amount), current_debt)
    new_debt = max(0, current_debt - paid)
    customer.debt_balance = new_debt
    customer.save(update_fields=["debt_balance", "updated_at"])

    # Register an immutable ledger entry of type DEBT_PAYMENT
    # Note: balance_after stays the same because cash was paid to salon for the previous debt.
    identity = ensure_identity()
    customer, wallet = _locked_wallet(customer)
    when = timezone.now()
    code = generate_tracking_code(when)
    op_label = (operator_label or "").strip()[:120]
    if not op_label and getattr(actor, "pk", None):
        op_label = str(getattr(actor, "label", "") or getattr(actor, "username", ""))[:120]

    entry = LedgerEntry.objects.create(
        edge_id=identity.edge_id,
        customer=customer,
        entry_type=LedgerEntryType.DEBT_PAYMENT,
        amount=paid,
        balance_after=wallet.balance,
        is_debt=False,
        note=note or f"تسویه نقدی بدهی ({paid:,} تومان) - باقیمانده بدهی: {new_debt:,} تومان",
        tracking_code=code,
        operator_label=op_label,
        created_by=actor if getattr(actor, "pk", None) else None,
        created_at=when,
    )
    emit(
        "ledger.entry_created",
        aggregate_type="customer",
        aggregate_id=str(customer.id),
        payload=_entry_payload(entry),
    )
    return paid, entry


def adjust(
    customer: Customer,
    amount: int,
    *,
    actor=None,
    note: str = "",
    source_command_id=None,
    entry_id=None,
    tracking_code: str | None = None,
    operator_label: str = "",
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
        entry_id=entry_id,
        tracking_code=tracking_code,
        operator_label=operator_label,
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
        return 0
    return max(0, wallet.balance)

"""Customer lifecycle on the edge. Every customer gets a wallet in the same
transaction that creates the customer and its outbox event."""

from __future__ import annotations

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.core.roles import require_edge
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.sessions.models import GamingSession, SessionStatus
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.events import emit
from apps.wallets.models import Wallet


class CustomerError(ValueError):
    pass


def _clean(
    *, full_name: str, phone: str, credit_limit: int, notes: str
) -> tuple[str, str, int, str]:
    full_name = (full_name or "").strip()
    if not full_name:
        raise CustomerError("نام مشتری الزامی است.")
    if len(full_name) > 120:
        raise CustomerError("نام مشتری حداکثر ۱۲۰ کاراکتر است.")
    phone = (phone or "").strip()
    if len(phone) > 24:
        raise CustomerError("شماره تماس حداکثر ۲۴ کاراکتر است.")
    if isinstance(credit_limit, bool) or not isinstance(credit_limit, int):
        raise CustomerError("سقف اعتبار باید عدد صحیح باشد.")
    if credit_limit < 0:
        raise CustomerError("سقف اعتبار نمی‌تواند منفی باشد.")
    if len(notes or "") > 255:
        raise CustomerError("یادداشت حداکثر ۲۵۵ کاراکتر است.")
    return full_name, phone, credit_limit, (notes or "").strip()


def _payload(customer: Customer, wallet: Wallet) -> dict:
    return {
        "customer_id": str(customer.id),
        "full_name": customer.full_name,
        "username": customer.username,
        "phone": customer.phone,
        "group_id": str(customer.group_id) if customer.group_id else None,
        "credit_limit": customer.credit_limit,
        "is_active": customer.is_active,
        "notes": customer.notes,
        "wallet_balance": wallet.balance,
        "revision": customer.revision,
    }


def _check_group(customer_edge_id, group: CustomerGroup | None) -> CustomerGroup | None:
    if group is None:
        return None
    if group.edge_id != customer_edge_id:
        raise CustomerError("گروه به این Edge تعلق ندارد.")
    if not group.is_active:
        raise CustomerError("گروه مشتری غیرفعال است.")
    return group


@transaction.atomic
def create_customer(
    *,
    full_name: str,
    phone: str = "",
    username: str = "",
    password: str = "",
    group: CustomerGroup | None = None,
    credit_limit: int | None = None,
    notes: str = "",
    customer_id=None,
    actor=None,
) -> Customer:
    require_edge()
    identity = ensure_identity()

    if customer_id is not None:
        existing = Customer.objects.filter(id=customer_id).first()
        if existing is not None:
            if existing.edge_id != identity.edge_id:
                raise CustomerError("شناسه مشتری به این Edge تعلق ندارد.")
            Wallet.objects.get_or_create(customer=existing, defaults={"balance": 0})
            return existing

    limit = (
        int(
            current_config().get(
                "default_credit_limit", settings.DEFAULT_CREDIT_LIMIT
            )
        )
        if credit_limit is None
        else credit_limit
    )
    full_name, phone, limit, notes = _clean(
        full_name=full_name, phone=phone, credit_limit=limit, notes=notes
    )
    username = (username or "").strip()
    if username and Customer.objects.filter(edge_id=identity.edge_id, username__iexact=username).exists():
        raise CustomerError("مشتری دیگری با این نام کاربری ثبت شده است.")

    group = _check_group(identity.edge_id, group)
    if phone and Customer.objects.filter(edge_id=identity.edge_id, phone=phone).exists():
        raise CustomerError("مشتری دیگری با این شماره تماس ثبت شده است.")

    try:
        with transaction.atomic():
            customer = Customer.objects.create(
                id=customer_id,
                edge_id=identity.edge_id,
                full_name=full_name,
                username=username,
                phone=phone,
                group=group,
                credit_limit=limit,
                notes=notes,
            )
            if password:
                customer.set_password(password)
                customer.save(update_fields=["password_hash"])
    except IntegrityError as exc:
        # A concurrent create won the unique keys. Return the winner for a
        # retried remote command, otherwise surface a friendly error.
        if customer_id is not None:
            existing = Customer.objects.filter(id=customer_id).first()
            if existing is not None:
                if existing.edge_id != identity.edge_id:
                    raise CustomerError("شناسه مشتری به این Edge تعلق ندارد.") from exc
                Wallet.objects.get_or_create(customer=existing, defaults={"balance": 0})
                return existing
        if phone:
            existing = Customer.objects.filter(
                edge_id=identity.edge_id, phone=phone
            ).first()
            if existing is not None:
                raise CustomerError(
                    "مشتری دیگری با این شماره تماس ثبت شده است."
                ) from exc
        raise
    wallet = Wallet.objects.create(customer=customer, balance=0)
    emit(
        "customer.created",
        aggregate_type="customer",
        aggregate_id=str(customer.id),
        payload=_payload(customer, wallet),
    )
    return customer


@transaction.atomic
def update_customer(
    customer: Customer,
    *,
    full_name: str | None = None,
    username: str | None = None,
    password: str | None = None,
    phone: str | None = None,
    group: CustomerGroup | None = None,
    clear_group: bool = False,
    credit_limit: int | None = None,
    notes: str | None = None,
    is_active: bool | None = None,
    expected_revision: int | None = None,
    actor=None,
) -> Customer:
    require_edge()
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if expected_revision is not None and customer.revision != expected_revision:
        raise CustomerError("نسخه مشتری تغییر کرده است؛ صفحه را تازه کنید و دوباره تلاش کنید.")
    wallet = Wallet.objects.select_for_update().get(customer=customer)

    full_name = customer.full_name if full_name is None else full_name
    phone = customer.phone if phone is None else phone
    limit = customer.credit_limit if credit_limit is None else credit_limit
    notes = customer.notes if notes is None else notes
    full_name, phone, limit, notes = _clean(
        full_name=full_name, phone=phone, credit_limit=limit, notes=notes
    )

    if username is not None:
        username = username.strip()
        if username and Customer.objects.filter(edge_id=customer.edge_id, username__iexact=username).exclude(pk=customer.pk).exists():
            raise CustomerError("مشتری دیگری با این نام کاربری ثبت شده است.")
        customer.username = username

    if password:
        customer.set_password(password)

    if clear_group:
        new_group = None
    elif group is not None:
        new_group = _check_group(customer.edge_id, group)
    else:
        new_group = customer.group

    if phone and (
        Customer.objects.filter(edge_id=customer.edge_id, phone=phone)
        .exclude(pk=customer.pk)
        .exists()
    ):
        raise CustomerError("مشتری دیگری با این شماره تماس ثبت شده است.")

    will_be_active = customer.is_active if is_active is None else is_active
    if not will_be_active and GamingSession.objects.filter(
        customer=customer, status=SessionStatus.ACTIVE
    ).exists():
        raise CustomerError("برای مشتری نشست فعال وجود دارد؛ ابتدا نشست را پایان دهید.")
    reserved = sum(
        GamingSession.objects.filter(
            customer=customer, status=SessionStatus.ACTIVE
        ).values_list("hourly_rate", flat=True)
    )
    if limit < customer.credit_limit and wallet.balance + limit < reserved:
        raise CustomerError(
            "سقف اعتبار جدید کمتر از بدهی و تعهد نشست‌های فعال است."
        )

    customer.full_name = full_name
    customer.phone = phone
    customer.group = new_group
    customer.credit_limit = limit
    customer.notes = notes
    customer.is_active = will_be_active
    customer.revision += 1
    customer.save(
        update_fields=[
            "full_name", "phone", "group", "credit_limit", "notes", "is_active",
            "revision", "updated_at",
        ]
    )
    emit(
        "customer.updated",
        aggregate_type="customer",
        aggregate_id=str(customer.id),
        payload=_payload(customer, wallet),
    )
    return customer

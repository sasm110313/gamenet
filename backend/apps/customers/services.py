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
    persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
    english = "01234567890123456789"
    phone = (phone or "").translate(str.maketrans(persian_arabic, english)).strip()
    if not phone:
        raise CustomerError("شماره موبایل الزامی است.")
    if len(phone) < 10 or len(phone) > 24:
        raise CustomerError("شماره موبایل باید حداقل ۱۰ رقم باشد.")
    # بدهی کلاً غیرمجاز است: سقف اعتبار همواره صفر است
    credit_limit = 0
    if len(notes or "") > 255:
        raise CustomerError("یادداشت حداکثر ۲۵۵ کاراکتر است.")
    return full_name, phone, credit_limit, (notes or "").strip()


def _payload(customer: Customer, wallet: Wallet) -> dict:
    return {
        "customer_id": str(customer.id),
        "full_name": customer.full_name,
        "username": customer.username,
        "password_hash": customer.password_hash or "",
        "phone": customer.phone,
        "group_id": str(customer.group_id) if customer.group_id else None,
        "group_name": customer.group.name if customer.group else None,
        "credit_limit": customer.credit_limit,
        "is_active": customer.is_active,
        "notes": customer.notes,
        "debt_balance": customer.debt_balance,
        "max_debt_limit": customer.max_debt_limit,
        "active_coupons": getattr(customer, "active_coupons", 0),
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
    password_hash: str = "",
    group: CustomerGroup | None = None,
    credit_limit: int | None = None,
    active_coupons: int | None = None,
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
                active_coupons=max(0, int(active_coupons)) if active_coupons is not None else 0,
                notes=notes,
            )
            # رمز عبور الزامی است؛ در صورت عدم تعیین، ابتدا همان شماره موبایل ثبت می‌شود
            initial_password = (password or "").strip() or phone
            if password_hash:
                if not isinstance(password_hash, str) or len(password_hash) > 255:
                    raise CustomerError("هش رمز عبور نامعتبر است.")
                customer.password_hash = password_hash
            else:
                customer.set_password(initial_password)
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
                if customer_id is not None and str(existing.id) == str(customer_id):
                    Wallet.objects.get_or_create(customer=existing, defaults={"balance": 0})
                    return existing
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
    password_hash: str | None = None,
    phone: str | None = None,
    group: CustomerGroup | None = None,
    clear_group: bool = False,
    credit_limit: int | None = None,
    max_debt_limit: int | None = None,
    active_coupons: int | None = None,
    notes: str | None = None,
    is_active: bool | None = None,
    expected_revision: int | None = None,
    actor=None,
) -> Customer:
    require_edge()
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if expected_revision is not None and customer.revision != expected_revision:
        raise CustomerError("نسخه مشتری تغییر کرده است؛ صفحه را تازه کنید و دوباره تلاش کنید.")
    wallet, _ = Wallet.objects.select_for_update().get_or_create(customer=customer, defaults={"balance": 0})

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

    if password is not None and str(password).strip():
        customer.set_password(str(password).strip())
    elif password_hash:
        if not isinstance(password_hash, str) or len(password_hash) > 255:
            raise CustomerError("هش رمز عبور نامعتبر است.")
        customer.password_hash = password_hash

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
    if max_debt_limit is not None:
        customer.max_debt_limit = max(0, int(max_debt_limit))
    if active_coupons is not None:
        customer.active_coupons = max(0, int(active_coupons))
    customer.notes = notes
    customer.is_active = will_be_active
    customer.revision += 1
    update_flds = [
        "full_name", "username", "password_hash", "phone", "group", "credit_limit", "notes", "is_active",
        "revision", "updated_at",
    ]
    if max_debt_limit is not None:
        update_flds.append("max_debt_limit")
    if active_coupons is not None:
        update_flds.append("active_coupons")
    customer.save(update_fields=update_flds)
    emit(
        "customer.updated",
        aggregate_type="customer",
        aggregate_id=str(customer.id),
        payload=_payload(customer, wallet),
    )
    return customer

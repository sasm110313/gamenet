"""Tariff and personal-rate management.

The edge is authoritative. A session copies the chosen rate at start, so a later
price edit can never reprice a live or historical session.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.roles import require_edge
from apps.customers.models import Customer
from apps.pricing.models import CustomerRate, Tariff
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.events import emit


class TariffError(ValueError):
    pass


class CustomerRateError(ValueError):
    pass


def _tariff_payload(tariff: Tariff) -> dict:
    return {
        "tariff_id": str(tariff.id),
        "name": tariff.name,
        "hourly_rate": tariff.hourly_rate,
        "is_active": tariff.is_active,
        "revision": tariff.revision,
    }


def _rate_payload(rate: CustomerRate) -> dict:
    return {
        "customer_rate_id": str(rate.id),
        "customer_id": str(rate.customer_id),
        "name": rate.name,
        "hourly_rate": rate.hourly_rate,
        "is_default": rate.is_default,
        "is_active": rate.is_active,
        "revision": rate.revision,
    }


def _clean_tariff(name: str, hourly_rate: int) -> tuple[str, int]:
    name = (name or "").strip()
    if not name:
        raise TariffError("نام تعرفه الزامی است.")
    if len(name) > 80:
        raise TariffError("نام تعرفه حداکثر ۸۰ کاراکتر است.")
    if isinstance(hourly_rate, bool) or not isinstance(hourly_rate, int):
        raise TariffError("نرخ ساعتی باید عدد صحیح باشد.")
    if hourly_rate <= 0:
        raise TariffError("نرخ ساعتی باید بزرگ‌تر از صفر باشد.")
    return name, hourly_rate


def _clean_rate(name: str, hourly_rate: int) -> tuple[str, int]:
    name = (name or "").strip()
    if not name:
        raise CustomerRateError("نام نرخ الزامی است.")
    if len(name) > 80:
        raise CustomerRateError("نام نرخ حداکثر ۸۰ کاراکتر است.")
    if isinstance(hourly_rate, bool) or not isinstance(hourly_rate, int):
        raise CustomerRateError("نرخ ساعتی باید عدد صحیح باشد.")
    if hourly_rate <= 0:
        raise CustomerRateError("نرخ ساعتی باید بزرگ‌تر از صفر باشد.")
    return name, hourly_rate


@transaction.atomic
def create_tariff(
    *, name: str, hourly_rate: int, tariff_id=None, actor=None
) -> Tariff:
    require_edge()
    identity = ensure_identity()
    if tariff_id is not None:
        existing = Tariff.objects.filter(id=tariff_id).first()
        if existing is not None:
            if existing.edge_id != identity.edge_id:
                raise TariffError("شناسه تعرفه به این Edge تعلق ندارد.")
            return existing
    name, hourly_rate = _clean_tariff(name, hourly_rate)
    if Tariff.objects.filter(edge_id=identity.edge_id, name=name).exists():
        raise TariffError("تعرفه‌ای با این نام قبلاً ثبت شده است.")
    tariff = Tariff.objects.create(
        id=tariff_id, edge_id=identity.edge_id, name=name, hourly_rate=hourly_rate
    )
    emit(
        "tariff.created",
        aggregate_type="tariff",
        aggregate_id=str(tariff.id),
        payload=_tariff_payload(tariff),
    )
    return tariff


@transaction.atomic
def update_tariff(
    tariff: Tariff,
    *,
    name: str | None = None,
    hourly_rate: int | None = None,
    is_active: bool | None = None,
    expected_revision: int | None = None,
) -> Tariff:
    require_edge()
    tariff = Tariff.objects.select_for_update().get(pk=tariff.pk)
    if expected_revision is not None and tariff.revision != expected_revision:
        raise TariffError("نسخه تعرفه تغییر کرده است؛ صفحه را تازه کنید و دوباره تلاش کنید.")
    name = tariff.name if name is None else name
    hourly_rate = tariff.hourly_rate if hourly_rate is None else hourly_rate
    name, hourly_rate = _clean_tariff(name, hourly_rate)
    if (
        Tariff.objects.filter(edge_id=tariff.edge_id, name=name)
        .exclude(pk=tariff.pk)
        .exists()
    ):
        raise TariffError("تعرفه‌ای با این نام قبلاً ثبت شده است.")
    tariff.name = name
    tariff.hourly_rate = hourly_rate
    if is_active is not None:
        tariff.is_active = is_active
    tariff.revision += 1
    tariff.save(
        update_fields=["name", "hourly_rate", "is_active", "revision", "updated_at"]
    )
    emit(
        "tariff.updated",
        aggregate_type="tariff",
        aggregate_id=str(tariff.id),
        payload=_tariff_payload(tariff),
    )
    return tariff


@transaction.atomic
def create_customer_rate(
    *,
    customer: Customer,
    name: str,
    hourly_rate: int,
    is_default: bool = False,
    rate_id=None,
    actor=None,
) -> CustomerRate:
    require_edge()
    identity = ensure_identity()
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if customer.edge_id != identity.edge_id:
        raise CustomerRateError("مشتری به این Edge تعلق ندارد.")

    if rate_id is not None:
        existing = CustomerRate.objects.filter(id=rate_id).first()
        if existing is not None:
            if existing.customer_id != customer.id:
                raise CustomerRateError("شناسه نرخ به مشتری دیگری تعلق دارد.")
            return existing

    name, hourly_rate = _clean_rate(name, hourly_rate)
    if CustomerRate.objects.filter(
        edge_id=identity.edge_id, customer=customer, name=name
    ).exists():
        raise CustomerRateError("نرخی با این نام برای این مشتری ثبت شده است.")

    active_exists = CustomerRate.objects.filter(
        customer=customer, is_active=True
    ).exists()
    has_default = CustomerRate.objects.filter(
        customer=customer, is_active=True, is_default=True
    ).exists()
    make_default = bool(is_default) or not active_exists or not has_default
    if make_default:
        CustomerRate.objects.filter(customer=customer, is_default=True).update(
            is_default=False
        )

    rate = CustomerRate.objects.create(
        id=rate_id,
        edge_id=identity.edge_id,
        customer=customer,
        name=name,
        hourly_rate=hourly_rate,
        is_default=make_default,
    )
    emit(
        "customer_rate.created",
        aggregate_type="customer_rate",
        aggregate_id=str(rate.id),
        payload=_rate_payload(rate),
    )
    return rate


@transaction.atomic
def update_customer_rate(
    rate: CustomerRate,
    *,
    name: str | None = None,
    hourly_rate: int | None = None,
    is_active: bool | None = None,
    is_default: bool | None = None,
    expected_revision: int | None = None,
    actor=None,
) -> CustomerRate:
    require_edge()
    rate = CustomerRate.objects.select_for_update().get(pk=rate.pk)
    customer = Customer.objects.select_for_update().get(pk=rate.customer_id)
    if expected_revision is not None and rate.revision != expected_revision:
        raise CustomerRateError("نسخه نرخ تغییر کرده است؛ صفحه را تازه کنید و دوباره تلاش کنید.")

    new_name = rate.name if name is None else name
    new_hourly = rate.hourly_rate if hourly_rate is None else hourly_rate
    new_name, new_hourly = _clean_rate(new_name, new_hourly)
    if (
        CustomerRate.objects.filter(
            edge_id=rate.edge_id, customer=customer, name=new_name
        )
        .exclude(pk=rate.pk)
        .exists()
    ):
        raise CustomerRateError("نرخی با این نام برای این مشتری ثبت شده است.")

    was_default = rate.is_default
    new_active = rate.is_active if is_active is None else is_active
    new_default = rate.is_default if is_default is None else is_default
    if is_default is True and not new_active:
        raise CustomerRateError("نرخ پیش‌فرض باید فعال باشد.")
    if not new_active:
        new_default = False
    if was_default and not new_default:
        # Never leave active rates without a default. If no other active rate
        # exists, this rate keeps the default flag while it stays active.
        has_other_active = (
            CustomerRate.objects.filter(customer=customer, is_active=True)
            .exclude(pk=rate.pk)
            .exists()
        )
        if new_active and not has_other_active:
            new_default = True
    if new_default:
        CustomerRate.objects.filter(customer=customer, is_default=True).exclude(
            pk=rate.pk
        ).update(is_default=False)

    rate.name = new_name
    rate.hourly_rate = new_hourly
    rate.is_active = new_active
    rate.is_default = new_default
    rate.revision += 1
    rate.save(
        update_fields=[
            "name", "hourly_rate", "is_active", "is_default", "revision", "updated_at",
        ]
    )
    emit(
        "customer_rate.updated",
        aggregate_type="customer_rate",
        aggregate_id=str(rate.id),
        payload=_rate_payload(rate),
    )

    # Keep a default whenever another active rate exists. The cloud projection
    # clears the old default when it sees the replacement's is_default=True.
    if was_default and not new_default:
        replacement = (
            CustomerRate.objects.select_for_update()
            .filter(customer=customer, is_active=True)
            .exclude(pk=rate.pk)
            .order_by("created_at", "id")
            .first()
        )
        if replacement is not None:
            replacement.is_default = True
            replacement.revision += 1
            replacement.save(update_fields=["is_default", "revision", "updated_at"])
            emit(
                "customer_rate.updated",
                aggregate_type="customer_rate",
                aggregate_id=str(replacement.id),
                payload=_rate_payload(replacement),
            )
    return rate


def deactivate_customer_rate(
    rate: CustomerRate, *, expected_revision: int | None = None, actor=None
) -> CustomerRate:
    return update_customer_rate(
        rate,
        is_active=False,
        is_default=False,
        expected_revision=expected_revision,
        actor=actor,
    )


def set_default_customer_rate(
    rate: CustomerRate, *, expected_revision: int | None = None, actor=None
) -> CustomerRate:
    return update_customer_rate(
        rate, is_default=True, expected_revision=expected_revision, actor=actor
    )

"""Tariff management. Edge-authoritative; changes never reprice a live session."""

from __future__ import annotations

from django.db import transaction

from apps.core.roles import require_edge
from apps.pricing.models import Tariff
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.events import emit


class TariffError(ValueError):
    pass


def _payload(tariff: Tariff) -> dict:
    return {
        "tariff_id": str(tariff.id),
        "name": tariff.name,
        "hourly_rate": tariff.hourly_rate,
        "is_active": tariff.is_active,
    }


def _clean(name: str, hourly_rate: int) -> tuple[str, int]:
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


@transaction.atomic
def create_tariff(*, name: str, hourly_rate: int, actor=None) -> Tariff:
    require_edge()
    name, hourly_rate = _clean(name, hourly_rate)
    identity = ensure_identity()
    if Tariff.objects.filter(edge_id=identity.edge_id, name=name).exists():
        raise TariffError("تعرفه‌ای با این نام قبلاً ثبت شده است.")
    tariff = Tariff.objects.create(
        edge_id=identity.edge_id, name=name, hourly_rate=hourly_rate
    )
    emit(
        "tariff.created",
        aggregate_type="tariff",
        aggregate_id=str(tariff.id),
        payload=_payload(tariff),
    )
    return tariff


@transaction.atomic
def update_tariff(
    tariff: Tariff, *, name: str | None = None, hourly_rate: int | None = None,
    is_active: bool | None = None,
) -> Tariff:
    require_edge()
    tariff = Tariff.objects.select_for_update().get(pk=tariff.pk)
    name = tariff.name if name is None else name
    hourly_rate = tariff.hourly_rate if hourly_rate is None else hourly_rate
    name, hourly_rate = _clean(name, hourly_rate)
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
    tariff.save(update_fields=["name", "hourly_rate", "is_active", "updated_at"])
    emit(
        "tariff.updated",
        aggregate_type="tariff",
        aggregate_id=str(tariff.id),
        payload=_payload(tariff),
    )
    return tariff

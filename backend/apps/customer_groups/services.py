"""Customer group management. A group always points at one tariff."""

from __future__ import annotations

from django.db import transaction

from apps.core.roles import require_edge
from apps.customer_groups.models import CustomerGroup
from apps.pricing.models import Tariff
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.events import emit


class GroupError(ValueError):
    pass


def _payload(group: CustomerGroup) -> dict:
    return {
        "group_id": str(group.id),
        "name": group.name,
        "tariff_id": str(group.tariff_id) if group.tariff_id else None,
        "is_active": group.is_active,
    }


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise GroupError("نام گروه الزامی است.")
    if len(name) > 80:
        raise GroupError("نام گروه حداکثر ۸۰ کاراکتر است.")
    return name


@transaction.atomic
def create_group(*, name: str, tariff: Tariff, actor=None) -> CustomerGroup:
    require_edge()
    identity = ensure_identity()
    name = _clean_name(name)
    if tariff.edge_id != identity.edge_id:
        raise GroupError("تعرفه به این Edge تعلق ندارد.")
    if not tariff.is_active:
        raise GroupError("تعرفه غیرفعال است.")
    if CustomerGroup.objects.filter(edge_id=identity.edge_id, name=name).exists():
        raise GroupError("گروهی با این نام قبلاً ثبت شده است.")
    group = CustomerGroup.objects.create(
        edge_id=identity.edge_id, name=name, tariff=tariff
    )
    emit(
        "customer_group.created",
        aggregate_type="customer_group",
        aggregate_id=str(group.id),
        payload=_payload(group),
    )
    return group


@transaction.atomic
def update_group(
    group: CustomerGroup, *, name: str | None = None, tariff: Tariff | None = None,
    is_active: bool | None = None,
) -> CustomerGroup:
    require_edge()
    group = CustomerGroup.objects.select_for_update().get(pk=group.pk)
    if name is not None:
        group.name = _clean_name(name)
    if tariff is not None:
        if tariff.edge_id != group.edge_id:
            raise GroupError("تعرفه به این Edge تعلق ندارد.")
        if not tariff.is_active:
            raise GroupError("تعرفه غیرفعال است.")
        group.tariff = tariff
    if is_active is not None:
        group.is_active = is_active
    if (
        CustomerGroup.objects.filter(edge_id=group.edge_id, name=group.name)
        .exclude(pk=group.pk)
        .exists()
    ):
        raise GroupError("گروهی با این نام قبلاً ثبت شده است.")
    group.save(update_fields=["name", "tariff", "is_active", "updated_at"])
    emit(
        "customer_group.updated",
        aggregate_type="customer_group",
        aggregate_id=str(group.id),
        payload=_payload(group),
    )
    return group

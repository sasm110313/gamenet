"""Edge pricing: tariffs and customer groups."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.core.dashboard import edge_common
from apps.core.ids import parse_uuid
from apps.customer_groups.models import CustomerGroup
from apps.customer_groups.services import GroupError, create_group, update_group
from apps.pricing.models import Tariff
from apps.pricing.services import TariffError, create_tariff, update_tariff


def _int(value):
    return int((value or "").strip().replace(",", "").replace("،", ""))


@login_required
def pricing(request):
    ctx = edge_common()
    ctx.update(
        {
            "tariffs": Tariff.objects.order_by("name"),
            "groups": CustomerGroup.objects.select_related("tariff").order_by("name"),
        }
    )
    return render(request, "edge/pricing.html", ctx)


@login_required
@require_POST
def tariff_create(request):
    try:
        tariff = create_tariff(
            name=request.POST.get("name", ""),
            hourly_rate=_int(request.POST.get("hourly_rate")),
            actor=request.user,
        )
    except (TariffError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_pricing")
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="tariff.created",
        object_type="tariff",
        object_id=str(tariff.id),
        metadata={"name": tariff.name, "rate": tariff.hourly_rate},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"تعرفه {tariff.name} ثبت شد.")
    return redirect("edge_pricing")


@login_required
@require_POST
def tariff_update(request, tariff_id):
    tariff = Tariff.objects.filter(id=tariff_id).first()
    if tariff is None:
        messages.error(request, "تعرفه یافت نشد.")
        return redirect("edge_pricing")
    try:
        update_tariff(
            tariff,
            name=request.POST.get("name", tariff.name),
            hourly_rate=_int(request.POST.get("hourly_rate")),
            is_active=request.POST.get("is_active") == "1",
            expected_revision=_int(request.POST.get("expected_revision"))
            if request.POST.get("expected_revision")
            else None,
        )
    except (TariffError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_pricing")
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="tariff.updated",
        object_type="tariff",
        object_id=str(tariff.id),
        metadata={"name": tariff.name, "rate": tariff.hourly_rate, "active": tariff.is_active},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, "تعرفه به‌روزرسانی شد؛ نشست‌های فعال تغییر نمی‌کنند.")
    return redirect("edge_pricing")


@login_required
@require_POST
def group_create(request):
    tariff = Tariff.objects.filter(id=parse_uuid(request.POST.get("tariff_id"))).first()
    if tariff is None:
        messages.error(request, "تعرفه انتخاب‌شده معتبر نیست.")
        return redirect("edge_pricing")
    try:
        group = create_group(
            name=request.POST.get("name", ""), tariff=tariff, actor=request.user
        )
    except GroupError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("edge_pricing") + "#groups")
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="customer_group.created",
        object_type="customer_group",
        object_id=str(group.id),
        metadata={"name": group.name, "tariff": tariff.name},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"گروه {group.name} ثبت شد.")
    return redirect(reverse("edge_pricing") + "#groups")


@login_required
@require_POST
def group_update(request, group_id):
    group = CustomerGroup.objects.filter(id=group_id).first()
    if group is None:
        messages.error(request, "گروه یافت نشد.")
        return redirect(reverse("edge_pricing") + "#groups")
    tariff = Tariff.objects.filter(id=parse_uuid(request.POST.get("tariff_id"))).first()
    try:
        update_group(
            group,
            name=request.POST.get("name", group.name),
            tariff=tariff,
            is_active=request.POST.get("is_active") == "1",
            expected_revision=_int(request.POST.get("expected_revision"))
            if request.POST.get("expected_revision")
            else None,
        )
    except (GroupError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect(reverse("edge_pricing") + "#groups")
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="customer_group.updated",
        object_type="customer_group",
        object_id=str(group.id),
        metadata={
            "name": group.name,
            "tariff": group.tariff.name if group.tariff else None,
            "active": group.is_active,
        },
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, "گروه به‌روزرسانی شد.")
    return redirect(reverse("edge_pricing") + "#groups")

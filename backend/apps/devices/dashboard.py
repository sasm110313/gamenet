"""Local dashboard (edge only). Renders the authoritative local state."""

from __future__ import annotations

from apps.core.redirects import safe_redirect_next

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import DeviceCommand
from apps.core.roles import require_edge
from apps.devices.models import RegistrationCode
from apps.devices.services import create_registration_code, deactivate_device
from apps.synchronization.cloud_client import CloudClient, CloudRejected, CloudUnavailable
from apps.synchronization.command_service import queue_device_command
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity, is_registered, load_credentials, save_registration
from apps.synchronization.models import OutboxEvent, OutboxStatus
from apps.synchronization.outbox import pending_counts, retry_failed

logger = logging.getLogger("gamenet.dashboard.edge")

ACTION_MAP = {
    "lock": "client.lock",
    "unlock": "client.unlock",
    "ping": "client.ping",
    "restart": "client.restart",
}

OUTBOX_LABELS = {
    OutboxStatus.PENDING: ("در انتظار ارسال", "warning"),
    OutboxStatus.SYNCING: ("در حال ارسال", "info"),
    OutboxStatus.SYNCED: ("همگام", "success"),
    OutboxStatus.FAILED: ("ناموفق", "danger"),
}


def _common():
    require_edge()
    identity = ensure_identity()
    counts = pending_counts()
    return {
        "identity": identity,
        "registered": is_registered(),
        "cloud_online": identity.status == "ONLINE",
        "last_sync": identity.last_sync_at,
        "counts": counts,
        "config": current_config(),
    }


@login_required
def overview(request):
    ctx = _common()
    devices = ClientDevice.objects.filter(is_active=True).order_by("name")
    ctx.update(
        {
            "devices": devices,
            "online_count": devices.exclude(
                status__in=[ClientStatus.OFFLINE, ClientStatus.MAINTENANCE]
            ).count(),
            "locked_count": devices.filter(status=ClientStatus.LOCKED).count(),
            "active_count": devices.filter(status=ClientStatus.ACTIVE).count(),
            "recent_commands": DeviceCommand.objects.select_related("client")[:8],
            "codes": RegistrationCode.objects.filter(used_at__isnull=True)[:4],
            "outbox_recent": OutboxEvent.objects.order_by("-local_sequence")[:6],
            "outbox_labels": OUTBOX_LABELS,
            "now": timezone.now(),
        }
    )
    return render(request, "edge/overview.html", ctx)


@login_required
def device_grid(request):
    ctx = _common()
    ctx["devices"] = ClientDevice.objects.filter(is_active=True).order_by("name")
    return render(request, "edge/_device_grid.html", ctx)


@login_required
def devices(request):
    ctx = _common()
    q = request.GET.get("q", "").strip()
    qs = ClientDevice.objects.all().order_by("name")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(hostname__icontains=q))
    ctx.update({"devices": qs, "q": q, "codes": RegistrationCode.objects.all()[:10]})
    return render(request, "edge/devices.html", ctx)


@login_required
def device_detail(request, device_id):
    ctx = _common()
    device = get_object_or_404(ClientDevice, id=device_id)
    ctx.update(
        {
            "device": device,
            "commands": device.commands.all()[:20],
            "outbox_events": OutboxEvent.objects.filter(
                aggregate_type="device", aggregate_id=str(device.id)
            ).order_by("-local_sequence")[:20],
        }
    )
    return render(request, "edge/device_detail.html", ctx)


@login_required
@require_POST
def device_action(request, device_id):
    device = get_object_or_404(ClientDevice, id=device_id)
    action = request.POST.get("action", "")
    command_type = ACTION_MAP.get(action)
    if command_type is None:
        return HttpResponseBadRequest("unknown action")
    queue_device_command(device, command_type, actor=request.user)
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action=f"device.{action}",
        object_type="device",
        object_id=str(device.id),
        metadata={"name": device.name},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"دستور «{action}» برای {device.name} ثبت شد.")
    return safe_redirect_next(request, "edge_devices")


@login_required
@require_POST
def create_code(request):
    reg = create_registration_code(actor=request.user, label=request.POST.get("label", ""))
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="registration_code.created",
        object_type="registration_code",
        object_id=str(reg.id),
        metadata={"label": reg.label},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"کد ثبت دستگاه: {reg.code} — تا {reg.expires_at:%H:%M} معتبر است.")
    return safe_redirect_next(request, "edge_devices")


@login_required
@require_POST
def deactivate(request, device_id):
    device = get_object_or_404(ClientDevice, id=device_id)
    deactivate_device(device)
    messages.warning(request, f"دستگاه {device.name} غیرفعال شد.")
    return redirect("edge_devices")


@login_required
def cloud_health(request):
    ctx = _common()
    ctx.update(
        {
            "events": OutboxEvent.objects.order_by("-local_sequence")[:50],
            "outbox_labels": OUTBOX_LABELS,
            "cloud_base": settings.CLOUD_BASE_URL,
        }
    )
    return render(request, "edge/cloud.html", ctx)


@login_required
@require_POST
def cloud_retry(request):
    count = retry_failed(request.POST.get("event_id") or None)
    messages.info(request, f"{count} رویداد برای ارسال مجدد آماده شد.")
    return redirect("edge_cloud")


@login_required
@require_POST
def cloud_register(request):
    code = request.POST.get("code", "").strip().upper()
    if not code:
        messages.error(request, "کد ثبت Edge را وارد کنید.")
        return redirect("edge_cloud")
    identity = ensure_identity()
    try:
        response = CloudClient.register(
            base_url=settings.CLOUD_BASE_URL,
            code=code,
            name=identity.name,
            software_version=settings.GAMENET_VERSION,
            ca_bundle=settings.CLOUD_CA_BUNDLE,
        )
    except (CloudUnavailable, CloudRejected) as exc:
        messages.error(request, f"ثبت Edge ناموفق بود: {exc}")
        return redirect("edge_cloud")
    save_registration(
        edge_id=response["edge_id"],
        secret=response["secret"],
        name=identity.name,
        base_url=settings.CLOUD_BASE_URL,
        public_key=response["command_public_key"],
        software_version=settings.GAMENET_VERSION,
    )
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="edge.registered",
        object_type="edge",
        object_id=response["edge_id"],
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, "Edge با موفقیت در Cloud ثبت شد.")
    return redirect("edge_cloud")


@login_required
@require_POST
def emit_test(request):
    from apps.synchronization.edge_runtime import emit_test_event

    event = emit_test_event(note=request.POST.get("note", "manual test"))
    messages.success(request, f"رویداد آزمایشی #{event.local_sequence} ثبت شد.")
    return redirect("edge_cloud")

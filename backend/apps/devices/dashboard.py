"""Local dashboard (edge only). Renders the authoritative local state."""

from __future__ import annotations

from apps.core.redirects import safe_redirect_next

from datetime import datetime, time, timedelta
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, Q, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import DeviceCommand
from apps.core.roles import require_edge
from apps.customers.models import Customer
from apps.devices.models import RegistrationCode
from apps.devices.services import create_registration_code, deactivate_device
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.sessions.models import GamingSession, SessionStatus
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


def _station_sort_key(d):
    name = (d.name or "").upper().strip()
    if name.startswith("PC-"):
        part = name[3:]
        if part.isdigit():
            return (0, int(part))
    return (1, name)


def _enrich_devices(device_list, now):
    active_sessions = {
        s.device_id: s
        for s in GamingSession.objects.filter(status=SessionStatus.ACTIVE).select_related(
            "customer", "customer__wallet", "tariff", "customer_rate"
        )
    }
    for d in device_list:
        d.active_session = active_sessions.get(d.id)
        if d.active_session:
            d.elapsed_seconds = max(0, int((now - d.active_session.started_at).total_seconds()))
            d.current_cost = int((d.elapsed_seconds / 3600) * d.active_session.hourly_rate)
            cust = d.active_session.customer
            if hasattr(cust, "wallet") and cust.wallet:
                d.wallet_balance = cust.wallet.balance
            else:
                d.wallet_balance = 0
            d.started_at_str = d.active_session.started_at.strftime("%H:%M")
        else:
            d.elapsed_seconds = 0
            d.current_cost = 0
            d.wallet_balance = 0
            d.started_at_str = ""
    device_list.sort(key=_station_sort_key)
    return device_list


@login_required
def overview(request):
    ctx = _common()
    now = timezone.now()
    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    month_start = timezone.make_aware(datetime.combine(today.replace(day=1), time.min))

    device_list = list(ClientDevice.objects.filter(is_active=True))
    device_list = _enrich_devices(device_list, now)

    total_devices = max(10, len(device_list))
    active_count = sum(1 for d in device_list if d.status == ClientStatus.ACTIVE or d.active_session)
    free_count = max(0, total_devices - active_count)
    locked_count = sum(1 for d in device_list if d.status == ClientStatus.LOCKED and not d.active_session)
    offline_count = sum(1 for d in device_list if d.status == ClientStatus.OFFLINE)

    today_session_revenue = (
        GamingSession.objects.filter(
            ended_at__gte=today_start, status=SessionStatus.COMPLETED
        ).aggregate(total=Sum("cost"))["total"]
        or 0
    )
    today_deposit_revenue = (
        LedgerEntry.objects.filter(
            created_at__gte=today_start, entry_type=LedgerEntryType.DEPOSIT
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    today_revenue = today_session_revenue + today_deposit_revenue

    month_session_revenue = (
        GamingSession.objects.filter(
            ended_at__gte=month_start, status=SessionStatus.COMPLETED
        ).aggregate(total=Sum("cost"))["total"]
        or 0
    )
    month_deposit_revenue = (
        LedgerEntry.objects.filter(
            created_at__gte=month_start, entry_type=LedgerEntryType.DEPOSIT
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    month_revenue = month_session_revenue + month_deposit_revenue

    customer_count = Customer.objects.filter(is_active=True).count()

    # Chart data for last 7 days
    revenue_chart = []
    max_chart_val = 1
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        d_start = timezone.make_aware(datetime.combine(d, time.min))
        d_end = timezone.make_aware(datetime.combine(d, time.max))
        day_session = (
            GamingSession.objects.filter(
                ended_at__gte=d_start, ended_at__lte=d_end, status=SessionStatus.COMPLETED
            ).aggregate(total=Sum("cost"))["total"]
            or 0
        )
        day_deposit = (
            LedgerEntry.objects.filter(
                created_at__gte=d_start, created_at__lte=d_end, entry_type=LedgerEntryType.DEPOSIT
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        total_val = day_session + day_deposit
        if total_val > max_chart_val:
            max_chart_val = total_val
        revenue_chart.append(
            {
                "label": f"{d.month}/{d.day}",
                "day_name": ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"][d.weekday()],
                "session": day_session,
                "deposit": day_deposit,
                "total": total_val,
                "height_pct": 0,
            }
        )

    for item in revenue_chart:
        item["height_pct"] = max(8, int((item["total"] / max_chart_val) * 100)) if item["total"] > 0 else 5

    ctx.update(
        {
            "devices": device_list,
            "total_devices": total_devices,
            "active_count": active_count,
            "locked_count": locked_count,
            "free_count": free_count,
            "offline_count": offline_count,
            "today_revenue": today_revenue,
            "today_session_revenue": today_session_revenue,
            "today_deposit_revenue": today_deposit_revenue,
            "month_revenue": month_revenue,
            "month_session_revenue": month_session_revenue,
            "month_deposit_revenue": month_deposit_revenue,
            "customer_count": customer_count,
            "revenue_chart": revenue_chart,
            "recent_commands": DeviceCommand.objects.select_related("client")[:8],
            "codes": RegistrationCode.objects.filter(used_at__isnull=True)[:4],
            "outbox_recent": OutboxEvent.objects.order_by("-local_sequence")[:6],
            "outbox_labels": OUTBOX_LABELS,
            "now": now,
        }
    )
    return render(request, "edge/overview.html", ctx)


@login_required
def device_grid(request):
    ctx = _common()
    now = timezone.now()
    device_list = list(ClientDevice.objects.filter(is_active=True).order_by("name"))
    device_list = _enrich_devices(device_list, now)
    ctx["devices"] = device_list
    ctx["now"] = now
    return render(request, "edge/_device_grid.html", ctx)


@login_required
def devices(request):
    ctx = _common()
    now = timezone.now()
    qs = ClientDevice.objects.filter(is_active=True)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q))

    device_list = list(qs)
    device_list = _enrich_devices(device_list, now)

    total_devices = max(10, len(device_list))
    active_count = sum(1 for d in device_list if d.status == ClientStatus.ACTIVE or d.active_session)
    free_count = sum(1 for d in device_list if d.status == ClientStatus.IDLE and not d.active_session)
    locked_count = sum(1 for d in device_list if d.status == ClientStatus.LOCKED and not d.active_session)
    offline_count = sum(1 for d in device_list if d.status == ClientStatus.OFFLINE)

    from apps.pricing.models import Tariff
    tariffs = list(Tariff.objects.filter(is_active=True).order_by("name"))
    customers = list(Customer.objects.filter(is_active=True).select_related("wallet").order_by("full_name")[:100])

    ctx.update(
        {
            "devices": device_list,
            "total_devices": total_devices,
            "active_count": active_count,
            "free_count": free_count,
            "locked_count": locked_count,
            "offline_count": offline_count,
            "tariffs": tariffs,
            "customers": customers,
            "now": now,
            "q": q,
        }
    )
    return render(request, "edge/devices.html", ctx)


@login_required
def devices_stations_partial(request):
    now = timezone.now()
    qs = ClientDevice.objects.filter(is_active=True)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q))

    device_list = list(qs)
    device_list = _enrich_devices(device_list, now)

    from apps.pricing.models import Tariff
    tariffs = list(Tariff.objects.filter(is_active=True).order_by("name"))
    customers = list(Customer.objects.filter(is_active=True).select_related("wallet").order_by("full_name")[:100])

    return render(
        request,
        "edge/_stations_cards.html",
        {
            "devices": device_list,
            "tariffs": tariffs,
            "customers": customers,
            "now": now,
        },
    )


@login_required
def device_detail(request, device_id):
    ctx = _common()
    now = timezone.now()
    device = get_object_or_404(ClientDevice, id=device_id)
    enriched = _enrich_devices([device], now)[0]

    from apps.pricing.models import Tariff
    tariffs = list(Tariff.objects.filter(is_active=True).order_by("name"))
    customers = list(Customer.objects.filter(is_active=True).select_related("wallet").order_by("full_name")[:100])

    recent_sessions = list(
        GamingSession.objects.filter(device=device)
        .select_related("customer", "tariff")
        .order_by("-started_at")[:15]
    )

    ctx.update(
        {
            "device": enriched,
            "tariffs": tariffs,
            "customers": customers,
            "recent_sessions": recent_sessions,
            "now": now,
        }
    )
    return render(request, "edge/device_detail.html", ctx)


@login_required
@require_POST
def device_update(request, device_id):
    device = get_object_or_404(ClientDevice, id=device_id)
    name = request.POST.get("name", "").strip()
    if name:
        device.name = name

    tariff_id = request.POST.get("default_tariff_id", "").strip()
    meta = dict(device.metadata or {})
    if tariff_id:
        meta["default_tariff_id"] = tariff_id
    elif "default_tariff_id" in meta:
        meta.pop("default_tariff_id")
    device.metadata = meta

    if "is_active" in request.POST:
        device.is_active = request.POST.get("is_active") == "1"

    device.save(update_fields=["name", "metadata", "is_active", "updated_at"])
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="device.updated",
        object_type="device",
        object_id=str(device.id),
        metadata={"name": device.name, "metadata": device.metadata},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"تنظیمات ایستگاه «{device.name}» با موفقیت ذخیره شد.")
    return safe_redirect_next(request, "edge_devices")


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

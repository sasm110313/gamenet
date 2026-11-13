"""Local dashboard (edge only). Renders the authoritative local state."""

from __future__ import annotations

from apps.core.redirects import safe_redirect_next

from datetime import datetime, time, timedelta
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import (
    ClientDevice,
    ClientStatus,
    ConnectionStatus,
    HealthStatus,
    KioskStatus,
    OccupancyStatus,
    PowerStatus,
)
from apps.commands.models import DeviceCommand
from apps.core.catalog_payload import build_catalog_json
from apps.core.charts import build_revenue_charts
from apps.core.money import session_cost
from apps.core.roles import require_edge
from apps.customers.models import Customer
from apps.devices.models import RegistrationCode
from apps.devices.services import (
    RegistrationError,
    create_registration_code,
    create_station,
    deactivate_device,
    reset_device_pairing,
)
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.pricing.models import Tariff
from apps.sessions.models import BillingMode, DisconnectPolicy, GamingSession, SessionStatus
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
    "shutdown": "client.shutdown",
    "admin_unlock": "client.admin_unlock",
    "update": "client.update",
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
        d.is_offline_but_on = (
            d.connection_status == ConnectionStatus.OFFLINE
            and d.power_status == PowerStatus.ON
        )
        d.has_health_error = d.health_status == HealthStatus.ERROR
        if d.active_session:
            sess = d.active_session
            d.elapsed_seconds = sess.billable_elapsed_seconds(now)
            d.paused_seconds = sess.current_paused_seconds(now)
            d.is_paused = bool(sess.paused_at)
            d.connection_lost = bool(sess.connection_lost_at)
            d.current_cost = session_cost(sess.hourly_rate, d.elapsed_seconds)
            cust = sess.customer
            base_wallet = cust.wallet.balance if (hasattr(cust, "wallet") and cust.wallet) else 0
            credit_limit = getattr(cust, "credit_limit", 0) or 0
            total_available = base_wallet + credit_limit

            # Remaining money for gamer
            d.remaining_money = max(0, total_available - d.current_cost)
            d.wallet_balance = base_wallet

            # Remaining time (seconds)
            if sess.hourly_rate > 0:
                credit_remaining_seconds = int((d.remaining_money / sess.hourly_rate) * 3600)
            else:
                credit_remaining_seconds = 0

            if sess.billing_mode == BillingMode.TIMED and sess.planned_duration_minutes:
                d.planned_total_seconds = sess.planned_duration_minutes * 60
                d.timed_remaining_seconds = max(0, d.planned_total_seconds - d.elapsed_seconds)
                d.remaining_seconds = (
                    min(credit_remaining_seconds, d.timed_remaining_seconds)
                    if sess.hourly_rate > 0
                    else d.timed_remaining_seconds
                )
                d.spent_percent = min(
                    100, max(0, int((d.elapsed_seconds / max(1, d.planned_total_seconds)) * 100))
                )
            else:
                d.planned_total_seconds = None
                d.timed_remaining_seconds = None
                d.remaining_seconds = credit_remaining_seconds
                total_budget = max(1, d.current_cost + d.remaining_money)
                d.spent_percent = min(100, max(0, int((d.current_cost / total_budget) * 100)))

            # Low balance warning flag (under 10 minutes or under 5000 Tomans)
            d.is_low_balance = d.remaining_seconds < 600 or d.remaining_money < 5000

            # Active software / game running
            meta = d.metadata or {}
            d.active_app = (
                meta.get("active_app")
                or meta.get("current_game")
                or meta.get("foreground_window")
                or "میزکار کیوسک"
            )
            d.started_at_str = sess.started_at.strftime("%H:%M")
        else:
            d.elapsed_seconds = 0
            d.paused_seconds = 0
            d.is_paused = False
            d.connection_lost = False
            d.planned_total_seconds = None
            d.timed_remaining_seconds = None
            d.current_cost = 0
            d.remaining_money = 0
            d.remaining_seconds = 0
            d.is_low_balance = False
            d.spent_percent = 0
            d.active_app = "—"
            d.wallet_balance = 0
            d.started_at_str = ""

    device_list.sort(key=_station_sort_key)
    return device_list


def _orthogonal_counts(device_list):
    total_devices = max(10, len(device_list))
    online_count = sum(1 for d in device_list if d.connection_status == ConnectionStatus.ONLINE)
    offline_count = sum(1 for d in device_list if d.connection_status == ConnectionStatus.OFFLINE)
    power_on_count = sum(1 for d in device_list if d.power_status == PowerStatus.ON)
    active_count = sum(
        1 for d in device_list if d.occupancy_status == OccupancyStatus.BUSY or d.active_session
    )
    free_count = sum(
        1
        for d in device_list
        if d.connection_status == ConnectionStatus.ONLINE
        and d.occupancy_status == OccupancyStatus.FREE
        and not d.active_session
    )
    locked_count = sum(
        1 for d in device_list if d.kiosk_status == KioskStatus.LOCKED and not d.active_session
    )
    error_count = sum(1 for d in device_list if d.health_status == HealthStatus.ERROR)
    return {
        "total_devices": total_devices,
        "online_count": online_count,
        "offline_count": offline_count,
        "power_on_count": power_on_count,
        "active_count": active_count,
        "free_count": free_count,
        "locked_count": locked_count,
        "error_count": error_count,
    }


def _apply_device_filters(request, qs):
    q = request.GET.get("q", "").strip()
    conn = request.GET.get("conn", "").strip().upper()
    power = request.GET.get("power", "").strip().upper()
    kiosk = request.GET.get("kiosk", "").strip().upper()
    occ = request.GET.get("occ", "").strip().upper()
    health = request.GET.get("health", "").strip().upper()

    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(hostname__icontains=q) | Q(ip_address__icontains=q)
        )
    if conn in ConnectionStatus.values:
        qs = qs.filter(connection_status=conn)
    if power in PowerStatus.values:
        qs = qs.filter(power_status=power)
    if kiosk in KioskStatus.values:
        qs = qs.filter(kiosk_status=kiosk)
    if occ in OccupancyStatus.values:
        qs = qs.filter(occupancy_status=occ)
    if health in HealthStatus.values:
        qs = qs.filter(health_status=health)
    return qs, {
        "q": q,
        "conn": conn,
        "power": power,
        "kiosk": kiosk,
        "occ": occ,
        "health": health,
    }


@login_required
def overview(request):
    ctx = _common()
    now = timezone.now()
    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    month_start = timezone.make_aware(datetime.combine(today.replace(day=1), time.min))

    device_list = list(ClientDevice.objects.filter(is_active=True))
    device_list = _enrich_devices(device_list, now)
    counts_dict = _orthogonal_counts(device_list)

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
    charts = build_revenue_charts(today)

    ctx.update(
        {
            "devices": device_list,
            **counts_dict,
            "today_revenue": today_revenue,
            "today_session_revenue": today_session_revenue,
            "today_deposit_revenue": today_deposit_revenue,
            "month_revenue": month_revenue,
            "month_session_revenue": month_session_revenue,
            "month_deposit_revenue": month_deposit_revenue,
            "customer_count": customer_count,
            "revenue_chart": charts["daily"],
            "revenue_chart_weekly": charts["weekly"],
            "revenue_chart_monthly": charts["monthly"],
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
    all_devices = _enrich_devices(list(ClientDevice.objects.filter(is_active=True)), now)
    counts_dict = _orthogonal_counts(all_devices)

    qs, filters = _apply_device_filters(request, ClientDevice.objects.filter(is_active=True))
    device_list = _enrich_devices(list(qs), now)

    tariffs = list(Tariff.objects.filter(is_active=True).order_by("name"))
    customers = list(
        Customer.objects.filter(is_active=True)
        .select_related("wallet", "group", "group__tariff")
        .prefetch_related("rates")
        .order_by("full_name")[:150]
    )
    default_hourly_rate = int(ctx["config"].get("default_hourly_rate", 60000))
    operator_label = request.user.label or request.user.username
    catalog_json = build_catalog_json(
        customers=customers,
        tariffs=tariffs,
        devices=all_devices,
        default_hourly_rate=default_hourly_rate,
        operator_label=operator_label,
    )

    ctx.update(
        {
            "devices": device_list,
            **counts_dict,
            "tariffs": tariffs,
            "customers": customers,
            "BillingMode": BillingMode,
            "DisconnectPolicy": DisconnectPolicy,
            "default_hourly_rate": default_hourly_rate,
            "operator_label": operator_label,
            "catalog_json": catalog_json,
            "filter_qs": request.GET.urlencode(),
            "now": now,
            **filters,
        }
    )
    return render(request, "edge/devices.html", ctx)


@login_required
def devices_stations_partial(request):
    now = timezone.now()
    qs, _ = _apply_device_filters(request, ClientDevice.objects.filter(is_active=True))
    device_list = _enrich_devices(list(qs), now)

    tariffs = list(Tariff.objects.filter(is_active=True).order_by("name"))
    customers = list(
        Customer.objects.filter(is_active=True)
        .select_related("wallet")
        .order_by("full_name")[:150]
    )

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

    tariffs = list(Tariff.objects.filter(is_active=True).order_by("name"))
    customers = list(
        Customer.objects.filter(is_active=True)
        .select_related("wallet", "group", "group__tariff")
        .prefetch_related("rates")
        .order_by("full_name")[:150]
    )
    default_hourly_rate = int(ctx["config"].get("default_hourly_rate", 60000))
    operator_label = request.user.label or request.user.username
    catalog_json = build_catalog_json(
        customers=customers,
        tariffs=tariffs,
        devices=[enriched],
        default_hourly_rate=default_hourly_rate,
        operator_label=operator_label,
    )

    recent_sessions = list(
        GamingSession.objects.filter(device=device)
        .select_related("customer", "tariff", "customer_rate")
        .order_by("-started_at")[:15]
    )

    ctx.update(
        {
            "device": enriched,
            "tariffs": tariffs,
            "customers": customers,
            "BillingMode": BillingMode,
            "DisconnectPolicy": DisconnectPolicy,
            "default_hourly_rate": default_hourly_rate,
            "operator_label": operator_label,
            "catalog_json": catalog_json,
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

    if "mac_address" in request.POST:
        from apps.devices.wol import WolError, normalize_mac

        mac_raw = request.POST.get("mac_address", "").strip()
        if mac_raw:
            try:
                meta["mac_address"] = normalize_mac(mac_raw)
            except WolError as exc:
                messages.error(request, str(exc))
                return safe_redirect_next(request, "edge_device_detail", device_id=device.id)
        else:
            meta.pop("mac_address", None)

    if "idle_shutdown_minutes" in request.POST:
        try:
            val = int(request.POST.get("idle_shutdown_minutes", 15))
            meta["idle_shutdown_minutes"] = max(0, min(720, val))
        except (ValueError, TypeError):
            pass

    device.metadata = meta

    if "is_active" in request.POST:
        device.is_active = request.POST.get("is_active") == "1"

    from django.db import transaction
    from apps.synchronization.events import emit

    with transaction.atomic():
        device.save(update_fields=["name", "metadata", "is_active", "updated_at"])
        emit(
            "device.updated",
            aggregate_type="device",
            aggregate_id=str(device.id),
            payload={
                "device_id": str(device.id),
                "name": device.name,
                "metadata": device.metadata,
                "is_active": device.is_active,
            },
        )
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
    if action == "wake":
        from apps.devices.wol import WolError, send_wol_magic_packet, sync_device_mac

        mac = sync_device_mac(device, ip_address=device.ip_address, emit_sync=True)
        if not mac:
            messages.error(
                request,
                f"برای روشن کردن {device.name} با LAN، ابتدا آدرس MAC آن را در تنظیمات ایستگاه وارد کنید یا یک‌بار کلاینت را متصل نمایید.",
            )
            return safe_redirect_next(request, "edge_device_detail", device_id=device.id)
        try:
            wol_res = send_wol_magic_packet(mac, ip_hint=device.ip_address)
        except WolError as exc:
            messages.error(request, str(exc))
            return safe_redirect_next(request, "edge_devices")
        AuditLog.objects.create(
            actor=request.user,
            actor_label=request.user.label,
            action="device.wake",
            object_type="device",
            object_id=str(device.id),
            metadata={"name": device.name, "mac_address": wol_res["mac"], "targets": wol_res["targets"][:6]},
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        from apps.devices.wol import is_lan_host_reachable
        is_up = is_lan_host_reachable(device.ip_address)
        if is_up:
            ping_msg = f"نتیجه واقعی شبکه: پینگ مثبت است و سخت‌افزار در شبکه فعال است (IP: {device.ip_address})."
        else:
            ping_msg = f"نتیجه واقعی شبکه: پینگ هنوز پاسخ نداده است (سیستم در حال بوت است یا تنظیمات WoL در کارت شبکه/BIOS سیستم غیرفعال است)."
        messages.success(
            request,
            f"بسته روشن‌سازی (Wake-on-LAN) برای «{device.name}» ({wol_res['mac']}) ارسال شد. {ping_msg}",
        )
        return safe_redirect_next(request, "edge_devices")

    if action == "unlock":
        messages.error(
            request,
            "امکان باز کردن سیستم بدون مشتری وجود ندارد. برای باز کردن سیستم، لطفاً از فرم «شروع نشست» و انتخاب مشتری دارای اعتبار استفاده نمایید.",
        )
        return safe_redirect_next(request, "edge_device_detail", device_id=device.id)

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
    labels = {
        "lock": "قفل صفحه",
        "unlock": "باز کردن",
        "ping": "پینگ",
        "restart": "راه‌اندازی مجدد (Restart)",
        "shutdown": "خاموش کردن (Shutdown)",
        "admin_unlock": "ورود ادمین",
    }
    label = labels.get(action, action)
    messages.success(request, f"دستور «{label}» برای «{device.name}» ثبت و ارسال شد.")
    return safe_redirect_next(request, "edge_devices")


@login_required
@require_POST
def device_screenshot_capture(request, device_id):
    from apps.devices.remote_ws import get_latest_remote_frame, request_screenshot_sync

    device = get_object_or_404(ClientDevice, id=device_id)
    if device.connection_status == ConnectionStatus.OFFLINE or device.status == ClientStatus.OFFLINE:
        from apps.devices.wol import is_lan_host_reachable
        lan_up = is_lan_host_reachable(device.ip_address)
        if lan_up:
            err = f"سیستم در شبکه فعال است ({device.ip_address}) اما کلاینت GameNet باز نیست."
        else:
            err = "سیستم خاموش است یا کلاینت بسته می‌باشد (ارتباط شبکه قطع است)."
        return JsonResponse(
            {"ok": False, "error": err},
            status=409,
        )
    frame = request_screenshot_sync(device, timeout=8.0, width=1280, quality=84)
    if not frame or not frame.get("data"):
        frame = get_latest_remote_frame(device.id)
        if frame and frame.get("data"):
            return JsonResponse(
                {
                    "ok": True,
                    "stale": True,
                    "width": frame.get("width", 0),
                    "height": frame.get("height", 0),
                    "captured_at": frame.get("captured_at", ""),
                    "data_url": f"data:image/jpeg;base64,{frame['data']}",
                }
            )
        return JsonResponse(
            {
                "ok": False,
                "error": "کلاینت در مهلت مقرر تصویر صفحه را ارسال نکرد. مطمئن شوید برنامه کلاینت به‌روز و متصل است.",
            },
            status=504,
        )
    return JsonResponse(
        {
            "ok": True,
            "stale": False,
            "width": frame.get("width", 0),
            "height": frame.get("height", 0),
            "captured_at": frame.get("captured_at", ""),
            "data_url": f"data:image/jpeg;base64,{frame['data']}",
        }
    )


@login_required
def device_screenshot_latest(request, device_id):
    from apps.devices.remote_ws import decode_frame_jpeg, get_latest_remote_frame

    device = get_object_or_404(ClientDevice, id=device_id)
    frame = get_latest_remote_frame(device.id)
    if not frame or not frame.get("data"):
        if request.GET.get("raw") == "1":
            return HttpResponse(status=404)
        return JsonResponse({"ok": False, "error": "هنوز اسکرین‌شاتی ثبت نشده است."}, status=404)
    if request.GET.get("raw") == "1":
        return HttpResponse(decode_frame_jpeg(frame), content_type="image/jpeg")
    return JsonResponse(
        {
            "ok": True,
            "width": frame.get("width", 0),
            "height": frame.get("height", 0),
            "captured_at": frame.get("captured_at", ""),
            "data_url": f"data:image/jpeg;base64,{frame['data']}",
        }
    )


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
def device_create(request):
    name = request.POST.get("name", "").strip()
    tariff_id = request.POST.get("default_tariff_id", "").strip()
    try:
        idle_mins = int(request.POST.get("idle_shutdown_minutes", 15))
    except (ValueError, TypeError):
        idle_mins = 15
    try:
        device = create_station(
            name,
            idle_shutdown_minutes=idle_mins,
            tariff_id=tariff_id,
        )
    except RegistrationError as exc:
        messages.error(request, str(exc))
        return safe_redirect_next(request, "edge_devices")
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="device.created",
        object_type="device",
        object_id=str(device.id),
        metadata={"name": device.name, "idle_shutdown_minutes": idle_mins},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"ایستگاه «{device.name}» با موفقیت ایجاد شد.")
    return safe_redirect_next(request, "edge_devices")


@login_required
@require_POST
def device_reset(request, device_id):
    device = get_object_or_404(ClientDevice, id=device_id)
    try:
        reset_device_pairing(device, actor=request.user, notify_client=True)
    except RegistrationError as exc:
        messages.error(request, str(exc))
        return safe_redirect_next(request, "edge_devices")
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="device.reset",
        object_type="device",
        object_id=str(device.id),
        metadata={"name": device.name},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(
        request,
        f"اتصال کلاینت «{device.name}» ریست شد و ایستگاه آماده ثبت روی سیستم جدید است.",
    )
    return safe_redirect_next(request, "edge_devices")


@login_required
@require_POST
def deactivate(request, device_id):
    device = get_object_or_404(ClientDevice, id=device_id)
    try:
        deactivate_device(device, actor=request.user)
    except RegistrationError as exc:
        messages.error(request, str(exc))
        return safe_redirect_next(request, "edge_devices")
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="device.deactivated",
        object_type="device",
        object_id=str(device.id),
        metadata={"name": device.name},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.warning(request, f"ایستگاه «{device.name}» حذف و غیرفعال شد.")
    return safe_redirect_next(request, "edge_devices")


@login_required
def cloud_health(request):
    from apps.synchronization.edge_ws import is_ws_connected
    from apps.synchronization.sync_log import last_sync_error, read_sync_logs, sync_log_path

    ctx = _common()
    ctx.update(
        {
            "events": OutboxEvent.objects.order_by("-local_sequence")[:50],
            "outbox_labels": OUTBOX_LABELS,
            "cloud_base": settings.CLOUD_BASE_URL,
            "ws_connected": is_ws_connected(),
            "sync_logs": read_sync_logs(limit=60),
            "last_sync_error": last_sync_error(),
            "sync_log_file": str(sync_log_path()),
        }
    )
    return render(request, "edge/cloud.html", ctx)


@login_required
@require_POST
def cloud_retry(request):
    from apps.synchronization.daemon import trigger_sync_now

    count = retry_failed(request.POST.get("event_id") or None)
    trigger_sync_now()
    messages.info(request, f"{count} رویداد برای ارسال مجدد آماده شد.")
    return redirect("edge_cloud")


@login_required
@require_POST
def cloud_register(request):
    from apps.synchronization.daemon import trigger_sync_now
    from apps.synchronization.sync_log import record_sync_log

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
            edge_id=str(identity.edge_id),
        )
    except (CloudUnavailable, CloudRejected) as exc:
        record_sync_log("ERROR", "register", f"ثبت Edge در سرور آنلاین ناموفق بود: {exc}")
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
    record_sync_log("INFO", "register", f"سرور محلی با شناسه {response['edge_id']} در {settings.CLOUD_BASE_URL} ثبت شد.")
    trigger_sync_now()
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="edge.registered",
        object_type="edge",
        object_id=response["edge_id"],
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, "Edge با موفقیت در Cloud ثبت شد و همگام‌سازی آغاز گردید.")
    return redirect("edge_cloud")


@login_required
@require_POST
def cloud_sync_now(request):
    from apps.synchronization.daemon import trigger_sync_now
    from apps.synchronization.sync_log import record_sync_log

    record_sync_log("INFO", "manual", "درخواست همگام‌سازی فوری و بررسی اتصال سرور آنلاین از پنل ادمین...")
    trigger_sync_now()
    messages.info(request, "فرمان همگام‌سازی فوری به پس‌زمینه ارسال شد.")
    return redirect("edge_cloud")


@login_required
@require_POST
def cloud_test_connection(request):
    import requests as req_lib
    from apps.synchronization.sync_log import record_sync_log

    url = f"{settings.CLOUD_BASE_URL.rstrip('/')}/healthz"
    try:
        r = req_lib.get(url, timeout=8, verify=settings.CLOUD_CA_BUNDLE or True)
        body = r.text[:200]
        if r.status_code == 200:
            record_sync_log("INFO", "diag", f"تست اتصال HTTPS به {url} موفق بود: HTTP {r.status_code} {body}")
            messages.success(request, f"اتصال به سرور آنلاین ({url}) برقرار است (HTTP {r.status_code}).")
        else:
            record_sync_log("WARNING", "diag", f"تست اتصال به {url} پاسخ غیرمنتظره داد: HTTP {r.status_code} {body}")
            messages.warning(request, f"سرور آنلاین پاسخ غیرمنتظره داد: HTTP {r.status_code}")
    except Exception as exc:
        record_sync_log("ERROR", "diag", f"خطا در تست اتصال به {url}: {type(exc).__name__}: {exc}")
        messages.error(request, f"خطا در اتصال به سرور آنلاین: {exc}")
    return redirect("edge_cloud")


@login_required
@require_POST
def cloud_reset(request):
    from apps.synchronization.edge_credentials import clear_registration
    from apps.synchronization.sync_log import record_sync_log

    clear_registration()
    ensure_identity()
    record_sync_log("WARNING", "register", "اعتبارنامه قبلی اتصال به ابر پاک شد و هویت جدید Edge آماده ثبت است.")
    messages.warning(request, "اتصال قبلی به سرور آنلاین پاک شد. اکنون می‌توانید کد ثبت جدید را وارد کنید.")
    return redirect("edge_cloud")


@login_required
@require_POST
def emit_test(request):
    from apps.synchronization.edge_runtime import emit_test_event

    event = emit_test_event(note=request.POST.get("note", "manual test"))
    messages.success(request, f"رویداد آزمایشی #{event.local_sequence} ثبت شد.")
    return redirect("edge_cloud")


@login_required
@require_POST
def edge_trigger_clients_update(request):
    require_edge()
    from apps.synchronization.updater import trigger_client_updates

    res = trigger_client_updates()
    messages.success(request, res.get("message", "فرمان به‌روزرسانی برای کلاینت‌ها ارسال شد."))
    return safe_redirect_next(request, "edge_devices")

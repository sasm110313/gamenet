"""Cloud dashboard. Read-only replica view plus remote control."""

from __future__ import annotations

from apps.core.redirects import safe_redirect_next

from datetime import datetime, time, timedelta
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
from apps.commands.models import CommandStatus, RemoteCommand
from apps.core.catalog_payload import build_catalog_json
from apps.core.charts import build_revenue_charts
from apps.core.money import session_cost
from apps.core.roles import require_cloud
from apps.customers.models import Customer
from apps.devices.models import RegistrationCode
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.pricing.models import CustomerRate, Tariff
from apps.sessions.models import BillingMode, DisconnectPolicy, GamingSession, SessionStatus
from apps.synchronization.command_service import issue_command
from apps.synchronization.models import (
    ConfigSnapshot,
    EdgeNode,
    EdgeRegistrationCode,
    EdgeStatus,
    SyncEvent,
)
import uuid

logger = logging.getLogger("gamenet.dashboard.cloud")


def _cloud_default_hourly_rate() -> int:
    snap = ConfigSnapshot.objects.filter(is_active=True).order_by("-version").first()
    if snap and isinstance(snap.payload, dict):
        return int(snap.payload.get("default_hourly_rate", 60000) or 60000)
    return 60000


def _active_salon_server():
    return (
        EdgeNode.objects.exclude(status=EdgeStatus.REVOKED)
        .filter(revoked_at__isnull=True)
        .order_by(F("last_heartbeat_at").desc(nulls_last=True), "-created_at")
        .first()
    )


def _counts():
    now = timezone.now()
    active_edge_ids = list(
        EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).values_list("id", flat=True)
    )
    devices_qs = ClientDevice.objects.filter(is_active=True, edge_id__in=active_edge_ids)
    return {
        "edges_online": EdgeNode.objects.filter(status=EdgeStatus.ONLINE).count(),
        "edges_total": len(active_edge_ids),
        "devices_online": devices_qs.filter(connection_status=ConnectionStatus.ONLINE).count(),
        "devices_total": devices_qs.count(),
        "locked_count": devices_qs.filter(kiosk_status=KioskStatus.LOCKED).count(),
        "active_count": GamingSession.objects.filter(status=SessionStatus.ACTIVE).count(),
        "events_total": SyncEvent.objects.count(),
        "events_rejected": SyncEvent.objects.filter(status="REJECTED").count(),
        "commands_pending": RemoteCommand.objects.filter(status=CommandStatus.PENDING).count(),
        "last_sync": EdgeNode.objects.exclude(status=EdgeStatus.REVOKED)
        .order_by(F("last_sync_at").desc(nulls_last=True))
        .values_list("last_sync_at", flat=True)
        .first(),
        "now": now,
        "stale_after": now - timedelta(seconds=90),
    }


def _station_sort_key(d):
    name = (d.name or "").upper().strip()
    if name.startswith("PC-"):
        part = name[3:]
        if part.isdigit():
            return (0, int(part))
    return (1, name)


def _annotate_devices(devices_qs, now=None):
    if now is None:
        now = timezone.now()
    devices = list(devices_qs)
    if not devices:
        return []
    edge_ids = {d.edge_id for d in devices}
    device_ids = {d.id for d in devices}

    edges = {e.id: e for e in EdgeNode.objects.filter(id__in=edge_ids)}
    active_sessions = {
        s.device_id: s
        for s in GamingSession.objects.filter(
            device_id__in=device_ids, status=SessionStatus.ACTIVE
        ).select_related("customer", "customer__wallet", "tariff", "customer_rate")
    }

    for d in devices:
        d.edge_node = edges.get(d.edge_id)
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
            d.current_cost, d.discount_amount = sess.calculate_cost(d.elapsed_seconds)
            wallet = getattr(sess.customer, "wallet", None)
            base_wallet = int(wallet.balance) if wallet else 0
            credit_limit = int(getattr(sess.customer, "credit_limit", 0) or 0)
            total_credit = base_wallet + credit_limit
            d.wallet_balance = base_wallet
            d.remaining_money = max(0, total_credit - d.current_cost)
            hourly_rate = sess.hourly_rate or 40000
            credit_remaining_seconds = sess.calculate_remaining_seconds(
                d.remaining_money, d.elapsed_seconds
            )

            if sess.billing_mode == BillingMode.TIMED and sess.planned_duration_minutes:
                d.planned_total_seconds = sess.planned_duration_minutes * 60
                d.timed_remaining_seconds = max(0, d.planned_total_seconds - d.elapsed_seconds)
                d.remaining_seconds = (
                    min(credit_remaining_seconds, d.timed_remaining_seconds)
                    if hourly_rate > 0
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
                d.spent_percent = min(100, int((d.current_cost / total_budget) * 100))

            d.is_low_balance = d.remaining_seconds < 600 or d.remaining_money < 5000
            d.started_at_str = sess.started_at.strftime("%H:%M")
        else:
            d.elapsed_seconds = 0
            d.paused_seconds = 0
            d.is_paused = False
            d.connection_lost = False
            d.planned_total_seconds = None
            d.timed_remaining_seconds = None
            d.current_cost = 0
            d.wallet_balance = 0
            d.remaining_money = 0
            d.remaining_seconds = 0
            d.is_low_balance = False
            d.spent_percent = 0
            d.started_at_str = ""
        meta = d.metadata or {}
        d.active_app = (
            meta.get("active_app")
            or meta.get("current_game")
            or meta.get("foreground_window")
            or "میزکار کیوسک"
        )

    devices.sort(key=_station_sort_key)
    return devices


def _orthogonal_cloud_counts(devices_list):
    total_devices = len(devices_list)
    online_count = sum(1 for d in devices_list if d.connection_status == ConnectionStatus.ONLINE)
    offline_count = sum(1 for d in devices_list if d.connection_status == ConnectionStatus.OFFLINE)
    power_on_count = sum(1 for d in devices_list if d.power_status == PowerStatus.ON)
    active_count = sum(
        1 for d in devices_list if d.occupancy_status == OccupancyStatus.BUSY or d.active_session
    )
    free_count = sum(
        1
        for d in devices_list
        if d.connection_status == ConnectionStatus.ONLINE
        and d.occupancy_status == OccupancyStatus.FREE
        and not d.active_session
    )
    locked_count = sum(
        1 for d in devices_list if d.kiosk_status == KioskStatus.LOCKED and not d.active_session
    )
    error_count = sum(1 for d in devices_list if d.health_status == HealthStatus.ERROR)
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


@login_required
def overview(request):
    require_cloud()
    now = timezone.now()
    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    month_start = timezone.make_aware(datetime.combine(today.replace(day=1), time.min))

    # Single local salon server
    salon_server = _active_salon_server()

    devices_raw = ClientDevice.objects.filter(is_active=True)
    if salon_server:
        devices_raw = devices_raw.filter(edge_id=salon_server.id)
    devices_annotated = _annotate_devices(devices_raw, now)

    ortho = _orthogonal_cloud_counts(devices_annotated)
    total_devices = ortho["total_devices"]
    active_count = ortho["active_count"]
    free_count = ortho["free_count"]
    locked_count = ortho["locked_count"]
    offline_count = ortho["offline_count"]

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
    today_revenue = today_session_revenue

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
    month_revenue = month_session_revenue

    customer_count = Customer.objects.filter(is_active=True).count()
    charts = build_revenue_charts(today)

    ctx = {
        "salon_server": salon_server,
        "devices": devices_annotated,
        "total_devices": total_devices,
        "active_count": active_count,
        "locked_count": locked_count,
        "free_count": free_count,
        "offline_count": offline_count,
        "online_count": ortho["online_count"],
        "power_on_count": ortho["power_on_count"],
        "error_count": ortho["error_count"],
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
        "now": now,
    }
    return render(request, "cloud/overview.html", ctx)


def _apply_cloud_device_filters(qs, request):
    edge_id = (request.GET.get("edge") or "").strip()
    q = (request.GET.get("q") or "").strip()
    conn = (request.GET.get("conn") or "").strip().upper()
    power = (request.GET.get("power") or "").strip().upper()
    kiosk = (request.GET.get("kiosk") or "").strip().upper()
    occ = (request.GET.get("occ") or "").strip().upper()
    health = (request.GET.get("health") or "").strip().upper()

    if edge_id:
        qs = qs.filter(edge_id=edge_id)
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
        "edge": edge_id,
        "q": q,
        "conn": conn,
        "power": power,
        "kiosk": kiosk,
        "occ": occ,
        "health": health,
    }


@login_required
def device_grid(request):
    require_cloud()
    now = timezone.now()
    base_qs = ClientDevice.objects.filter(is_active=True)
    if not (request.GET.get("edge") or "").strip():
        salon_server = _active_salon_server()
        if salon_server:
            base_qs = base_qs.filter(edge_id=salon_server.id)
    qs, _ = _apply_cloud_device_filters(base_qs, request)
    devices = _annotate_devices(qs.order_by("name"), now)
    return render(request, "cloud/_device_grid.html", {"devices": devices, "now": now})


@login_required
def devices(request):
    require_cloud()
    ctx = _counts()
    edges_list = EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).order_by(
        F("last_heartbeat_at").desc(nulls_last=True), "name"
    )
    active_edge_ids = [e.id for e in edges_list]
    salon_server = _active_salon_server()
    base_qs = ClientDevice.objects.filter(is_active=True, edge_id__in=active_edge_ids)
    all_devices = _annotate_devices(
        (base_qs.filter(edge_id=salon_server.id) if salon_server else base_qs).order_by("name")
    )
    ortho_all = _orthogonal_cloud_counts(all_devices)
    filtered_base = base_qs
    if not (request.GET.get("edge") or "").strip() and salon_server:
        filtered_base = filtered_base.filter(edge_id=salon_server.id)
    qs, filters = _apply_cloud_device_filters(filtered_base, request)
    devices_list = _annotate_devices(qs.order_by("name"))
    customers_list = list(
        Customer.objects.filter(is_active=True)
        .select_related("wallet", "group__tariff")
        .prefetch_related("rates")
        .order_by("full_name")[:150]
    )
    tariffs = list(Tariff.objects.filter(is_active=True).order_by("name"))
    default_rate = _cloud_default_hourly_rate()
    operator_label = (
        getattr(request.user, "label", "")
        or request.user.get_full_name()
        or request.user.get_username()
    )
    catalog_json = build_catalog_json(
        customers=customers_list,
        tariffs=tariffs,
        devices=all_devices,
        default_hourly_rate=default_rate,
        operator_label=operator_label,
    )

    filter_params = request.GET.copy()
    ctx.update(
        {
            "devices": devices_list,
            "edges": edges_list,
            "selected_edge": filters["edge"],
            "q": filters["q"],
            "search_query": filters["q"],
            "filters": filters,
            "filter_qs": filter_params.urlencode(),
            "ortho": ortho_all,
            "ConnectionStatus": ConnectionStatus,
            "PowerStatus": PowerStatus,
            "KioskStatus": KioskStatus,
            "OccupancyStatus": OccupancyStatus,
            "HealthStatus": HealthStatus,
            "customers": customers_list,
            "tariffs": tariffs,
            "default_hourly_rate": default_rate,
            "BillingMode": BillingMode,
            "DisconnectPolicy": DisconnectPolicy,
            "operator_label": operator_label,
            "catalog_json": catalog_json,
            "codes": RegistrationCode.objects.order_by("-created_at")[:10],
        }
    )
    return render(request, "cloud/devices.html", ctx)


@login_required
def device_detail(request, device_id):
    require_cloud()
    device = get_object_or_404(ClientDevice, id=device_id)
    edge = EdgeNode.objects.filter(id=device.edge_id).first()
    active_session = (
        GamingSession.objects.filter(device_id=device.id, status=SessionStatus.ACTIVE)
        .select_related("customer", "customer__wallet", "tariff", "customer_rate")
        .first()
    )
    recent_commands = (
        RemoteCommand.objects.filter(edge=edge, payload__device_id=str(device.id)).order_by(
            "-issued_at"
        )[:30]
        if edge
        else []
    )
    recent_sessions = list(
        GamingSession.objects.filter(device_id=device.id)
        .select_related("customer", "tariff", "customer_rate")
        .order_by("-started_at")[:15]
    )

    customers_list = list(
        Customer.objects.filter(edge_id=device.edge_id, is_active=True)
        .select_related("wallet", "group__tariff")
        .prefetch_related("rates")
        .order_by("full_name")[:150]
    )
    tariffs = list(
        Tariff.objects.filter(edge_id=device.edge_id, is_active=True).order_by("name")
    )
    default_rate = _cloud_default_hourly_rate()
    operator_label = (
        getattr(request.user, "label", "")
        or request.user.get_full_name()
        or request.user.get_username()
    )
    device.active_session = active_session
    device.is_offline_but_on = (
        device.connection_status == ConnectionStatus.OFFLINE
        and device.power_status == PowerStatus.ON
    )
    device.has_health_error = device.health_status == HealthStatus.ERROR
    if active_session:
        now = timezone.now()
        device.elapsed_seconds = active_session.billable_elapsed_seconds(now)
        device.paused_seconds = active_session.current_paused_seconds(now)
        device.is_paused = bool(active_session.paused_at)
        device.connection_lost = bool(active_session.connection_lost_at)
        device.current_cost, device.discount_amount = active_session.calculate_cost(device.elapsed_seconds)
    device.active_app = (
        (device.metadata or {}).get("active_app")
        or (device.metadata or {}).get("current_game")
        or ""
    )

    catalog_json = build_catalog_json(
        customers=customers_list,
        tariffs=tariffs,
        devices=[device],
        default_hourly_rate=default_rate,
        operator_label=operator_label,
    )

    ctx = _counts()
    ctx.update(
        {
            "device": device,
            "edge": edge,
            "active_session": active_session,
            "commands": recent_commands,
            "recent_sessions": recent_sessions,
            "customers": customers_list,
            "tariffs": tariffs,
            "default_hourly_rate": default_rate,
            "BillingMode": BillingMode,
            "DisconnectPolicy": DisconnectPolicy,
            "operator_label": operator_label,
            "catalog_json": catalog_json,
        }
    )
    return render(request, "cloud/device_detail.html", ctx)


@login_required
@require_POST
def device_update(request, device_id):
    require_cloud()
    device = get_object_or_404(ClientDevice, id=device_id)
    edge = EdgeNode.objects.filter(id=device.edge_id).first()
    if edge is None:
        messages.error(request, "Edge مربوط به این دستگاه یافت نشد.")
        return safe_redirect_next(request, "cloud_devices")

    name = request.POST.get("name", "").strip()[:80]
    if name:
        device.name = name

    tariff_id = request.POST.get("default_tariff_id", "").strip()
    meta = dict(device.metadata or {})
    if tariff_id:
        meta["default_tariff_id"] = tariff_id
    elif "default_tariff_id" in meta:
        meta.pop("default_tariff_id")

    cmd_payload = {
        "device_id": str(device.id),
        "name": device.name,
        "default_tariff_id": tariff_id,
        "is_active": device.is_active if "is_active" not in request.POST else (request.POST.get("is_active") == "1"),
    }
    if "mac_address" in request.POST:
        from apps.devices.wol import WolError, normalize_mac

        mac_raw = request.POST.get("mac_address", "").strip()
        if mac_raw:
            try:
                mac_clean = normalize_mac(mac_raw)
            except WolError as exc:
                messages.error(request, str(exc))
                return safe_redirect_next(request, "cloud_device_detail", device_id=device.id)
            meta["mac_address"] = mac_clean
            cmd_payload["mac_address"] = mac_clean
        else:
            meta.pop("mac_address", None)
            cmd_payload["mac_address"] = ""

    device.metadata = meta

    if "is_active" in request.POST:
        device.is_active = request.POST.get("is_active") == "1"

    device.save(update_fields=["name", "metadata", "is_active", "updated_at"])

    issue_command(
        edge,
        "device.update",
        cmd_payload,
        actor=request.user,
    )
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="remote.device.updated",
        object_type="device",
        object_id=str(device.id),
        metadata={"edge_id": str(edge.id), "name": device.name, "default_tariff_id": tariff_id},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"تنظیمات ایستگاه «{device.name}» ذخیره و به سرور سالن ارسال شد.")
    return safe_redirect_next(request, "cloud_device_detail", device_id=device.id)


@login_required
@require_POST
def device_screenshot_capture(request, device_id):
    require_cloud()
    from apps.devices.remote_ws import get_latest_remote_frame, request_screenshot_sync

    device = get_object_or_404(ClientDevice, id=device_id)
    if device.connection_status == ConnectionStatus.OFFLINE:
        return JsonResponse(
            {"ok": False, "error": "کلاینت به هاب محلی متصل نیست (آفلاین)."},
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
                "error": "کلاینت در مهلت مقرر تصویر صفحه را ارسال نکرد. مطمئن شوید کلاینت و سرور سالن متصل و به‌روز هستند.",
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
    require_cloud()
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
def device_start_session(request, device_id):
    require_cloud()
    device = get_object_or_404(ClientDevice, id=device_id)
    edge = EdgeNode.objects.filter(id=device.edge_id).first()
    if edge is None:
        messages.error(request, "Edge مربوط به این دستگاه یافت نشد.")
        return safe_redirect_next(request, "cloud_devices")

    customer_id = request.POST.get("customer_id")
    customer = get_object_or_404(Customer, id=customer_id)
    session_id = uuid.uuid4()

    wallet = getattr(customer, "wallet", None)
    balance = getattr(wallet, "balance", 0) if wallet else 0
    debt = getattr(customer, "debt_balance", 0) or 0
    if balance <= 0:
        messages.error(
            request,
            f"شروع نشست ممکن نیست! موجودی کیف پول {customer.full_name} صفر است. ابتدا حساب را شارژ کنید.",
        )
        return safe_redirect_next(request, "cloud_device_detail", device_id=device.id)
    if debt > 0 and balance <= 0:
        messages.error(
            request,
            f"مشتری {customer.full_name} دارای بدهی تسویه‌نشده ({debt:,} تومان) با موجودی صفر است. تا زمان تسویه بدهی، امکان شروع بازی وجود ندارد.",
        )
        return safe_redirect_next(request, "cloud_device_detail", device_id=device.id)

    rate_choice = (request.POST.get("rate_choice") or "").strip()
    rate_id = (request.POST.get("customer_rate_id") or "").strip() or None
    tariff_id = (request.POST.get("tariff_id") or "").strip() or None
    if rate_choice.startswith("rate:"):
        rate_id = rate_choice.split(":", 1)[1].strip() or None
        tariff_id = None
    elif rate_choice.startswith("tariff:"):
        tariff_id = rate_choice.split(":", 1)[1].strip() or None
        rate_id = None

    billing_mode = (request.POST.get("billing_mode") or BillingMode.CREDIT).strip().upper()
    if billing_mode not in BillingMode.values:
        billing_mode = BillingMode.CREDIT

    planned_minutes = None
    if billing_mode == BillingMode.TIMED:
        raw_mins = (request.POST.get("planned_duration_minutes") or "").strip()
        try:
            planned_minutes = int(raw_mins)
        except (TypeError, ValueError):
            planned_minutes = 0
        if planned_minutes < 5 or planned_minutes > 720:
            messages.error(request, "در روش زمانی، مدت بازی باید بین ۵ تا ۷۲۰ دقیقه باشد.")
            return safe_redirect_next(request, "cloud_devices")

    disconnect_policy = (
        (request.POST.get("disconnect_policy") or DisconnectPolicy.PAUSE).strip().upper()
    )
    if disconnect_policy not in DisconnectPolicy.values:
        disconnect_policy = DisconnectPolicy.PAUSE

    issue_command(
        edge,
        "session.start",
        {
            "session_id": str(session_id),
            "customer_id": str(customer.id),
            "device_id": str(device.id),
            "customer_rate_id": str(rate_id) if rate_id else None,
            "tariff_id": str(tariff_id) if tariff_id else None,
            "billing_mode": billing_mode,
            "planned_duration_minutes": planned_minutes,
            "disconnect_policy": disconnect_policy,
        },
        actor=request.user,
    )
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="remote.session.started",
        object_type="device",
        object_id=str(device.id),
        metadata={
            "edge_id": str(edge.id),
            "device_name": device.name,
            "customer_name": customer.full_name,
            "billing_mode": billing_mode,
            "planned_duration_minutes": planned_minutes,
            "disconnect_policy": disconnect_policy,
        },
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(
        request, f"دستور شروع نشست برای {customer.full_name} روی {device.name} ارسال شد."
    )
    return safe_redirect_next(request, "cloud_devices")


@login_required
@require_POST
def create_client_code(request):
    require_cloud()
    edge_id = request.POST.get("edge_id")
    edge = get_object_or_404(EdgeNode, id=edge_id)
    label = request.POST.get("label", "").strip()[:80]

    issue_command(
        edge,
        "edge.create_client_code",
        {"label": label},
        actor=request.user,
    )
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="remote.client_code.create",
        object_type="edge",
        object_id=str(edge.id),
        metadata={"edge_name": edge.name, "label": label},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"دستور ساخت کد ثبت کلاینت برای «{edge.name}» صادر شد.")
    return safe_redirect_next(request, "cloud_devices")


@login_required
def edges(request):
    require_cloud()
    now = timezone.now()
    salon_server = _active_salon_server()
    devices = (
        _annotate_devices(
            ClientDevice.objects.filter(edge_id=salon_server.id, is_active=True).order_by("name"),
            now,
        )
        if salon_server
        else []
    )
    commands_qs = RemoteCommand.objects.select_related("edge", "created_by").order_by("-issued_at")[:60]
    events_qs = SyncEvent.objects.select_related("edge").order_by("-local_sequence")[:60]
    snapshots = ConfigSnapshot.objects.order_by("-version")[:20]
    active_config = ConfigSnapshot.objects.filter(is_active=True).order_by("-version").first()
    active_codes = EdgeRegistrationCode.objects.filter(
        used_at__isnull=True, expires_at__gt=now
    ).order_by("-created_at")[:10]
    all_edges = EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).filter(revoked_at__isnull=True).order_by(
        F("last_heartbeat_at").desc(nulls_last=True), "-created_at"
    )
    ctx = _counts()
    ctx.update(
        {
            "salon_server": salon_server,
            "all_edges": all_edges,
            "active_codes": active_codes,
            "devices": devices,
            "commands": commands_qs,
            "events": events_qs,
            "snapshots": snapshots,
            "active": active_config,
        }
    )
    return render(request, "cloud/edges.html", ctx)


@login_required
@require_POST
def edge_revoke(request, edge_id):
    require_cloud()
    edge = get_object_or_404(EdgeNode, id=edge_id)
    edge.status = EdgeStatus.REVOKED
    edge.revoked_at = timezone.now()
    edge.save(update_fields=["status", "revoked_at", "updated_at"])
    deactivated = ClientDevice.objects.filter(edge_id=edge.id, is_active=True).update(
        is_active=False, connection_status=ConnectionStatus.OFFLINE
    )
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="edge.revoked",
        object_type="edge",
        object_id=str(edge.id),
        metadata={"name": edge.name, "deactivated_devices": deactivated},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.warning(request, f"اتصال سرور «{edge.name}» لغو شد و {deactivated} ایستگاه آن غیرفعال شدند.")
    return redirect("cloud_edges")


@login_required
def edge_detail(request, edge_id):
    require_cloud()
    return redirect("cloud_edges")


@login_required
@require_POST
def create_code(request):
    require_cloud()
    import secrets
    from datetime import timedelta

    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    reg = EdgeRegistrationCode.objects.create(
        code=code,
        note=request.POST.get("note", "")[:160],
        created_by=request.user,
        expires_at=timezone.now() + timedelta(hours=24),
    )
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action="edge_code.created",
        object_type="edge_registration_code",
        object_id=str(reg.id),
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"کد ثبت سرور سالن: {reg.code} (۲۴ ساعت اعتبار)")
    return redirect("cloud_edges")


@login_required
@require_POST
def edge_action(request, edge_id):
    require_cloud()
    edge = get_object_or_404(EdgeNode, id=edge_id)
    action = request.POST.get("action", "")
    if action == "unlock":
        messages.error(
            request,
            "امکان باز کردن سیستم بدون مشتری وجود ندارد. برای باز کردن سیستم، لطفاً از فرم «شروع نشست» و انتخاب مشتری دارای اعتبار استفاده نمایید.",
        )
        return safe_redirect_next(request, "cloud_overview")

    if action == "update_edge":
        import json
        from pathlib import Path
        version = "0.2.3"
        url = "/static/updates/server/GameNet-Server-Update-0.2.3.zip"
        sha256 = ""
        manifest_file = Path(settings.BASE_DIR) / "static" / "updates" / "server" / "latest.json"
        if manifest_file.exists():
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                version = data.get("version", version)
                url = data.get("url", url)
                sha256 = data.get("sha256", sha256)
            except Exception:
                pass
        command = issue_command(
            edge,
            "edge.update",
            {"version": version, "url": url, "sha256": sha256},
            actor=request.user,
            ttl_seconds=7 * 24 * 3600,
        )
        AuditLog.objects.create(
            actor=request.user,
            actor_label=request.user.label,
            action="edge.update",
            object_type="edge",
            object_id=str(edge.id),
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, f"دستور به‌روزرسانی خودکار سرور سالن به نسخه {version} ثبت و ارسال شد.")
        return safe_redirect_next(request, "cloud_edges")

    if action == "update_clients":
        import json
        from pathlib import Path
        version = "0.2.3"
        url = "/static/updates/app.asar"
        sha256 = ""
        manifest_file = Path(settings.BASE_DIR) / "static" / "updates" / "latest.json"
        if manifest_file.exists():
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                version = data.get("version", version)
                url = data.get("url", url)
                sha256 = data.get("sha256", sha256)
            except Exception:
                pass
        command = issue_command(
            edge,
            "edge.update_clients",
            {"version": version, "url": url, "sha256": sha256},
            actor=request.user,
            ttl_seconds=7 * 24 * 3600,
        )
        AuditLog.objects.create(
            actor=request.user,
            actor_label=request.user.label,
            action="edge.update_clients",
            object_type="edge",
            object_id=str(edge.id),
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, f"دستور به‌روزرسانی آنلاین کلاینت‌های سالن به نسخه {version} ارسال شد.")
        return safe_redirect_next(request, "cloud_edges")

    mapping = {
        "ping": ("edge.ping", {}),
        "sync": ("edge.sync_now", {}),
        "test_event": ("edge.test_event", {"note": "issued from cloud dashboard"}),
    }
    if action not in mapping:
        return HttpResponseBadRequest("unknown action")
    command_type, payload = mapping[action]
    issue_command(edge, command_type, payload, actor=request.user)
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action=f"edge.{action}",
        object_type="edge",
        object_id=str(edge.id),
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"دستور برای سرور سالن ارسال شد.")
    return safe_redirect_next(request, "cloud_edges")


@login_required
@require_POST
def device_action(request, device_id):
    require_cloud()
    device = get_object_or_404(ClientDevice, id=device_id)
    edge = EdgeNode.objects.filter(id=device.edge_id).first()
    if edge is None:
        messages.error(request, "Edge مربوط به این دستگاه یافت نشد.")
        return redirect("cloud_overview")
    action = request.POST.get("action", "")
    if action == "wake":
        from apps.devices.wol import WolError, normalize_mac

        mac_raw = (device.metadata or {}).get("mac_address") or ""
        try:
            mac = normalize_mac(mac_raw)
        except WolError as exc:
            messages.error(request, str(exc))
            return safe_redirect_next(request, "cloud_device_detail", device_id=device.id)
        if not mac:
            messages.error(
                request,
                f"آدرس MAC برای «{device.name}» ثبت نشده است. از بخش تنظیمات ایستگاه، آدرس MAC کارت شبکه را وارد کنید یا یک‌بار کلاینت را متصل نمایید.",
            )
            return safe_redirect_next(request, "cloud_device_detail", device_id=device.id)
        issue_command(
            edge,
            "device.wake",
            {
                "device_id": str(device.id),
                "mac_address": mac,
                "ip_address": device.ip_address or "",
            },
            actor=request.user,
        )
        AuditLog.objects.create(
            actor=request.user,
            actor_label=request.user.label,
            action="remote.device.wake",
            object_type="device",
            object_id=str(device.id),
            metadata={"edge_id": str(edge.id), "device_name": device.name, "mac_address": mac},
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        if edge.status != EdgeStatus.ONLINE:
            messages.warning(
                request,
                f"سرور سالن در حال حاضر آفلاین است؛ دستور روشن‌سازی {device.name} ({mac}) در صف قرار گرفت و به محض اتصال سرور سالن اجرا می‌شود.",
            )
        else:
            messages.success(
                request,
                f"دستور روشن‌سازی (Wake-on-LAN) برای {device.name} ({mac}) به سرور سالن ارسال شد.",
            )
        return safe_redirect_next(request, "cloud_overview")

    if action == "unlock":
        messages.error(
            request,
            "امکان باز کردن سیستم بدون مشتری وجود ندارد. برای باز کردن سیستم، لطفاً از فرم «شروع نشست» و انتخاب مشتری دارای اعتبار استفاده نمایید.",
        )
        return safe_redirect_next(request, "cloud_overview")

    mapping = {
        "lock": "client.lock",
        "unlock": "client.unlock",
        "ping": "client.ping",
        "restart": "client.restart",
        "restart_app": "client.restart_app",
        "shutdown": "client.shutdown",
        "admin_unlock": "client.admin_unlock",
        "update": "client.update",
        "kill_games": "client.kill_games",
    }
    if action not in mapping:
        return HttpResponseBadRequest("unknown action")

    payload = {"device_id": str(device.id)}
    if action == "lock":
        payload["reason"] = "قفل دستی توسط مدیر از کلود"
        payload["close_games"] = True
        payload["keep_processes"] = False
    elif action == "kill_games":
        payload["reason"] = "بستن تمام بازی‌ها از کلود"
    elif action == "restart_app":
        payload["reason"] = "ریست نرم‌افزار کلاینت از کلود"
        payload["mode"] = "app"
        payload["app_only"] = True
    elif action == "restart":
        payload["reason"] = "ری‌استارت سیستم از کلود"
        payload["mode"] = "system"

    issue_command(edge, mapping[action], payload, actor=request.user)
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action=f"remote.device.{action}",
        object_type="device",
        object_id=str(device.id),
        metadata={"edge_id": str(edge.id), "device_name": device.name},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    labels = {
        "lock": "قفل کلاینت و بستن بازی‌ها",
        "unlock": "باز کردن",
        "ping": "پینگ",
        "restart": "ری‌استارت سیستم (Restart)",
        "restart_app": "ریست نرم‌افزار کلاینت",
        "shutdown": "خاموش کردن (Shutdown)",
        "admin_unlock": "ورود ادمین به دسکتاپ (اکسپلورر)",
        "kill_games": "بستن تمام بازی‌ها",
    }
    label = labels.get(action, action)
    messages.success(request, f"دستور «{label}» از طریق کلود به هاب و دستگاه «{device.name}» ابلاغ شد.")
    return safe_redirect_next(request, "cloud_overview")


@login_required
def commands(request):
    require_cloud()
    return redirect(reverse("cloud_edges") + "#commands")


@login_required
def events(request):
    require_cloud()
    return redirect(reverse("cloud_edges") + "#events")


@login_required
def config(request):
    require_cloud()
    if request.method == "POST":
        import hashlib
        import json

        payload = {
            "device_heartbeat_seconds": int(request.POST.get("device_heartbeat_seconds", 10)),
            "device_offline_after_missed": int(request.POST.get("device_offline_after_missed", 3)),
            "default_hourly_rate": int(request.POST.get("default_hourly_rate", 60000)),
            "default_credit_limit": int(request.POST.get("default_credit_limit", 60000)),
            "command_ttl_seconds": int(request.POST.get("command_ttl_seconds", 120)),
        }
        version = (ConfigSnapshot.objects.order_by("-version").values_list("version", flat=True).first() or 0) + 1
        content_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        ConfigSnapshot.objects.create(
            version=version, payload=payload, content_hash=content_hash, created_by=request.user
        )
        ConfigSnapshot.objects.exclude(version=version).update(is_active=False)
        messages.success(request, f"نسخه پیکربندی v{version} ساخته شد.")
        return redirect(reverse("cloud_edges") + "#config")
    return redirect(reverse("cloud_edges") + "#config")

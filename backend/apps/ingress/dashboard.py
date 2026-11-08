"""Cloud dashboard. Read-only replica view plus remote control."""

from __future__ import annotations

from apps.core.redirects import safe_redirect_next

from datetime import datetime, time, timedelta
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import CommandStatus, RemoteCommand
from apps.core.roles import require_cloud
from apps.customers.models import Customer
from apps.devices.models import RegistrationCode
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.sessions.models import GamingSession, SessionStatus
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


def _counts():
    now = timezone.now()
    return {
        "edges_online": EdgeNode.objects.filter(status=EdgeStatus.ONLINE).count(),
        "edges_total": EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).count(),
        "devices_online": ClientDevice.objects.exclude(
            status__in=[ClientStatus.OFFLINE, ClientStatus.MAINTENANCE]
        ).count(),
        "devices_total": ClientDevice.objects.filter(is_active=True).count(),
        "locked_count": ClientDevice.objects.filter(status=ClientStatus.LOCKED, is_active=True).count(),
        "active_count": GamingSession.objects.filter(status=SessionStatus.ACTIVE).count(),
        "events_total": SyncEvent.objects.count(),
        "events_rejected": SyncEvent.objects.filter(status="REJECTED").count(),
        "commands_pending": RemoteCommand.objects.filter(status=CommandStatus.PENDING).count(),
        "last_sync": EdgeNode.objects.order_by("-last_sync_at").values_list("last_sync_at", flat=True).first(),
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
        ).select_related("customer", "tariff")
    }

    for d in devices:
        d.edge_node = edges.get(d.edge_id)
        d.active_session = active_sessions.get(d.id)
        if d.active_session:
            d.elapsed_seconds = max(0, int((now - d.active_session.started_at).total_seconds()))
            d.current_cost = int((d.elapsed_seconds / 3600) * d.active_session.hourly_rate)
        else:
            d.elapsed_seconds = 0
            d.current_cost = 0

    devices.sort(key=_station_sort_key)
    return devices


@login_required
def overview(request):
    require_cloud()
    now = timezone.now()
    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    month_start = timezone.make_aware(datetime.combine(today.replace(day=1), time.min))

    # Single local salon server
    salon_server = EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).first()

    devices_raw = ClientDevice.objects.filter(is_active=True)
    devices_annotated = _annotate_devices(devices_raw, now)

    total_devices = max(10, len(devices_annotated))
    active_count = sum(1 for d in devices_annotated if d.status == ClientStatus.ACTIVE or d.active_session)
    free_count = max(0, total_devices - active_count)
    locked_count = sum(1 for d in devices_annotated if d.status == ClientStatus.LOCKED and not d.active_session)
    offline_count = sum(1 for d in devices_annotated if d.status == ClientStatus.OFFLINE)

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

    ctx = {
        "salon_server": salon_server,
        "devices": devices_annotated,
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
        "now": now,
    }
    return render(request, "cloud/overview.html", ctx)


@login_required
def device_grid(request):
    require_cloud()
    now = timezone.now()
    qs = ClientDevice.objects.filter(is_active=True).order_by("name")
    devices = _annotate_devices(qs, now)
    return render(request, "cloud/_device_grid.html", {"devices": devices, "now": now})


@login_required
def devices(request):
    require_cloud()
    ctx = _counts()
    edge_id = request.GET.get("edge")
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    qs = ClientDevice.objects.filter(is_active=True)
    if edge_id:
        qs = qs.filter(edge_id=edge_id)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(hostname__icontains=q) | Q(ip_address__icontains=q))
    if status_filter:
        qs = qs.filter(status=status_filter)

    devices_list = _annotate_devices(qs.order_by("name"))
    edges_list = EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).order_by("name")
    customers_list = Customer.objects.filter(is_active=True).order_by("full_name")[:100]

    ctx.update(
        {
            "devices": devices_list,
            "edges": edges_list,
            "selected_edge": edge_id,
            "q": q,
            "status_filter": status_filter,
            "customers": customers_list,
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
        .select_related("customer")
        .first()
    )
    recent_commands = (
        RemoteCommand.objects.filter(edge=edge, payload__device_id=str(device.id)).order_by(
            "-issued_at"
        )[:30]
        if edge
        else []
    )

    customers_list = (
        Customer.objects.filter(edge_id=device.edge_id, is_active=True).order_by("full_name")[:100]
    )

    ctx = _counts()
    ctx.update(
        {
            "device": device,
            "edge": edge,
            "active_session": active_session,
            "commands": recent_commands,
            "customers": customers_list,
        }
    )
    return render(request, "cloud/device_detail.html", ctx)


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
    rate_id = request.POST.get("customer_rate_id") or None

    issue_command(
        edge,
        "session.start",
        {
            "session_id": str(session_id),
            "customer_id": str(customer.id),
            "device_id": str(device.id),
            "customer_rate_id": str(rate_id) if rate_id else None,
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
    salon_server = EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).first()
    devices = (
        ClientDevice.objects.filter(is_active=True).order_by("name")
        if salon_server
        else []
    )
    return render(
        request,
        "cloud/edges.html",
        {
            "salon_server": salon_server,
            "devices": devices,
        },
    )


@login_required
def edge_detail(request, edge_id):
    require_cloud()
    edge = get_object_or_404(EdgeNode, id=edge_id)
    ctx = _counts()
    ctx.update(
        {
            "edge": edge,
            "devices": ClientDevice.objects.filter(edge_id=edge.id).order_by("name"),
            "commands": edge.commands.order_by("-issued_at")[:30],
            "events": edge.events.order_by("-local_sequence")[:30],
        }
    )
    return render(request, "cloud/edge_detail.html", ctx)


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
    mapping = {"lock": "client.lock", "unlock": "client.unlock", "ping": "client.ping", "restart": "client.restart"}
    if action not in mapping:
        return HttpResponseBadRequest("unknown action")
    issue_command(edge, mapping[action], {"device_id": str(device.id)}, actor=request.user)
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action=f"remote.device.{action}",
        object_type="device",
        object_id=str(device.id),
        metadata={"edge_id": str(edge.id), "device_name": device.name},
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"دستور {action} برای {device.name} ارسال شد.")
    return safe_redirect_next(request, "cloud_overview")


@login_required
def commands(request):
    require_cloud()
    ctx = _counts()
    ctx["commands"] = RemoteCommand.objects.select_related("edge", "created_by").order_by("-issued_at")[:100]
    return render(request, "cloud/commands.html", ctx)


@login_required
def events(request):
    require_cloud()
    ctx = _counts()
    ctx["events"] = SyncEvent.objects.select_related("edge").order_by("-local_sequence")[:100]
    return render(request, "cloud/events.html", ctx)


@login_required
def config(request):
    require_cloud()
    ctx = _counts()
    ctx["snapshots"] = ConfigSnapshot.objects.order_by("-version")[:20]
    ctx["active"] = ConfigSnapshot.objects.filter(is_active=True).order_by("-version").first()
    if request.method == "POST":
        import hashlib
        import json

        payload = {
            "device_heartbeat_seconds": int(request.POST.get("device_heartbeat_seconds", 10)),
            "device_offline_after_missed": int(request.POST.get("device_offline_after_missed", 3)),
            "default_hourly_rate": int(request.POST.get("default_hourly_rate", 40000)),
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
        return redirect("cloud_config")
    return render(request, "cloud/config.html", ctx)

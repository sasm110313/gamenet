"""Cloud dashboard. Read-only replica view plus remote control."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import CommandStatus, RemoteCommand
from apps.core.roles import require_cloud
from apps.synchronization.command_service import issue_command
from apps.synchronization.models import (
    ConfigSnapshot,
    EdgeNode,
    EdgeRegistrationCode,
    EdgeStatus,
    SyncEvent,
)

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
        "events_total": SyncEvent.objects.count(),
        "events_rejected": SyncEvent.objects.filter(status="REJECTED").count(),
        "commands_pending": RemoteCommand.objects.filter(status=CommandStatus.PENDING).count(),
        "last_sync": EdgeNode.objects.order_by("-last_sync_at").values_list("last_sync_at", flat=True).first(),
        "now": now,
        "stale_after": now - timedelta(seconds=90),
    }


@login_required
def overview(request):
    require_cloud()
    ctx = _counts()
    ctx.update(
        {
            "edges": EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).order_by("name"),
            "devices": ClientDevice.objects.filter(is_active=True).order_by("name")[:50],
            "commands": RemoteCommand.objects.select_related("edge").order_by("-issued_at")[:8],
            "events": SyncEvent.objects.select_related("edge").order_by("-local_sequence")[:8],
            "config": ConfigSnapshot.objects.filter(is_active=True).order_by("-version").first(),
        }
    )
    return render(request, "cloud/overview.html", ctx)


@login_required
def edges(request):
    require_cloud()
    ctx = _counts()
    ctx.update(
        {
            "edges": EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).order_by("name"),
            "codes": EdgeRegistrationCode.objects.select_related("used_by").order_by("-created_at")[:10],
        }
    )
    return render(request, "cloud/edges.html", ctx)


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
    messages.success(request, f"کد ثبت Edge: {reg.code} (۲۴ ساعت اعتبار)")
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
    if action == "test_event":
        # The cloud command makes the *edge* emit a real outbox event, which then
        # round-trips through ingest — the Phase 0 end-to-end proof.
        issue_command(edge, "edge.test_event", payload, actor=request.user)
        messages.success(request, "دستور ساخت رویداد آزمایشی برای Edge ارسال شد.")
        return redirect("cloud_edge_detail", edge_id=edge.id)

    issue_command(edge, command_type, payload, actor=request.user)
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action=f"edge.{action}",
        object_type="edge",
        object_id=str(edge.id),
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"دستور {command_type} برای {edge.name} ارسال شد.")
    return redirect("cloud_edge_detail", edge_id=edge.id)


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
    return redirect(request.POST.get("next") or "cloud_overview")


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

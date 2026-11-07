"""Edge session floor: start a session and stop it with an exact charge."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus
from apps.core.dashboard import edge_common
from apps.customers.models import Customer
from apps.sessions.models import GamingSession, SessionStatus
from apps.sessions.services import SessionError, start_session, stop_session


def _audit(request, action: str, session: GamingSession, metadata=None) -> None:
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action=action,
        object_type="gaming_session",
        object_id=str(session.id),
        metadata=metadata or {},
        ip_address=request.META.get("REMOTE_ADDR"),
    )


@login_required
def sessions(request):
    ctx = edge_common()
    q = request.GET.get("q", "").strip()
    active = (
        GamingSession.objects.filter(status=SessionStatus.ACTIVE)
        .select_related("customer", "device")
        .order_by("started_at")
    )
    recent = GamingSession.objects.select_related("customer", "device").order_by("-started_at")
    if q:
        recent = recent.filter(
            Q(customer__full_name__icontains=q)
            | Q(device__name__icontains=q)
            | Q(id__icontains=q)
        )
    customers = Customer.objects.filter(is_active=True).select_related("wallet", "group")
    devices = (
        ClientDevice.objects.filter(
            is_active=True,
            status__in=[ClientStatus.ONLINE, ClientStatus.LOCKED, ClientStatus.IDLE],
        )
        .exclude(sessions__status=SessionStatus.ACTIVE)
        .order_by("name")
    )
    ctx.update(
        {
            "active_sessions": active,
            "recent_sessions": recent[:80],
            "customers": customers[:200],
            "devices": devices,
            "q": q,
        }
    )
    return render(request, "edge/sessions.html", ctx)


@login_required
@require_POST
def session_start(request):
    customer = Customer.objects.filter(id=request.POST.get("customer_id")).first()
    device = ClientDevice.objects.filter(id=request.POST.get("device_id")).first()
    if customer is None or device is None:
        messages.error(request, "مشتری یا دستگاه انتخاب‌شده معتبر نیست.")
        return redirect("edge_sessions")
    try:
        session = start_session(customer, device, actor=request.user)
    except SessionError as exc:
        messages.error(request, str(exc))
        return redirect("edge_sessions")
    _audit(
        request, "session.started", session,
        {"customer": customer.full_name, "device": device.name, "rate": session.hourly_rate},
    )
    messages.success(
        request, f"نشست {customer.full_name} روی {device.name} شروع شد."
    )
    return redirect("edge_sessions")


@login_required
@require_POST
def session_stop(request, session_id):
    session = get_object_or_404(GamingSession, id=session_id)
    try:
        session, entry = stop_session(
            session, actor=request.user, reason=request.POST.get("reason", "پایان دستی")
        )
    except SessionError as exc:
        messages.error(request, str(exc))
        return redirect("edge_sessions")
    _audit(
        request, "session.ended", session,
        {"cost": session.cost, "elapsed_seconds": session.elapsed_seconds,
         "ledger_entry": str(entry.id) if entry else None},
    )
    messages.success(
        request,
        f"نشست پایان یافت؛ مدت {session.elapsed_seconds or 0} ثانیه و هزینه {session.cost or 0:,} تومان.",
    )
    return redirect(request.POST.get("next") or "edge_sessions")

"""Edge session floor: start a session and stop it with an exact charge."""

from __future__ import annotations

from apps.core.redirects import safe_redirect_next

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ConnectionStatus, OccupancyStatus
from apps.core.catalog_payload import build_catalog_json
from apps.core.dashboard import edge_common
from apps.customers.models import Customer
from apps.pricing.models import CustomerRate, Tariff
from apps.sessions.models import BillingMode, DisconnectPolicy, GamingSession, SessionStatus
from apps.sessions.services import SessionError, start_session, stop_session
from apps.synchronization.config import current_config


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


def _int_or_none(raw):
    val = str(raw or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")).strip()
    if not val:
        return None
    return int(val.replace(",", "").replace("،", ""))


@login_required
def sessions(request):
    ctx = edge_common()
    q = request.GET.get("q", "").strip()
    active = (
        GamingSession.objects.filter(status=SessionStatus.ACTIVE)
        .select_related("customer", "customer__wallet", "device", "tariff", "customer_rate")
        .order_by("started_at")
    )
    recent = GamingSession.objects.select_related("customer", "device", "tariff", "customer_rate").order_by("-started_at")
    if q:
        recent = recent.filter(
            Q(customer__full_name__icontains=q)
            | Q(device__name__icontains=q)
            | Q(id__icontains=q)
        )
    customers = list(
        Customer.objects.filter(is_active=True)
        .select_related("wallet", "group", "group__tariff")
        .prefetch_related("rates")
        .order_by("full_name")[:200]
    )
    devices = list(
        ClientDevice.objects.filter(
            is_active=True,
            connection_status=ConnectionStatus.ONLINE,
            occupancy_status=OccupancyStatus.FREE,
        )
        .exclude(sessions__status=SessionStatus.ACTIVE)
        .order_by("name")
    )
    tariffs = list(Tariff.objects.filter(is_active=True).order_by("name"))
    rates = (
        CustomerRate.objects.filter(customer__is_active=True, is_active=True)
        .select_related("customer")
        .order_by("customer__full_name", "-is_default", "name")
    )
    default_hourly_rate = int(ctx["config"].get("default_hourly_rate", 60000))
    operator_label = request.user.label or request.user.username
    catalog_json = build_catalog_json(
        customers=customers,
        tariffs=tariffs,
        devices=devices,
        default_hourly_rate=default_hourly_rate,
        operator_label=operator_label,
    )
    ctx.update(
        {
            "active_sessions": active,
            "recent_sessions": recent[:80],
            "customers": customers,
            "devices": devices,
            "tariffs": tariffs,
            "rates": rates,
            "BillingMode": BillingMode,
            "DisconnectPolicy": DisconnectPolicy,
            "default_hourly_rate": default_hourly_rate,
            "operator_label": operator_label,
            "catalog_json": catalog_json,
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
        return safe_redirect_next(request, "edge_sessions")

    if request.POST.get("require_confirm") == "1" and request.POST.get("confirm_start") != "1":
        messages.error(request, "لطفاً تیک تأیید نهایی شروع نشست را فعال کنید.")
        return safe_redirect_next(request, "edge_sessions")

    rate = None
    tariff = None
    rate_choice = (request.POST.get("rate_choice") or "").strip()
    if rate_choice.startswith("rate:"):
        rate_id = rate_choice.split(":", 1)[1].strip()
        rate = CustomerRate.objects.filter(id=rate_id, customer=customer).first()
        if rate is None:
            messages.error(request, "نرخ شخصی انتخاب‌شده معتبر نیست.")
            return safe_redirect_next(request, "edge_sessions")
    elif rate_choice.startswith("tariff:"):
        tariff_id = rate_choice.split(":", 1)[1].strip()
        tariff = Tariff.objects.filter(id=tariff_id, edge_id=customer.edge_id).first()
        if tariff is None:
            messages.error(request, "تعرفه انتخاب‌شده معتبر نیست.")
            return safe_redirect_next(request, "edge_sessions")
    else:
        rate_id = request.POST.get("customer_rate_id", "").strip()
        tariff_id = request.POST.get("tariff_id", "").strip()
        if rate_id:
            rate = CustomerRate.objects.filter(id=rate_id).first()
            if rate is None or rate.customer_id != customer.id:
                messages.error(request, "نرخ انتخاب‌شده معتبر نیست.")
                return safe_redirect_next(request, "edge_sessions")
        elif tariff_id:
            tariff = Tariff.objects.filter(id=tariff_id, edge_id=customer.edge_id).first()
            if tariff is None:
                messages.error(request, "تعرفه انتخاب‌شده معتبر نیست.")
                return safe_redirect_next(request, "edge_sessions")

    billing_mode = (request.POST.get("billing_mode") or BillingMode.CREDIT).strip().upper()
    disconnect_policy = (request.POST.get("disconnect_policy") or DisconnectPolicy.PAUSE).strip().upper()
    try:
        planned_minutes = _int_or_none(request.POST.get("planned_duration_minutes"))
    except ValueError:
        messages.error(request, "مدت زمان انتخاب‌شده نامعتبر است.")
        return safe_redirect_next(request, "edge_sessions")

    try:
        session = start_session(
            customer,
            device,
            customer_rate=rate,
            tariff=tariff,
            billing_mode=billing_mode,
            planned_duration_minutes=planned_minutes,
            disconnect_policy=disconnect_policy,
            actor=request.user,
        )
    except SessionError as exc:
        messages.error(request, str(exc))
        return safe_redirect_next(request, "edge_sessions")
    except Exception as exc:
        logger.exception("Unexpected error in session_start: %s", exc)
        messages.error(request, f"خطای سیستمی در شروع نشست: {exc}")
        return safe_redirect_next(request, "edge_sessions")
    _audit(
        request,
        "session.started",
        session,
        {
            "customer": customer.full_name,
            "device": device.name,
            "rate": session.hourly_rate,
            "rate_name": session.tariff_name,
            "billing_mode": session.billing_mode,
            "planned_duration_minutes": session.planned_duration_minutes,
            "estimated_cost": session.estimated_cost,
            "disconnect_policy": session.disconnect_policy,
        },
    )
    messages.success(
        request,
        f"نشست {customer.full_name} روی {device.name} با نرخ {session.tariff_name} شروع شد.",
    )
    return safe_redirect_next(request, "edge_sessions")


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
    return safe_redirect_next(request, "edge_sessions")

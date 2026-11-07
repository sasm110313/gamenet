"""Cloud remote management: issue signed catalog/session/wallet commands.

The cloud never writes edge-authoritative rows. Every action here becomes a
signed, expiring, exactly-once command; the edge applies it and the resulting
event flows back into the cloud projections.
"""

from __future__ import annotations

from apps.core.redirects import safe_redirect_next

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import RemoteCommand
from apps.core.roles import require_cloud
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.pricing.models import CustomerRate, Tariff
from apps.sessions.models import GamingSession, SessionStatus
from apps.synchronization.command_service import issue_command
from apps.synchronization.models import EdgeNode, EdgeStatus

MANAGEMENT_TTL_SECONDS = 3600


def _int(value, label: str) -> int:
    raw = str(value or "").replace(",", "").replace("،", "").strip()
    if not raw:
        raise ValueError(f"{label} الزامی است.")
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{label} باید عدد صحیح باشد.") from exc


def _request_id(request) -> uuid.UUID | None:
    raw = (request.POST.get("request_id") or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ValueError("شناسه درخواست نامعتبر است.") from exc


def _edge(edge_id) -> EdgeNode | None:
    return (
        EdgeNode.objects.filter(id=edge_id)
        .exclude(status=EdgeStatus.REVOKED)
        .first()
    )


def _audit(request, action: str, command: RemoteCommand) -> None:
    AuditLog.objects.create(
        actor=request.user,
        actor_label=getattr(request.user, "label", ""),
        action=action,
        object_type="remote_command",
        object_id=str(command.id),
        metadata={
            "edge_id": str(command.edge_id),
            "command_type": command.command_type,
            "request_id": str(command.request_id) if command.request_id else None,
        },
        ip_address=request.META.get("REMOTE_ADDR"),
    )


def _issue(
    request,
    edge: EdgeNode,
    command_type: str,
    payload: dict,
    *,
    action: str,
) -> RemoteCommand:
    request_id = _request_id(request)
    if request_id is not None:
        existing = RemoteCommand.objects.filter(edge=edge, request_id=request_id).first()
        if existing is not None:
            messages.info(request, "این درخواست قبلاً ثبت شده است؛ فرمان تکراری ارسال نشد.")
            return existing
    command = issue_command(
        edge,
        command_type,
        payload,
        actor=request.user,
        request_id=request_id,
        ttl_seconds=MANAGEMENT_TTL_SECONDS,
    )
    _audit(request, action, command)
    messages.success(
        request,
        f"فرمان «{command_type}» برای Edge «{edge.name}» ثبت شد؛ "
        "نتیجه پس از اجرا در صفحه دستورها دیده می‌شود.",
    )
    return command


def _base_context() -> dict:
    require_cloud()
    return {
        "edges": EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).order_by("name"),
        "tariffs": Tariff.objects.order_by("edge_id", "name"),
        "groups": CustomerGroup.objects.select_related("tariff").order_by("edge_id", "name"),
        "customers": Customer.objects.select_related("group", "wallet").order_by("full_name"),
    }


def _tariffs_by_edge() -> dict:
    mapping: dict = {edge.id: [] for edge in EdgeNode.objects.all()}
    for tariff in Tariff.objects.order_by("name"):
        mapping.setdefault(tariff.edge_id, []).append(tariff)
    return mapping


def _groups_by_edge() -> dict:
    mapping: dict = {edge.id: [] for edge in EdgeNode.objects.all()}
    for group in CustomerGroup.objects.filter(is_active=True).order_by("name"):
        mapping.setdefault(group.edge_id, []).append(group)
    return mapping


@login_required
def pricing(request):
    ctx = _base_context()
    ctx.update(
        {
            "tariffs_by_edge": _tariffs_by_edge(),
            "groups_by_edge": _groups_by_edge(),
        }
    )
    return render(request, "cloud/manage_pricing.html", ctx)


@login_required
@require_POST
def tariff_create(request):
    require_cloud()
    try:
        edge = _edge(request.POST.get("edge_id"))
        if edge is None:
            raise ValueError("Edge انتخاب‌شده معتبر نیست.")
        _issue(
            request,
            edge,
            "catalog.tariff.upsert",
            {
                "tariff_id": str(uuid.uuid4()),
                "base_revision": 0,
                "name": (request.POST.get("name") or "").strip(),
                "hourly_rate": _int(request.POST.get("hourly_rate"), "نرخ ساعتی"),
            },
            action="remote.tariff.created",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_pricing")


@login_required
@require_POST
def tariff_update(request, tariff_id):
    require_cloud()
    tariff = get_object_or_404(Tariff, id=tariff_id)
    edge = _edge(tariff.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این تعرفه یافت نشد.")
        _issue(
            request,
            edge,
            "catalog.tariff.upsert",
            {
                "tariff_id": str(tariff.id),
                "base_revision": _int(
                    request.POST.get("base_revision", tariff.revision), "نسخه"
                ),
                "name": (request.POST.get("name") or "").strip(),
                "hourly_rate": _int(request.POST.get("hourly_rate"), "نرخ ساعتی"),
                "is_active": request.POST.get("is_active") == "1",
            },
            action="remote.tariff.updated",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_pricing")


@login_required
@require_POST
def group_create(request):
    require_cloud()
    try:
        edge = _edge(request.POST.get("edge_id"))
        if edge is None:
            raise ValueError("Edge انتخاب‌شده معتبر نیست.")
        tariff = Tariff.objects.filter(
            id=request.POST.get("tariff_id"), edge_id=edge.id
        ).first()
        if tariff is None:
            raise ValueError("تعرفه انتخاب‌شده معتبر نیست.")
        _issue(
            request,
            edge,
            "catalog.group.upsert",
            {
                "group_id": str(uuid.uuid4()),
                "base_revision": 0,
                "name": (request.POST.get("name") or "").strip(),
                "tariff_id": str(tariff.id),
                "is_active": True,
            },
            action="remote.group.created",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_pricing")


@login_required
@require_POST
def group_update(request, group_id):
    require_cloud()
    group = get_object_or_404(CustomerGroup, id=group_id)
    edge = _edge(group.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این گروه یافت نشد.")
        tariff_id = request.POST.get("tariff_id")
        tariff = (
            Tariff.objects.filter(id=tariff_id, edge_id=edge.id).first()
            if tariff_id
            else None
        )
        if tariff is None:
            raise ValueError("تعرفه انتخاب‌شده معتبر نیست.")
        _issue(
            request,
            edge,
            "catalog.group.upsert",
            {
                "group_id": str(group.id),
                "base_revision": _int(
                    request.POST.get("base_revision", group.revision), "نسخه"
                ),
                "name": (request.POST.get("name") or "").strip(),
                "tariff_id": str(tariff.id),
                "is_active": request.POST.get("is_active") == "1",
            },
            action="remote.group.updated",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_pricing")


@login_required
def customers(request):
    ctx = _base_context()
    ctx["groups_by_edge"] = _groups_by_edge()
    return render(request, "cloud/manage_customers.html", ctx)


@login_required
@require_POST
def customer_create(request):
    require_cloud()
    try:
        edge = _edge(request.POST.get("edge_id"))
        if edge is None:
            raise ValueError("Edge انتخاب‌شده معتبر نیست.")
        group_id = request.POST.get("group_id")
        group = (
            CustomerGroup.objects.filter(id=group_id, edge_id=edge.id).first()
            if group_id
            else None
        )
        if group_id and group is None:
            raise ValueError("گروه انتخاب‌شده معتبر نیست.")
        _issue(
            request,
            edge,
            "catalog.customer.upsert",
            {
                "customer_id": str(uuid.uuid4()),
                "base_revision": 0,
                "full_name": (request.POST.get("full_name") or "").strip(),
                "phone": (request.POST.get("phone") or "").strip(),
                "group_id": str(group.id) if group else None,
                "credit_limit": _int(request.POST.get("credit_limit"), "سقف اعتبار"),
                "notes": (request.POST.get("notes") or "").strip(),
                "is_active": True,
            },
            action="remote.customer.created",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_customers")


@login_required
def customer_detail(request, customer_id):
    ctx = _base_context()
    customer = get_object_or_404(
        Customer.objects.select_related("group__tariff", "wallet"), id=customer_id
    )
    edges = {edge.id: edge for edge in ctx["edges"]}
    edge = edges.get(customer.edge_id)
    rates = customer.rates.order_by("-is_default", "-is_active", "name")
    devices = (
        ClientDevice.objects.filter(
            edge_id=customer.edge_id,
            is_active=True,
            status__in=[ClientStatus.ONLINE, ClientStatus.LOCKED, ClientStatus.IDLE],
        )
        .exclude(sessions__status=SessionStatus.ACTIVE)
        .order_by("name")
    )
    commands = (
        RemoteCommand.objects.filter(
            edge_id=customer.edge_id, payload__customer_id=str(customer.id)
        )
        .select_related("edge")
        .order_by("-issued_at")[:20]
    )
    ctx.update(
        {
            "customer": customer,
            "edge": edge,
            "rates": rates,
            "active_rates": rates.filter(is_active=True),
            "devices": devices,
            "groups": _groups_by_edge().get(customer.edge_id, []),
            "active_sessions": customer.sessions.filter(
                status=SessionStatus.ACTIVE
            ).select_related("device"),
            "commands": commands,
        }
    )
    return render(request, "cloud/manage_customer.html", ctx)


@login_required
@require_POST
def customer_update(request, customer_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    edge = _edge(customer.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این مشتری یافت نشد.")
        group_id = request.POST.get("group_id")
        group = (
            CustomerGroup.objects.filter(id=group_id, edge_id=edge.id).first()
            if group_id
            else None
        )
        if group_id and group is None:
            raise ValueError("گروه انتخاب‌شده معتبر نیست.")
        _issue(
            request,
            edge,
            "catalog.customer.upsert",
            {
                "customer_id": str(customer.id),
                "base_revision": _int(
                    request.POST.get("base_revision", customer.revision), "نسخه"
                ),
                "full_name": (request.POST.get("full_name") or "").strip(),
                "phone": (request.POST.get("phone") or "").strip(),
                "group_id": str(group.id) if group else None,
                "credit_limit": _int(request.POST.get("credit_limit"), "سقف اعتبار"),
                "notes": (request.POST.get("notes") or "").strip(),
                "is_active": request.POST.get("is_active") == "1",
            },
            action="remote.customer.updated",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_customer", customer_id=customer.id)


@login_required
@require_POST
def customer_rate_create(request, customer_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    edge = _edge(customer.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این مشتری یافت نشد.")
        _issue(
            request,
            edge,
            "catalog.customer_rate.upsert",
            {
                "customer_rate_id": str(uuid.uuid4()),
                "customer_id": str(customer.id),
                "base_revision": 0,
                "name": (request.POST.get("name") or "").strip(),
                "hourly_rate": _int(request.POST.get("hourly_rate"), "نرخ ساعتی"),
                "is_default": request.POST.get("is_default") == "1",
                "is_active": True,
            },
            action="remote.customer_rate.created",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_customer", customer_id=customer.id)


@login_required
@require_POST
def customer_rate_update(request, customer_id, rate_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    rate = get_object_or_404(CustomerRate, id=rate_id, customer=customer)
    edge = _edge(customer.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این مشتری یافت نشد.")
        _issue(
            request,
            edge,
            "catalog.customer_rate.upsert",
            {
                "customer_rate_id": str(rate.id),
                "customer_id": str(customer.id),
                "base_revision": _int(
                    request.POST.get("base_revision", rate.revision), "نسخه"
                ),
                "name": (request.POST.get("name") or "").strip(),
                "hourly_rate": _int(request.POST.get("hourly_rate"), "نرخ ساعتی"),
                "is_default": request.POST.get("is_default") == "1",
                "is_active": request.POST.get("is_active") == "1",
            },
            action="remote.customer_rate.updated",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_customer", customer_id=customer.id)


@login_required
@require_POST
def customer_rate_deactivate(request, customer_id, rate_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    rate = get_object_or_404(CustomerRate, id=rate_id, customer=customer)
    edge = _edge(customer.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این مشتری یافت نشد.")
        _issue(
            request,
            edge,
            "catalog.customer_rate.deactivate",
            {
                "customer_rate_id": str(rate.id),
                "base_revision": _int(
                    request.POST.get("base_revision", rate.revision), "نسخه"
                ),
            },
            action="remote.customer_rate.deactivated",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_customer", customer_id=customer.id)


@login_required
@require_POST
def wallet(request, customer_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    edge = _edge(customer.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این مشتری یافت نشد.")
        action = request.POST.get("action")
        if action not in {"deposit", "adjust"}:
            raise ValueError("نوع عملیات کیف پول نامعتبر است.")
        amount = _int(request.POST.get("amount"), "مبلغ")
        if action == "deposit" and amount <= 0:
            raise ValueError("مبلغ شارژ باید بزرگ‌تر از صفر باشد.")
        if action == "adjust" and amount == 0:
            raise ValueError("مبلغ اصلاح نمی‌تواند صفر باشد.")
        reason = (request.POST.get("reason") or "").strip()
        if not reason:
            raise ValueError("دلیل عملیات الزامی است.")
        _issue(
            request,
            edge,
            "wallet.deposit" if action == "deposit" else "wallet.adjust",
            {
                "customer_id": str(customer.id),
                "amount": amount,
                "reason": reason,
                "requested_by": getattr(request.user, "label", "")
                or request.user.get_username(),
            },
            action=f"remote.wallet.{action}",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_customer", customer_id=customer.id)


@login_required
@require_POST
def session_start(request, customer_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    edge = _edge(customer.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این مشتری یافت نشد.")
        session_id = request.POST.get("session_id")
        try:
            session_id = str(uuid.UUID(session_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("شناسه نشست نامعتبر است.") from exc
        device = ClientDevice.objects.filter(
            id=request.POST.get("device_id"), edge_id=customer.edge_id, is_active=True
        ).first()
        if device is None:
            raise ValueError("دستگاه انتخاب‌شده معتبر نیست.")
        rate_id = request.POST.get("customer_rate_id")
        rate = (
            CustomerRate.objects.filter(
                id=rate_id, customer=customer, is_active=True
            ).first()
            if rate_id
            else None
        )
        if rate_id and rate is None:
            raise ValueError("نرخ انتخاب‌شده معتبر نیست.")
        _issue(
            request,
            edge,
            "session.start",
            {
                "session_id": session_id,
                "customer_id": str(customer.id),
                "device_id": str(device.id),
                "customer_rate_id": str(rate.id) if rate else None,
            },
            action="remote.session.started",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("cloud_manage_customer", customer_id=customer.id)


@login_required
@require_POST
def session_stop(request, session_id):
    require_cloud()
    session = get_object_or_404(GamingSession, id=session_id)
    edge = _edge(session.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این نشست یافت نشد.")
        _issue(
            request,
            edge,
            "session.stop",
            {
                "session_id": str(session.id),
                "reason": (request.POST.get("reason") or "پایان از ابر").strip()[:120],
            },
            action="remote.session.stopped",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return safe_redirect_next(request, "cloud_sessions")

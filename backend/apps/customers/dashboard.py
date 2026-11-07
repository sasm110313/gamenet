"""Edge customer counter: search, registration, wallet operations."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus
from apps.core.dashboard import edge_common
from apps.customers.models import Customer
from apps.customers.services import CustomerError, create_customer, update_customer
from apps.customer_groups.models import CustomerGroup
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.sessions.models import GamingSession, SessionStatus
from apps.wallets.models import Wallet
from apps.wallets.services import WalletError, adjust, deposit, reverse_entry


def _int(value, *, default=None) -> int:
    value = (value or "").strip()
    if not value:
        if default is not None:
            return default
        raise ValueError("عدد الزامی است")
    return int(value.replace(",", "").replace("،", ""))


def _audit(request, action: str, obj_type: str, obj_id, metadata=None) -> None:
    AuditLog.objects.create(
        actor=request.user,
        actor_label=request.user.label,
        action=action,
        object_type=obj_type,
        object_id=str(obj_id),
        metadata=metadata or {},
        ip_address=request.META.get("REMOTE_ADDR"),
    )


@login_required
def customers(request):
    ctx = edge_common()
    q = request.GET.get("q", "").strip()
    qs = Customer.objects.select_related("group", "wallet").order_by("full_name")
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(id__icontains=q)
        )
    ctx.update(
        {
            "customers": qs[:200],
            "groups": CustomerGroup.objects.filter(is_active=True).select_related("tariff"),
            "q": q,
            "default_credit_limit": ctx["config"].get("default_credit_limit"),
        }
    )
    return render(request, "edge/customers.html", ctx)


@login_required
@require_POST
def customer_create(request):
    group = None
    group_id = request.POST.get("group_id")
    if group_id:
        group = CustomerGroup.objects.filter(id=group_id).first()
        if group is None:
            messages.error(request, "گروه انتخاب‌شده معتبر نیست.")
            return redirect("edge_customers")
    try:
        credit_limit = _int(
            request.POST.get("credit_limit"),
            default=int(edge_common()["config"].get("default_credit_limit", 60_000)),
        )
        customer = create_customer(
            full_name=request.POST.get("full_name", ""),
            phone=request.POST.get("phone", ""),
            group=group,
            credit_limit=credit_limit,
            notes=request.POST.get("notes", ""),
            actor=request.user,
        )
    except (CustomerError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_customers")

    _audit(request, "customer.created", "customer", customer.id, {"name": customer.full_name})
    messages.success(request, f"مشتری {customer.full_name} ثبت شد.")
    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
def customer_detail(request, customer_id):
    ctx = edge_common()
    customer = get_object_or_404(
        Customer.objects.select_related("group__tariff", "wallet"), id=customer_id
    )
    wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})
    entries = customer.ledger_entries.select_related("session").order_by("-created_at")[:60]
    sessions_qs = customer.sessions.select_related("device").order_by("-started_at")
    active = sessions_qs.filter(status=SessionStatus.ACTIVE).first()
    sessions = sessions_qs[:20]
    devices = ClientDevice.objects.filter(
        is_active=True, status__in=[ClientStatus.ONLINE, ClientStatus.LOCKED, ClientStatus.IDLE]
    ).exclude(sessions__status=SessionStatus.ACTIVE).order_by("name")
    ctx.update(
        {
            "customer": customer,
            "wallet": wallet,
            "available": wallet.balance + customer.credit_limit,
            "entries": entries,
            "sessions": sessions,
            "active_session": active,
            "devices": devices,
            "groups": CustomerGroup.objects.filter(
                Q(is_active=True) | Q(id=customer.group_id)
            ).select_related("tariff"),
        }
    )
    return render(request, "edge/customer_detail.html", ctx)


@login_required
@require_POST
def customer_update(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    group = None
    group_id = request.POST.get("group_id")
    if group_id:
        group = CustomerGroup.objects.filter(id=group_id).first()
        if group is None:
            messages.error(request, "گروه انتخاب‌شده معتبر نیست.")
            return redirect("edge_customer_detail", customer_id=customer_id)
    try:
        credit_limit = _int(request.POST.get("credit_limit"))
        update_customer(
            customer,
            full_name=request.POST.get("full_name", ""),
            phone=request.POST.get("phone", ""),
            group=group,
            clear_group=not bool(group),
            credit_limit=credit_limit,
            notes=request.POST.get("notes", ""),
            actor=request.user,
        )
    except (CustomerError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(request, "customer.updated", "customer", customer.id)
    messages.success(request, "اطلاعات مشتری ذخیره شد.")
    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_toggle(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        customer = update_customer(
            customer, is_active=not customer.is_active, actor=request.user
        )
    except CustomerError as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(request, "customer.toggled", "customer", customer.id, {"active": customer.is_active})
    messages.warning(
        request, f"وضعیت مشتری {customer.full_name} به {'فعال' if customer.is_active else 'غیرفعال'} تغییر کرد."
    )
    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_deposit(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        entry = deposit(
            customer,
            _int(request.POST.get("amount")),
            actor=request.user,
            note=request.POST.get("note", "")[:255],
        )
    except (WalletError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(request, "wallet.deposit", "ledger_entry", entry.id, {"amount": entry.amount})
    messages.success(request, f"{entry.amount:,} تومان به کیف پول شارژ شد.")
    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_adjust(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        entry = adjust(
            customer,
            _int(request.POST.get("amount")),
            actor=request.user,
            note=request.POST.get("note", "")[:255],
        )
    except (WalletError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(request, "wallet.adjust", "ledger_entry", entry.id, {"amount": entry.amount})
    messages.success(request, f"اصلاح {entry.amount:,} تومان ثبت شد.")
    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_reverse(request, customer_id, entry_id):
    customer = get_object_or_404(Customer, id=customer_id)
    entry = get_object_or_404(LedgerEntry, id=entry_id, customer=customer)
    if entry.entry_type == LedgerEntryType.REVERSAL:
        return HttpResponseBadRequest("a reversal cannot be reversed")
    try:
        reversal = reverse_entry(entry, actor=request.user, note=request.POST.get("note", ""))
    except WalletError as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(
        request, "wallet.reversal", "ledger_entry", reversal.id,
        {"reverses": str(entry.id), "amount": reversal.amount},
    )
    messages.warning(request, "تراکنش با یک ردیف اصلاحی برگشت داده شد.")
    return redirect("edge_customer_detail", customer_id=customer.id)

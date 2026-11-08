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
from apps.pricing.models import CustomerRate
from apps.pricing.services import (
    CustomerRateError,
    create_customer_rate,
    deactivate_customer_rate,
    set_default_customer_rate,
    update_customer_rate,
)
from apps.sessions.models import GamingSession, SessionStatus
from apps.sessions.services import SessionError, resolve_rate
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
def customer_create(request):
    if request.method == "POST":
        group = None
        group_id = request.POST.get("group_id")
        if group_id:
            group = CustomerGroup.objects.filter(id=group_id).first()
            if group is None:
                messages.error(request, "گروه انتخاب‌شده معتبر نیست.")
                return redirect("edge_customer_create")
        try:
            credit_limit = _int(
                request.POST.get("credit_limit"),
                default=int(edge_common()["config"].get("default_credit_limit", 60_000)),
            )
            initial_deposit = _int(request.POST.get("initial_deposit", 0), default=0)
            full_name = request.POST.get("full_name", "").strip()
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "").strip()
            phone = request.POST.get("phone", "").strip()
            notes = request.POST.get("notes", "").strip()

            if not full_name:
                raise CustomerError("وارد کردن نام و نام خانوادگی الزامی است.")

            customer = create_customer(
                full_name=full_name,
                username=username,
                password=password,
                phone=phone,
                group=group,
                credit_limit=credit_limit,
                notes=notes,
                actor=request.user,
            )
            if initial_deposit > 0:
                from apps.ledger.services import deposit_manual
                deposit_manual(
                    customer=customer,
                    amount=initial_deposit,
                    note="شارژ اولیه هنگام ثبت نام",
                    actor=request.user,
                )
        except (CustomerError, ValueError) as exc:
            messages.error(request, str(exc))
            return redirect("edge_customer_create")

        _audit(request, "customer.created", "customer", customer.id, {"name": customer.full_name})
        messages.success(request, f"مشتری {customer.full_name} با موفقیت ثبت شد.")
        return redirect("edge_customer_detail", customer_id=customer.id)

    # GET
    ctx = edge_common()
    ctx.update({
        "groups": CustomerGroup.objects.filter(is_active=True).order_by("name"),
    })
    return render(request, "edge/customer_create.html", ctx)


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
    rates = customer.rates.order_by("-is_default", "-is_active", "name")
    edit_rate = None
    edit_id = request.GET.get("edit", "").strip()
    if edit_id:
        edit_rate = rates.filter(id=edit_id).first()
    try:
        _, _, effective_hourly_rate, effective_rate_name = resolve_rate(customer)
    except SessionError:
        effective_hourly_rate, effective_rate_name = None, "نرخ نامعتبر"
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
            "rates": rates,
            "active_rates": rates.filter(is_active=True),
            "edit_rate": edit_rate,
            "effective_hourly_rate": effective_hourly_rate,
            "effective_rate_name": effective_rate_name,
        }
    )
    return render(request, "edge/customer_detail.html", ctx)


@login_required
@require_POST
def customer_rate_create(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        rate = create_customer_rate(
            customer=customer,
            name=request.POST.get("name", ""),
            hourly_rate=_int(request.POST.get("hourly_rate")),
            is_default=request.POST.get("is_default") == "1",
            actor=request.user,
        )
    except (CustomerRateError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(
        request, "customer_rate.created", "customer_rate", rate.id,
        {"customer": customer.full_name, "name": rate.name, "rate": rate.hourly_rate},
    )
    messages.success(request, f"نرخ «{rate.name}» ثبت شد.")
    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_rate_update(request, customer_id, rate_id):
    customer = get_object_or_404(Customer, id=customer_id)
    rate = get_object_or_404(CustomerRate, id=rate_id, customer=customer)
    try:
        expected = _int(request.POST.get("expected_revision"))
        rate = update_customer_rate(
            rate,
            name=request.POST.get("name", ""),
            hourly_rate=_int(request.POST.get("hourly_rate")),
            is_active=request.POST.get("is_active") == "1",
            is_default=request.POST.get("is_default") == "1",
            expected_revision=expected,
            actor=request.user,
        )
    except (CustomerRateError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(
        request, "customer_rate.updated", "customer_rate", rate.id,
        {"customer": customer.full_name, "name": rate.name, "rate": rate.hourly_rate,
         "active": rate.is_active, "default": rate.is_default},
    )
    messages.success(request, f"نرخ «{rate.name}» به‌روزرسانی شد؛ نشست‌های فعال تغییر نمی‌کنند.")
    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_rate_default(request, customer_id, rate_id):
    customer = get_object_or_404(Customer, id=customer_id)
    rate = get_object_or_404(CustomerRate, id=rate_id, customer=customer)
    try:
        rate = set_default_customer_rate(rate, actor=request.user)
    except CustomerRateError as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(
        request, "customer_rate.default", "customer_rate", rate.id,
        {"customer": customer.full_name, "name": rate.name},
    )
    messages.success(request, f"نرخ «{rate.name}» پیش‌فرض این مشتری شد.")
    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_rate_deactivate(request, customer_id, rate_id):
    customer = get_object_or_404(Customer, id=customer_id)
    rate = get_object_or_404(CustomerRate, id=rate_id, customer=customer)
    try:
        expected = _int(request.POST.get("expected_revision"))
        rate = deactivate_customer_rate(rate, expected_revision=expected, actor=request.user)
    except (CustomerRateError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("edge_customer_detail", customer_id=customer.id)
    _audit(
        request, "customer_rate.deactivated", "customer_rate", rate.id,
        {"customer": customer.full_name, "name": rate.name},
    )
    messages.warning(request, f"نرخ «{rate.name}» غیرفعال شد.")
    return redirect("edge_customer_detail", customer_id=customer.id)


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
        expected = request.POST.get("expected_revision")
        update_customer(
            customer,
            full_name=request.POST.get("full_name", ""),
            username=request.POST.get("username", ""),
            password=request.POST.get("password", "") or None,
            phone=request.POST.get("phone", ""),
            group=group,
            clear_group=not bool(group),
            credit_limit=credit_limit,
            notes=request.POST.get("notes", ""),
            expected_revision=_int(expected) if expected else None,
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
            customer, is_active=not customer.is_active,
            expected_revision=customer.revision, actor=request.user,
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

"""Cloud read-only views of edge-authoritative customers, wallets and sessions."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render

from apps.core.roles import require_cloud
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.pricing.models import Tariff
from apps.sessions.models import GamingSession, SessionStatus
from apps.wallets.models import Wallet


def _base() -> dict:
    require_cloud()
    return {
        "customers_total": Customer.objects.filter(is_active=True).count(),
        "wallet_total": Wallet.objects.aggregate(total=Sum("balance"))["total"] or 0,
        "debt_total": Wallet.objects.filter(balance__lt=0).aggregate(total=Sum("balance"))["total"] or 0,
        "sessions_active": GamingSession.objects.filter(status=SessionStatus.ACTIVE).count(),
        "ledger_total": LedgerEntry.objects.count(),
    }


@login_required
def customers(request):
    ctx = _base()
    q = request.GET.get("q", "").strip()
    qs = Customer.objects.select_related("group", "wallet").order_by("full_name")
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(id__icontains=q)
        )
    ctx.update({"customers": qs[:300], "q": q})
    return render(request, "cloud/customers.html", ctx)


@login_required
def customer_detail(request, customer_id):
    ctx = _base()
    customer = get_object_or_404(
        Customer.objects.select_related("group__tariff", "wallet"), id=customer_id
    )
    active_sessions = customer.sessions.filter(status=SessionStatus.ACTIVE).select_related("device")

    rahro_status = None
    try:
        import requests
        from django.conf import settings
        rahro_url = getattr(settings, "RAHRO_API_URL", "http://127.0.0.1:8000/rahro/api/gamenet/")
        shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
        r = requests.get(
            f"{rahro_url.rstrip('/')}/status/",
            params={"phone": customer.phone, "username": customer.username},
            headers={"X-Internal-Secret": shared_secret},
            timeout=1.5,
        )
        if r.status_code == 200:
            rahro_status = r.json()
    except Exception:
        pass

    ctx.update(
        {
            "customer": customer,
            "active_sessions": active_sessions,
            "rahro_status": rahro_status,
            "entries": customer.ledger_entries.select_related("session").order_by("-created_at")[:100],
            "sessions": customer.sessions.select_related("device").order_by("-started_at")[:30],
        }
    )
    return render(request, "cloud/customer_detail.html", ctx)


@login_required
def sessions(request):
    ctx = _base()
    status = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()
    qs = GamingSession.objects.select_related("customer", "device").order_by("-started_at")
    if status in SessionStatus.values:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(customer__full_name__icontains=q)
            | Q(device__name__icontains=q)
            | Q(id__icontains=q)
        )
    ctx.update(
        {
            "sessions": qs[:300],
            "status": status,
            "statuses": SessionStatus,
            "q": q,
        }
    )
    return render(request, "cloud/sessions.html", ctx)


@login_required
def ledger(request):
    ctx = _base()
    q = request.GET.get("q", "").strip()
    entry_type = request.GET.get("type", "").strip()
    qs = LedgerEntry.objects.select_related("customer", "session", "reverses").order_by("-created_at")
    if q:
        qs = qs.filter(
            Q(customer__full_name__icontains=q)
            | Q(customer__phone__icontains=q)
            | Q(id__icontains=q)
        )
    if entry_type in LedgerEntryType.values:
        qs = qs.filter(entry_type=entry_type)
    ctx.update(
        {
            "entries": qs[:400],
            "q": q,
            "entry_type": entry_type,
            "types": LedgerEntryType,
            "filtered_total": qs.aggregate(total=Sum("amount"))["total"] or 0,
        }
    )
    return render(request, "cloud/ledger.html", ctx)


@login_required
def pricing(request):
    ctx = _base()
    ctx.update(
        {
            "tariffs": Tariff.objects.order_by("edge_id", "name"),
            "groups": CustomerGroup.objects.select_related("tariff").order_by("edge_id", "name"),
        }
    )
    return render(request, "cloud/pricing.html", ctx)

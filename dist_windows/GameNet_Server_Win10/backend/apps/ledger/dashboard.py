"""Edge ledger browser. Read-only: corrections happen from the customer page."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import render

from apps.core.dashboard import edge_common
from apps.ledger.models import LedgerEntry, LedgerEntryType


@login_required
def ledger(request):
    ctx = edge_common()
    q = request.GET.get("q", "").strip()
    entry_type = request.GET.get("type", "").strip()
    qs = LedgerEntry.objects.select_related("customer", "session", "reverses").order_by("-created_at")
    if q:
        qs = qs.filter(
            Q(customer__full_name__icontains=q)
            | Q(customer__phone__icontains=q)
            | Q(tracking_code__icontains=q)
            | Q(operator_label__icontains=q)
            | Q(note__icontains=q)
            | Q(id__icontains=q)
        )
    if entry_type in LedgerEntryType.values:
        qs = qs.filter(entry_type=entry_type)
    page_obj = Paginator(qs, 100).get_page(request.GET.get("page"))
    ctx.update(
        {
            "entries": page_obj,
            "page_obj": page_obj,
            "q": q,
            "entry_type": entry_type,
            "types": LedgerEntryType,
            "total": qs.aggregate(total=Sum("amount"))["total"] or 0,
        }
    )
    return render(request, "edge/ledger.html", ctx)

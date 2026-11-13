"""Cloud remote management: issue signed catalog/session/wallet commands.

The cloud never writes edge-authoritative rows. Every action here becomes a
signed, expiring, exactly-once command; the edge applies it and the resulting
event flows back into the cloud projections.
"""

from __future__ import annotations

from apps.core.redirects import safe_redirect_next

import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus, ConnectionStatus, OccupancyStatus
from apps.commands.models import RemoteCommand
from apps.core.catalog_payload import build_catalog_json
from apps.core.ids import parse_uuid
from apps.core.roles import require_cloud
from apps.customer_groups.models import CustomerGroup
from apps.customers.models import Customer
from apps.ledger.models import LedgerEntry, LedgerEntryType, generate_tracking_code
from apps.pricing.models import CustomerRate, Tariff
from apps.sessions.models import BillingMode, DisconnectPolicy, GamingSession, SessionStatus
from apps.synchronization.command_service import issue_command
from apps.synchronization.models import ConfigSnapshot, EdgeNode, EdgeStatus
from apps.wallets.models import Wallet

MANAGEMENT_TTL_SECONDS = 3600


def _operator_label(user) -> str:
    return (
        getattr(user, "label", "")
        or user.get_full_name()
        or user.get_username()
        or "اپراتور"
    )[:120]


def _cloud_default_hourly_rate() -> int:
    snap = ConfigSnapshot.objects.filter(is_active=True).order_by("-version").first()
    if snap and isinstance(snap.payload, dict):
        return int(snap.payload.get("default_hourly_rate", 60000) or 60000)
    return 60000


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


def _edge(edge_id=None) -> EdgeNode | None:
    if edge_id:
        node = (
            EdgeNode.objects.filter(id=edge_id)
            .exclude(status=EdgeStatus.REVOKED)
            .first()
        )
        if node:
            return node
    return EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).first()


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
    tariffs_qs = list(ctx["tariffs"])
    groups_qs = list(ctx["groups"])
    ctx.update(
        {
            "tariffs_by_edge": _tariffs_by_edge(),
            "groups_by_edge": _groups_by_edge(),
            "active_tariffs_count": sum(1 for t in tariffs_qs if t.is_active),
            "active_groups_count": sum(1 for g in groups_qs if g.is_active),
        }
    )
    return render(request, "cloud/pricing.html", ctx)


@login_required
def pricing_redirect(request):
    require_cloud()
    return redirect("cloud_pricing")


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
    return redirect(reverse("cloud_pricing") + "#tariffs")


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
    return redirect(reverse("cloud_pricing") + "#tariffs")


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
    return redirect(reverse("cloud_pricing") + "#groups")


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
    return redirect(reverse("cloud_pricing") + "#groups")


@login_required
def customers(request):
    require_cloud()
    q = (request.GET.get("q") or "").strip()
    qs = Customer.objects.select_related("group__tariff", "wallet").order_by("full_name")
    if q:
        qs = qs.filter(
            Q(full_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(username__icontains=q)
            | Q(id__icontains=q)
        )
    edges = EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).order_by("name")
    salon_server = (
        EdgeNode.objects.exclude(status=EdgeStatus.REVOKED)
        .order_by("-last_heartbeat_at")
        .first()
    )
    groups = CustomerGroup.objects.filter(is_active=True).select_related("tariff").order_by("name")
    return render(
        request,
        "cloud/customers.html",
        {
            "customers": qs[:300],
            "q": q,
            "edges": edges,
            "salon_server": salon_server,
            "groups": groups,
            "groups_by_edge": _groups_by_edge(),
            "customers_total": Customer.objects.filter(is_active=True).count(),
            "wallet_total": Wallet.objects.aggregate(total=Sum("balance"))["total"] or 0,
            "debt_total": Wallet.objects.filter(balance__lt=0).aggregate(total=Sum("balance"))["total"] or 0,
            "sessions_active": GamingSession.objects.filter(status=SessionStatus.ACTIVE).count(),
        },
    )


@login_required
def customers_redirect(request):
    require_cloud()
    return redirect("cloud_customers")


@login_required
def customer_create(request):
    require_cloud()
    salon_server = _edge(request.POST.get("edge_id") if request.method == "POST" else None)

    if request.method == "POST":
        try:
            if salon_server is None:
                raise ValueError("سرور سالن در دسترس نیست.")
            group_id = request.POST.get("group_id")
            group = (
                CustomerGroup.objects.filter(id=group_id, edge_id=salon_server.id).first()
                if group_id
                else None
            )
            if group_id and group is None:
                raise ValueError("گروه انتخاب‌شده معتبر نیست.")

            customer_id = str(uuid.uuid4())
            full_name = (request.POST.get("full_name") or "").strip()
            username = (request.POST.get("username") or "").strip()
            password = (request.POST.get("password") or "").strip()
            phone = (request.POST.get("phone") or "").strip()
            credit_limit = _int(request.POST.get("credit_limit", 60000), "سقف اعتبار")
            initial_deposit = _int(request.POST.get("initial_deposit", 0), "شارژ اولیه")
            notes = (request.POST.get("notes") or "").strip()

            # نرمال‌سازی ارقام فارسی/عربی
            persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
            english = "01234567890123456789"
            phone = (request.POST.get("phone") or "").translate(str.maketrans(persian_arabic, english)).strip()
            if not phone:
                raise ValueError("شماره موبایل الزامی است.")
            if len(phone) < 10 or len(phone) > 24:
                raise ValueError("شماره موبایل باید حداقل ۱۰ رقم باشد.")

            password = (request.POST.get("password") or "").strip()
            if not password:
                password = phone

            if username:
                username = username.translate(str.maketrans(persian_arabic, english)).strip()
                if not username.isdigit() or len(username) < 4 or len(username) > 6:
                    raise ValueError("کد ۴ تا ۶ رقمی ورود کلاینت باید یک عدد بین ۴ تا ۶ رقم باشد (یا خالی بگذارید).")
                dup = Customer.objects.filter(username=username).first()
                if dup:
                    raise ValueError(f"کد عددی «{username}» قبلاً برای «{dup.full_name}» ثبت شده است.")

            if not full_name:
                raise ValueError("وارد کردن نام و نام خانوادگی الزامی است.")

            _issue(
                request,
                salon_server,
                "catalog.customer.upsert",
                {
                    "customer_id": customer_id,
                    "base_revision": 0,
                    "full_name": full_name,
                    "username": username,
                    "password": password,
                    "phone": phone,
                    "group_id": str(group.id) if group else None,
                    "credit_limit": credit_limit,
                    "notes": notes,
                    "is_active": True,
                },
                action="remote.customer.created",
            )

            # Instant cloud replica projection so admin immediately sees it
            from apps.wallets.models import Wallet
            from apps.ledger.models import LedgerEntry, LedgerEntryType

            cloud_cust, _ = Customer.objects.update_or_create(
                id=customer_id,
                defaults={
                    "edge_id": salon_server.id,
                    "full_name": full_name,
                    "username": username,
                    "phone": phone,
                    "group": group,
                    "credit_limit": credit_limit,
                    "notes": notes,
                    "is_active": True,
                    "is_replica": True,
                },
            )
            if password:
                cloud_cust.set_password(password)
                cloud_cust.save(update_fields=["password_hash"])
            wallet, _ = Wallet.objects.get_or_create(customer=cloud_cust, defaults={"balance": 0})

            # اگر این کاربر در رهرو هم عضو باشد، کد ۴ تا ۶ رقمی در رهرو هم هماهنگ می‌شود
            if username:
                try:
                    import requests
                    from django.conf import settings
                    rahro_url = getattr(settings, "RAHRO_API_URL", "http://127.0.0.1:8000/rahro/api/gamenet/")
                    shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
                    requests.post(
                        f"{rahro_url.rstrip('/')}/set-login-code/",
                        json={"phone": phone, "username": username, "login_code": username},
                        headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
                        timeout=1.5,
                    )
                except Exception:
                    pass

            if initial_deposit > 0:
                init_entry_id = str(uuid.uuid4())
                init_tracking_code = generate_tracking_code()
                op_label = _operator_label(request.user)
                init_cmd = _issue(
                    request,
                    salon_server,
                    "wallet.deposit",
                    {
                        "customer_id": customer_id,
                        "amount": initial_deposit,
                        "reason": "شارژ اولیه هنگام ثبت نام",
                        "requested_by": op_label,
                        "entry_id": init_entry_id,
                        "tracking_code": init_tracking_code,
                        "operator_label": op_label,
                    },
                    action="remote.customer.initial_deposit",
                )
                if not LedgerEntry.objects.filter(source_command_id=init_cmd.id).exists():
                    wallet.balance += initial_deposit
                    wallet.save(update_fields=["balance"])
                    LedgerEntry.objects.create(
                        id=init_entry_id,
                        customer=cloud_cust,
                        edge_id=salon_server.id,
                        entry_type=LedgerEntryType.DEPOSIT,
                        amount=initial_deposit,
                        balance_after=wallet.balance,
                        note="شارژ اولیه هنگام ثبت نام",
                        tracking_code=init_tracking_code,
                        operator_label=op_label,
                        source_command_id=init_cmd.id,
                        created_by=request.user,
                        is_replica=True,
                    )

            messages.success(request, f"مشتری «{full_name}» با موفقیت ثبت شد.")
            return redirect("cloud_customer_detail", customer_id=cloud_cust.id)
        except (ValueError, IntegrityError) as exc:
            if "customers_unique_phone_per_edge" in str(exc) or "phone" in str(exc):
                messages.error(request, "مشتری دیگری با این شماره تماس از قبل ثبت شده است.")
            else:
                messages.error(request, str(exc))
            return redirect(reverse("cloud_customers") + "#create")

    # GET request: redirect cleanly into the unified tabbed Customers workspace
    return redirect(reverse("cloud_customers") + "#create")


@login_required
def customer_detail_redirect(request, customer_id):
    require_cloud()
    return redirect("cloud_customer_detail", customer_id=customer_id)


@login_required
def customer_detail(request, customer_id):
    require_cloud()
    customer = get_object_or_404(
        Customer.objects.select_related("group__tariff", "wallet").prefetch_related("rates"),
        id=customer_id,
    )
    edges = EdgeNode.objects.exclude(status=EdgeStatus.REVOKED).order_by("name")
    edge_map = {edge.id: edge for edge in edges}
    edge = edge_map.get(customer.edge_id)
    rates = list(customer.rates.order_by("-is_default", "-is_active", "name"))
    active_rates = [r for r in rates if r.is_active]
    devices = list(
        ClientDevice.objects.filter(
            edge_id=customer.edge_id,
            is_active=True,
            connection_status=ConnectionStatus.ONLINE,
            occupancy_status=OccupancyStatus.FREE,
        )
        .exclude(sessions__status=SessionStatus.ACTIVE)
        .order_by("name")
    )
    tariffs = list(
        Tariff.objects.filter(edge_id=customer.edge_id, is_active=True).order_by("name")
    )
    default_hourly_rate = _cloud_default_hourly_rate()
    default_rate_obj = next((r for r in active_rates if r.is_default), None)
    group_tariff = (
        customer.group.tariff
        if (customer.group and customer.group.is_active and customer.group.tariff and customer.group.tariff.is_active)
        else None
    )
    if default_rate_obj is not None:
        effective_hourly_rate, effective_rate_name = default_rate_obj.hourly_rate, default_rate_obj.name
    elif group_tariff is not None:
        effective_hourly_rate, effective_rate_name = group_tariff.hourly_rate, f"تعرفه گروه ({group_tariff.name})"
    else:
        effective_hourly_rate, effective_rate_name = default_hourly_rate, "تعرفه پیش‌فرض سالن"

    operator_label = _operator_label(request.user)
    entries = list(
        customer.ledger_entries.select_related("session", "reverses").order_by("-created_at")[:60]
    )
    sessions = list(
        customer.sessions.select_related("device", "tariff", "customer_rate").order_by("-started_at")[:30]
    )
    active_sessions = customer.sessions.filter(status=SessionStatus.ACTIVE).select_related("device")
    active_session = active_sessions.first()
    commands = (
        RemoteCommand.objects.filter(
            edge_id=customer.edge_id, payload__customer_id=str(customer.id)
        )
        .select_related("edge")
        .order_by("-issued_at")[:20]
    )
    catalog_json = build_catalog_json(
        customers=[customer],
        tariffs=tariffs,
        devices=devices,
        default_hourly_rate=default_hourly_rate,
        operator_label=operator_label,
    )
    ctx = {
        "edges": edges,
        "customer": customer,
        "edge": edge,
        "rates": rates,
        "active_rates": active_rates,
        "devices": devices,
        "tariffs": tariffs,
        "default_hourly_rate": default_hourly_rate,
        "recharge_cadre_rate": next(
            (t.hourly_rate for t in tariffs if "کادر" in (t.name or "")), 20000
        ),
        "recharge_rahro_rate": next(
            (t.hourly_rate for t in tariffs if ("لیگ" in (t.name or "") or "رهرو" in (t.name or ""))),
            40000,
        ),
        "effective_hourly_rate": effective_hourly_rate,
        "effective_rate_name": effective_rate_name,
        "BillingMode": BillingMode,
        "DisconnectPolicy": DisconnectPolicy,
        "operator_label": operator_label,
        "entries": entries,
        "sessions": sessions,
        "catalog_json": catalog_json,
        "groups": CustomerGroup.objects.filter(
            Q(edge_id=customer.edge_id, is_active=True) | Q(id=customer.group_id)
        ).select_related("tariff").order_by("name"),
        "active_sessions": active_sessions,
        "active_session": active_session,
        "commands": commands,
    }

    # استعلام خودکار وضعیت عضو در سامانه رهرو
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
        elif rahro_url != "https://hammasjedy.ir/rahro/api/gamenet/":
            r_cloud = requests.get(
                "https://hammasjedy.ir/rahro/api/gamenet/status/",
                params={"phone": customer.phone, "username": customer.username},
                headers={"X-Internal-Secret": shared_secret},
                timeout=1.5,
            )
            if r_cloud.status_code == 200:
                rahro_status = r_cloud.json()
    except Exception:
        try:
            r_cloud = requests.get(
                "https://hammasjedy.ir/rahro/api/gamenet/status/",
                params={"phone": customer.phone, "username": customer.username},
                headers={"X-Internal-Secret": shared_secret},
                timeout=1.5,
            )
            if r_cloud.status_code == 200:
                rahro_status = r_cloud.json()
        except Exception:
            pass
    if rahro_status and rahro_status.get("found"):
        total_coupons = int(rahro_status.get("total_coupons") or rahro_status.get("remaining_monthly_quotas") or 0)
        if customer.active_coupons != total_coupons:
            customer.active_coupons = total_coupons
            customer.save(update_fields=["active_coupons", "updated_at"])
    ctx["rahro_status"] = rahro_status

    return render(request, "cloud/customer_detail.html", ctx)


@login_required
@require_POST
def customer_rahro_discount(request, customer_id):
    """
    اعمال مستقیم کوپن و تخفیف برای افراد رهرو توسط ادمین در پنل گیم‌نت:
    - در صورت وجود سهمیه ماهانه ۵۰٪، بدون کسر امتیاز از سهمیه کسر می‌شود.
    - در غیر این صورت متناسب با درصد، امتیاز رهرو کسر می‌گردد.
    - قابلیت تسویه فوری نصف قیمت و ثبت پرداخت نقدی برای نشست‌های در حال اجرا یا ثبت باجه.
    """
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        from datetime import timedelta
        from django.utils import timezone
        import requests
        from django.conf import settings
        from apps.core.money import session_cost
        from apps.ledger.models import LedgerEntry, LedgerEntryType
        from apps.wallets.models import Wallet

        discount_percent = int(request.POST.get("discount_percent", 50))
        action_type = (request.POST.get("action_type") or "").strip()
        duration_minutes = int(request.POST.get("duration_minutes") or 60)
        session_id = request.POST.get("session_id")

        rahro_url = getattr(settings, "RAHRO_API_URL", "http://127.0.0.1:8000/rahro/api/gamenet/")
        shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
        actor_name = request.user.get_full_name() or request.user.username or "مدیر گیم‌نت"

        # ۱. کسر هوشمند سهمیه ماهانه یا امتیاز در سامانه رهرو
        resp = requests.post(
            f"{rahro_url.rstrip('/')}/apply-discount/",
            json={
                "phone": customer.phone,
                "username": customer.username,
                "discount_percent": discount_percent,
                "session_id": str(session_id) if session_id else None,
                "actor_name": actor_name,
            },
            headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
            timeout=3.5,
        )
        data = {}
        try:
            data = resp.json()
        except Exception:
            pass

        if resp.status_code != 200 or not data.get("success"):
            err_msg = data.get("error") or data.get("message") or f"خطا در ارتباط با سامانه رهرو (کد وضعیت: {resp.status_code})"
            raise ValueError(err_msg)

        now = timezone.now()
        voucher_code = data.get("voucher_code", "")

        # بررسی وجود نشست فعال
        active_session = None
        if session_id:
            active_session = customer.sessions.filter(id=parse_uuid(session_id), status=SessionStatus.ACTIVE).first()
        if not active_session:
            active_session = customer.sessions.filter(status=SessionStatus.ACTIVE).first()

        # ۲. حالت الف: پایان نشست فعال و ثبت پرداخت نقدی نصف قیمت
        if (action_type == "settle_active" or (active_session and not action_type)) and active_session:
            elapsed = max(60, int((now - active_session.started_at).total_seconds()))
            dur_mins = max(1, elapsed // 60)
            rate = active_session.hourly_rate or 40000
            base_cost = session_cost(rate, elapsed)
            discount_amount = ((base_cost * discount_percent) + 50) // 100
            final_cost = max(0, base_cost - discount_amount)

            # خاتمه نشست فعال در کلود
            active_session.status = SessionStatus.COMPLETED
            active_session.ended_at = now
            active_session.elapsed_seconds = elapsed
            active_session.cost = final_cost
            active_session.discount_percent = discount_percent
            active_session.discount_amount = discount_amount
            active_session.discount_source = data.get("source", "RAHRO")
            active_session.end_reason = f"پایان نشست و پرداخت نقدی نصف قیمت ({final_cost:,} تومان)"
            active_session.save(
                update_fields=[
                    "status", "ended_at", "elapsed_seconds", "cost",
                    "discount_percent", "discount_amount", "discount_source",
                    "end_reason", "updated_at",
                ]
            )

            # ثبت تراکنش‌های دوبل حسابداری (شارژ هزینه نشست + دریافت پرداخت نقدی)
            wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})
            if final_cost > 0:
                wallet.balance -= final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=active_session.edge_id,
                    session=active_session,
                    entry_type=LedgerEntryType.SESSION_CHARGE,
                    amount=-final_cost,
                    balance_after=wallet.balance,
                    note=f"شارژ نشست ایستگاه {active_session.device.name if active_session.device else ''} ({dur_mins} دقیقه با تخفیف {discount_percent}٪)",
                    operator_label=actor_name,
                    created_by=request.user,
                    is_replica=True,
                )

                wallet.balance += final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=active_session.edge_id,
                    session=active_session,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=final_cost,
                    balance_after=wallet.balance,
                    note=f"پرداخت نقدی/پوز باجه (نصف قیمت: {final_cost:,} تومان) بابت {voucher_code or 'تخفیف رهرو'}",
                    operator_label=actor_name,
                    created_by=request.user,
                    is_replica=True,
                )
                wallet.save(update_fields=["balance"])

            # صدور فرمان توقف به سرور سالن (لبه)
            edge = _edge(active_session.edge_id)
            if edge:
                try:
                    _issue(
                        request,
                        edge,
                        "session.stop",
                        {
                            "session_id": str(active_session.id),
                            "reason": f"پایان نشست با تخفیف {discount_percent}٪ و تسویه نقدی",
                            "discount_percent": discount_percent,
                        },
                        action="remote.session.stopped_with_rahro_discount",
                    )
                except Exception:
                    pass

            # ثبت در کارنامه رهرو دانش‌آموز
            try:
                requests.post(
                    f"{rahro_url.rstrip('/')}/record-session/",
                    json={
                        "session_id": str(active_session.id),
                        "phone": customer.phone,
                        "username": customer.username,
                        "device_name": active_session.device.name if active_session.device else "ایستگاه بازی",
                        "started_at": active_session.started_at.isoformat(),
                        "ended_at": now.isoformat(),
                        "duration_seconds": elapsed,
                        "hourly_rate": rate,
                        "base_cost": base_cost,
                        "discount_percent": discount_percent,
                        "discount_amount": discount_amount,
                        "final_cost": final_cost,
                        "discount_source": f"سهمیه ماهانه / بلیت {voucher_code} (پرداخت‌شده)",
                    },
                    headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
                    timeout=2.5,
                )
            except Exception:
                pass

            messages.success(
                request,
                f"نشست ایستگاه «{active_session.device.name if active_session.device else ''}» متوقف و تسویه شد. "
                f"مبلغ نصف قیمت ({final_cost:,} تومان) به صورت نقدی در باجه دریافت و ثبت گردید. ({data.get('message', '')})"
            )

        # ۳. حالت ب: ثبت مستقیم بازی باجه و پرداخت نقدی بر مبنای ۱ ساعت (و شارژ خودکار نرخ)
        elif action_type == "record_paid_desk" or (not active_session and action_type not in ["auto_charge_rate", "reserve_coupon"]):
            dur_mins = duration_minutes
            dur_secs = dur_mins * 60
            
            # تعیین نرخ ساعتی بر اساس گروه یا وضعیت رهرو (۴۰ هزار یا ۲۰ هزار تومان)
            hourly_rate = int(data.get("base_hourly_rate") or (customer.group.tariff.hourly_rate if customer.group and customer.group.tariff else 40000))
            base_cost = (hourly_rate * dur_mins) // 60
            discount_amount = ((base_cost * discount_percent) + 50) // 100
            final_cost = max(0, base_cost - discount_amount)

            edge = EdgeNode.objects.filter(revoked_at__isnull=True).order_by("-last_heartbeat_at").first()
            edge_id = edge.id if edge else (customer.edge_id or uuid.UUID("01a18e45-00ea-7f5b-8631-0d6406670e55"))

            last_device_id = (
                customer.sessions.order_by("-started_at")
                .values_list("device_id", flat=True)
                .first()
            )
            device = (
                ClientDevice.objects.filter(id=last_device_id, is_active=True).first()
                or ClientDevice.objects.filter(edge_id=edge_id, is_active=True).first()
                or ClientDevice.objects.filter(is_active=True).first()
            )

            new_sess_id = uuid.uuid4()
            started_at = now - timedelta(seconds=dur_secs)

            # ایجاد سابقه نشست تکمیل‌شده در گیم‌نت
            sess = GamingSession.objects.create(
                id=new_sess_id,
                edge_id=edge_id,
                customer=customer,
                device=device,
                tariff_name=customer.group.name if customer.group else "آزاد",
                hourly_rate=hourly_rate,
                started_at=started_at,
                ended_at=now,
                elapsed_seconds=dur_secs,
                cost=final_cost,
                discount_percent=discount_percent,
                discount_amount=discount_amount,
                discount_source=f"رهرو ({voucher_code or 'کوپن'})",
                status=SessionStatus.COMPLETED,
                end_reason=f"ثبت باجه و پرداخت نقدی ۱ ساعت بازی ({final_cost:,} تومان)",
                is_replica=True,
            )

            wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})
            if final_cost > 0:
                wallet.balance -= final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=edge_id,
                    session=sess,
                    entry_type=LedgerEntryType.SESSION_CHARGE,
                    amount=-final_cost,
                    balance_after=wallet.balance,
                    note=f"شارژ نشست باجه ({dur_mins} دقیقه با تخفیف {discount_percent}٪)",
                    operator_label=actor_name,
                    created_by=request.user,
                    is_replica=True,
                )

                wallet.balance += final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=edge_id,
                    session=sess,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=final_cost,
                    balance_after=wallet.balance,
                    note=f"پرداخت نقدی/پوز باجه ({final_cost:,} تومان) بابت {voucher_code or 'تخفیف رهرو'}",
                    operator_label=actor_name,
                    created_by=request.user,
                    is_replica=True,
                )
                wallet.save(update_fields=["balance"])

            # شارژ خودکار نرخ مشتری در گیم‌نت برای ورود با کد لاگین در سالن:
            from apps.pricing.models import CustomerRate
            disc_rate_amount = ((hourly_rate * discount_percent) + 50) // 100
            discounted_hourly_rate = max(0, hourly_rate - disc_rate_amount)

            if discounted_hourly_rate > 0:
                CustomerRate.objects.filter(customer=customer, is_default=True).update(is_default=False)
                rate_obj = CustomerRate.objects.filter(customer=customer, name__startswith="تخفیف کوپن رهرو").first()
                if rate_obj:
                    rate_obj.name = f"تخفیف کوپن رهرو ({discount_percent}٪)"
                    rate_obj.hourly_rate = discounted_hourly_rate
                    rate_obj.is_default = True
                    rate_obj.is_active = True
                    rate_obj.save(update_fields=["name", "hourly_rate", "is_default", "is_active", "updated_at"])
                else:
                    rate_obj = CustomerRate.objects.create(
                        id=uuid.uuid4(),
                        edge_id=edge_id,
                        customer=customer,
                        name=f"تخفیف کوپن رهرو ({discount_percent}٪)",
                        hourly_rate=discounted_hourly_rate,
                        is_default=True,
                        is_active=True,
                        is_replica=True,
                    )
                if edge:
                    try:
                        _issue(
                            request,
                            edge,
                            "catalog.customer_rate.upsert",
                            {
                                "customer_rate_id": str(rate_obj.id),
                                "customer_id": str(customer.id),
                                "base_revision": rate_obj.revision,
                                "name": rate_obj.name,
                                "hourly_rate": rate_obj.hourly_rate,
                                "is_default": True,
                                "is_active": True,
                            },
                            action="remote.customer_rate.synced_from_rahro",
                        )
                    except Exception:
                        pass
            elif discount_percent == 100:
                wallet.balance += hourly_rate
                wallet.save(update_fields=["balance"])
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=edge_id,
                    session=sess,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=hourly_rate,
                    balance_after=wallet.balance,
                    note="شارژ خودکار کیف پول بابت ۱ ساعت بازی رایگان کوپن رهرو (۱۰۰٪)",
                    operator_label=actor_name,
                    created_by=request.user,
                    is_replica=True,
                )

            # همگام‌سازی با سامانه رهرو
            try:
                requests.post(
                    f"{rahro_url.rstrip('/')}/record-session/",
                    json={
                        "session_id": str(new_sess_id),
                        "phone": customer.phone,
                        "username": customer.username,
                        "device_name": "باجه گیم‌نت مسجد",
                        "started_at": started_at.isoformat(),
                        "ended_at": now.isoformat(),
                        "duration_seconds": dur_secs,
                        "hourly_rate": hourly_rate,
                        "base_cost": base_cost,
                        "discount_percent": discount_percent,
                        "discount_amount": discount_amount,
                        "final_cost": final_cost,
                        "discount_source": f"سهمیه ماهانه / بلیت {voucher_code} (پرداخت‌شده)",
                    },
                    headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
                    timeout=2.5,
                )
            except Exception:
                pass

            messages.success(
                request,
                f"بازی {dur_mins} دقیقه‌ای با تخفیف {discount_percent}٪ و پرداخت نقدی {final_cost:,} تومان "
                f"با موفقیت ثبت و تسویه شد. همچنین نرخ ساعتی در کلاینت برای ۱ ساعت روی {discounted_hourly_rate:,} ت شارژ گردید. ({data.get('message', '')})"
            )

        # ۴. حالت ج: شارژ خودکار نرخ ۱ ساعت بازی در کلاینت سالن (بدون ثبت نشست در باجه)
        elif action_type == "auto_charge_rate":
            hourly_rate = int(data.get("base_hourly_rate") or (customer.group.tariff.hourly_rate if customer.group and customer.group.tariff else 40000))
            disc_rate_amount = ((hourly_rate * discount_percent) + 50) // 100
            discounted_hourly_rate = max(0, hourly_rate - disc_rate_amount)

            edge = EdgeNode.objects.filter(revoked_at__isnull=True).order_by("-last_heartbeat_at").first()
            edge_id = edge.id if edge else (customer.edge_id or uuid.UUID("01a18e45-00ea-7f5b-8631-0d6406670e55"))

            from apps.pricing.models import CustomerRate
            if discounted_hourly_rate > 0:
                CustomerRate.objects.filter(customer=customer, is_default=True).update(is_default=False)
                rate_obj = CustomerRate.objects.filter(customer=customer, name__startswith="تخفیف کوپن رهرو").first()
                if rate_obj:
                    rate_obj.name = f"تخفیف کوپن رهرو ({discount_percent}٪)"
                    rate_obj.hourly_rate = discounted_hourly_rate
                    rate_obj.is_default = True
                    rate_obj.is_active = True
                    rate_obj.save(update_fields=["name", "hourly_rate", "is_default", "is_active", "updated_at"])
                else:
                    rate_obj = CustomerRate.objects.create(
                        id=uuid.uuid4(),
                        edge_id=edge_id,
                        customer=customer,
                        name=f"تخفیف کوپن رهرو ({discount_percent}٪)",
                        hourly_rate=discounted_hourly_rate,
                        is_default=True,
                        is_active=True,
                        is_replica=True,
                    )
                if edge:
                    try:
                        _issue(
                            request,
                            edge,
                            "catalog.customer_rate.upsert",
                            {
                                "customer_rate_id": str(rate_obj.id),
                                "customer_id": str(customer.id),
                                "base_revision": rate_obj.revision,
                                "name": rate_obj.name,
                                "hourly_rate": rate_obj.hourly_rate,
                                "is_default": True,
                                "is_active": True,
                            },
                            action="remote.customer_rate.synced_from_rahro",
                        )
                    except Exception:
                        pass
                messages.success(
                    request,
                    f"شارژ خودکار نرخ انجام شد: نرخ ساعتی {customer.full_name} برای ۱ ساعت بازی به {discounted_hourly_rate:,} تومان (به جای {hourly_rate:,} تومان) تغییر یافت. ({data.get('message', '')})"
                )
            else:
                wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})
                wallet.balance += hourly_rate
                wallet.save(update_fields=["balance"])
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=edge_id,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=hourly_rate,
                    balance_after=wallet.balance,
                    note="شارژ خودکار کیف پول بابت ۱ ساعت بازی رایگان کوپن رهرو (۱۰۰٪)",
                    operator_label=actor_name,
                    created_by=request.user,
                    is_replica=True,
                )
                messages.success(
                    request,
                    f"شارژ خودکار ۱ ساعت بازی رایگان (۱۰۰٪) انجام شد: مبلغ {hourly_rate:,} تومان به کیف پول کاربر اضافه گردید. ({data.get('message', '')})"
                )

        # ۵. حالت د: صرفاً اعمال تخفیف روی نشست فعال در حال اجرا
        elif action_type == "apply_active" and active_session:
            active_session.discount_percent = discount_percent
            active_session.discount_source = data.get("source", "RAHRO")
            active_session.save(update_fields=["discount_percent", "discount_source", "updated_at"])
            messages.success(request, f"تخفیف {discount_percent}٪ با موفقیت روی نشست جاری {customer.full_name} ثبت شد. ({data.get('message')})")

        # ۶. حالت ه: صدور کوپن رزرو برای بازی‌های بعدی
        else:
            messages.success(request, f"کوپن تخفیف {discount_percent}٪ برای {customer.full_name} در رهرو صادر شد: {data.get('message')}")

    except Exception as exc:
        messages.error(request, str(exc))

    referer = request.META.get("HTTP_REFERER")
    if referer and ("customers/" in referer or "manage/customers/" in referer):
        return redirect(referer)
    return redirect("cloud_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_rahro_recharge(request, customer_id):
    """
    شارژ سریع، شفاف و هوشمند حساب کاربری گیم‌نت:
    - دریافت وجه نقد یا کارتخوان از کاربر و افزایش موجودی کیف پول.
    - در صورت انتخاب سهمیه ماهانه رهرو (برای پایه‌های ۵ تا ۷)، مصرف ۱ سهمیه ماهانه در رهرو و تنظیم نرخ کلاینت روی ۲۰,۰۰۰ تومان برای ۱ ساعت.
    - اگر کاربر عضو کادر یا پایه ۸ و ۹ باشد، محاسبه بر مبنای نرخ ۲۰,۰۰۰ ت.
    - اگر کاربر عادی باشد، محاسبه بر مبنای نرخ ۶۰,۰۰۰ ت.
    - ثبت در حسابداری (دفتر کل) و ارسال فرمان wallet.deposit و customer_rate.upsert به سرور سالن (لبه).
    """
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)

    try:
        raw_amount = str(request.POST.get("amount") or "0").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")).replace(",", "").replace("،", "").strip()
        amount = int(raw_amount or 0)
        use_coupon = (request.POST.get("use_coupon") or "").strip()
        payment_method = (request.POST.get("payment_method") or "pos").strip()

        rahro_url = getattr(settings, "RAHRO_API_URL", "http://127.0.0.1:8000/rahro/api/gamenet/")
        shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
        actor_name = request.user.get_full_name() or request.user.username or "مدیر گیم‌نت"
        method_title = "کارتخوان باجه" if payment_method == "pos" else "نقدی"

        edge = _edge(customer.edge_id)
        if not edge:
            edge = EdgeNode.objects.filter(revoked_at__isnull=True).order_by("-last_heartbeat_at").first()
        edge_id = edge.id if edge else (customer.edge_id or uuid.UUID("01a18e45-00ea-7f5b-8631-0d6406670e55"))

        applied_coupon_note = ""
        discount_percent = 0
        if use_coupon in ["50", "100"]:
            discount_percent = int(use_coupon)
            try:
                import requests
                resp = None
                try:
                    resp = requests.post(
                        f"{rahro_url.rstrip('/')}/apply-discount/",
                        json={
                            "phone": customer.phone,
                            "username": customer.username,
                            "discount_percent": discount_percent,
                            "actor_name": actor_name,
                        },
                        headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
                        timeout=3.0,
                    )
                except Exception:
                    pass
                if (not resp or resp.status_code != 200) and rahro_url != "https://hammasjedy.ir/rahro/api/gamenet/":
                    try:
                        resp = requests.post(
                            "https://hammasjedy.ir/rahro/api/gamenet/apply-discount/",
                            json={
                                "phone": customer.phone,
                                "username": customer.username,
                                "discount_percent": discount_percent,
                                "actor_name": actor_name,
                            },
                            headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
                            timeout=3.0,
                        )
                    except Exception:
                        pass
                data = resp.json() if resp and resp.status_code == 200 else {}
                if resp and resp.status_code == 200 and data.get("success"):
                    applied_coupon_note = data.get("message") or f"سهمیه {discount_percent}٪ رهرو اعمال شد."
                else:
                    err = data.get("error") or data.get("message") or "عدم پاسخ مناسب از سامانه رهرو"
                    messages.warning(request, f"هشدار سهمیه رهرو: {err}")
            except Exception as e:
                messages.warning(request, f"خطا در ارتباط با سامانه رهرو: {str(e)}")

        # در صورت استفاده از کوپن ۵۰٪، نرخ ساعتی کلاینت روی ۲۰,۰۰۰ تومان تنظیم می‌شود
        if discount_percent == 50:
            from apps.pricing.models import CustomerRate
            CustomerRate.objects.filter(customer=customer, is_default=True).update(is_default=False)
            rate_obj = CustomerRate.objects.filter(customer=customer, name__startswith="تخفیف کوپن رهرو").first()
            if rate_obj:
                rate_obj.name = "تخفیف کوپن رهرو (۵۰٪)"
                rate_obj.hourly_rate = 20000
                rate_obj.is_default = True
                rate_obj.is_active = True
                rate_obj.save(update_fields=["name", "hourly_rate", "is_default", "is_active", "updated_at"])
            else:
                rate_obj = CustomerRate.objects.create(
                    id=uuid.uuid4(),
                    edge_id=edge_id,
                    customer=customer,
                    name="تخفیف کوپن رهرو (۵۰٪)",
                    hourly_rate=20000,
                    is_default=True,
                    is_active=True,
                    is_replica=True,
                )
            if edge:
                try:
                    _issue(
                        request,
                        edge,
                        "catalog.customer_rate.upsert",
                        {
                            "customer_rate_id": str(rate_obj.id),
                            "customer_id": str(customer.id),
                            "base_revision": rate_obj.revision,
                            "name": rate_obj.name,
                            "hourly_rate": rate_obj.hourly_rate,
                            "is_default": True,
                            "is_active": True,
                        },
                        action="remote.customer_rate.synced_from_rahro",
                    )
                except Exception:
                    pass

        # شارژ کیف پول
        from apps.wallets.models import Wallet
        from apps.ledger.models import LedgerEntry, LedgerEntryType

        wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})
        total_credit = amount
        if discount_percent == 100 and amount == 0:
            total_credit = 40000

        is_debt = bool(request.POST.get("is_debt"))
        if is_debt and total_credit > 0:
            max_limit = customer.max_debt_limit or 40000
            current_debt = customer.debt_balance or 0
            if current_debt + total_credit > max_limit:
                messages.error(
                    request,
                    f"ثبت بدهی ممکن نیست! سقف مجاز بدهی {max_limit:,} تومان است و بدهی فعلی {current_debt:,} تومان می‌باشد (حداکثر بدهی جدید: {max(0, max_limit - current_debt):,} تومان).",
                )
                return safe_redirect_next(request, "cloud_customer_detail", customer_id=customer.id)

        if total_credit > 0:
            note_custom = (request.POST.get("note") or "").strip()[:160]
            prefix = "شارژ نسیه (بدهی)" if is_debt else "شارژ کیف پول"
            note = f"{prefix} ({total_credit:,} ت - {method_title})"
            if discount_percent == 50:
                note += " [همراه با سهمیه ۵۰٪ رهرو - نرخ کلاینت ۲۰,۰۰۰ ت]"
            elif discount_percent == 100:
                note += " [اعتبار هدیه کوپن ۱۰۰٪ رایگان رهرو]"
            if note_custom:
                note = f"{note} — {note_custom}"[:255]

            entry_id = str(uuid.uuid4())
            tracking_code = generate_tracking_code()
            cmd = None
            if edge:
                try:
                    cmd = _issue(
                        request,
                        edge,
                        "wallet.deposit",
                        {
                            "customer_id": str(customer.id),
                            "amount": total_credit,
                            "is_debt": is_debt,
                            "reason": note,
                            "requested_by": actor_name,
                            "entry_id": entry_id,
                            "tracking_code": tracking_code,
                            "operator_label": actor_name,
                        },
                        action="remote.wallet.deposit",
                    )
                except Exception:
                    cmd = None

            already_created = bool(
                cmd and LedgerEntry.objects.filter(source_command_id=cmd.id).exists()
            )
            if not already_created:
                wallet.balance += total_credit
                wallet.save(update_fields=["balance"])
                if is_debt:
                    customer.debt_balance = (customer.debt_balance or 0) + total_credit
                    customer.save(update_fields=["debt_balance"])
                LedgerEntry.objects.create(
                    id=entry_id,
                    customer=customer,
                    edge_id=edge_id,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=total_credit,
                    balance_after=wallet.balance,
                    is_debt=is_debt,
                    note=note,
                    tracking_code=tracking_code,
                    operator_label=actor_name,
                    source_command_id=cmd.id if cmd else None,
                    created_by=request.user,
                    is_replica=True,
                )

            msg = (
                f"کیف پول {customer.full_name} با موفقیت به مبلغ {total_credit:,} تومان ({method_title}) شارژ شد. "
                f"موجودی جدید: {wallet.balance:,} تومان. کد پیگیری: {tracking_code}"
            )
            if is_debt:
                msg += f" (ثبت به عنوان بدهی - بدهی کل: {customer.debt_balance:,} تومان)"
            if applied_coupon_note:
                msg += f" ({applied_coupon_note})"
            messages.success(request, msg)
        else:
            messages.info(request, "هیچ مبلغی برای شارژ کیف پول وارد نشد.")

    except Exception as exc:
        messages.error(request, f"خطا در شارژ کیف پول: {str(exc)}")

    return safe_redirect_next(request, "cloud_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_settle_debt(request, customer_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    raw_amount = (
        str(request.POST.get("amount") or "")
        .translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        .replace(",", "")
        .replace("،", "")
        .strip()
    )
    amount = int(raw_amount) if raw_amount.isdigit() else None
    note = str(request.POST.get("note") or "").strip()[:160]
    actor_name = request.user.get_full_name() or request.user.username or "مدیر آنلاین"

    from apps.wallets.services import settle_debt

    try:
        paid, entry = settle_debt(
            customer=customer,
            amount=amount,
            note=note or "تسویه نقدی بدهی از پنل آنلاین",
            operator_label=actor_name,
            actor=request.user,
        )
        edge = _edge(customer.edge_id)
        if not edge:
            edge = EdgeNode.objects.filter(revoked_at__isnull=True).order_by("-last_heartbeat_at").first()
        if edge and entry:
            try:
                _issue(
                    request,
                    edge,
                    "wallet.settle_debt",
                    {
                        "customer_id": str(customer.id),
                        "amount": paid,
                        "note": entry.note,
                        "entry_id": str(entry.id),
                        "tracking_code": entry.tracking_code,
                        "operator_label": actor_name,
                    },
                    action="remote.wallet.settle_debt",
                )
            except Exception:
                pass

        messages.success(
            request,
            f"مبلغ {paid:,} تومان از بدهی {customer.full_name} با موفقیت تسویه شد. بدهی باقیمانده: {customer.debt_balance:,} تومان.",
        )
    except Exception as exc:
        messages.error(request, f"خطا در تسویه بدهی: {str(exc)}")

    return safe_redirect_next(request, "cloud_customer_detail", customer_id=customer.id)


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

        full_name = (request.POST.get("full_name") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        username = (request.POST.get("username") or "").strip()
        password = (request.POST.get("password") or "").strip()

        # تبدیل ارقام فارسی و عربی به ارقام انگلیسی
        persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
        english = "01234567890123456789"
        if username:
            username = username.translate(str.maketrans(persian_arabic, english)).strip()
            if not username.isdigit() or len(username) < 4 or len(username) > 6:
                raise ValueError("کد ۴ تا ۶ رقمی ورود کلاینت باید یک عدد بین ۴ تا ۶ رقم باشد (یا فیلد را خالی بگذارید).")
            dup = Customer.objects.filter(username=username).exclude(id=customer.id).first()
            if dup:
                raise ValueError(f"کد عددی «{username}» قبلاً برای «{dup.full_name}» ثبت شده است.")

        # به‌روزرسانی کلود رپلیکا
        customer.full_name = full_name or customer.full_name
        customer.phone = phone
        customer.username = username
        customer.group = group
        customer.credit_limit = _int(request.POST.get("credit_limit"), "سقف اعتبار")
        if "max_debt_limit" in request.POST:
            try:
                raw_debt = str(request.POST.get("max_debt_limit") or "40000").replace(",", "").strip()
                customer.max_debt_limit = max(0, int(raw_debt))
            except (ValueError, TypeError):
                pass
        customer.notes = (request.POST.get("notes") or "").strip()
        customer.is_active = request.POST.get("is_active") == "1"
        if password:
            customer.set_password(password)
        customer.save()

        _issue(
            request,
            edge,
            "catalog.customer.upsert",
            {
                "customer_id": str(customer.id),
                "base_revision": _int(
                    request.POST.get("base_revision", customer.revision), "نسخه"
                ),
                "full_name": customer.full_name,
                "phone": customer.phone,
                "username": customer.username,
                "password": password,
                "group_id": str(group.id) if group else None,
                "credit_limit": customer.credit_limit,
                "max_debt_limit": customer.max_debt_limit,
                "notes": customer.notes,
                "is_active": customer.is_active,
            },
            action="remote.customer.updated",
        )

        # اگر کاربر در رهرو باشد، کد ورود گیم‌نت را در رهرو هم هماهنگ کن (یا در صورت خالی بودن، پاک کن)
        try:
            import requests
            from django.conf import settings
            rahro_url = getattr(settings, "RAHRO_API_URL", "http://127.0.0.1:8000/rahro/api/gamenet/")
            shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
            requests.post(
                f"{rahro_url.rstrip('/')}/set-login-code/",
                json={"phone": customer.phone, "username": customer.username, "login_code": username},
                headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
                timeout=1.5,
            )
        except Exception:
            pass

        messages.success(request, f"مشخصات «{customer.full_name}» با موفقیت ذخیره و با سرور سالن همگام شد.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("cloud_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


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
    return redirect(reverse("cloud_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


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
    return redirect(reverse("cloud_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


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
    return redirect(reverse("cloud_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


@login_required
def wallet(request, customer_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    if request.method != "POST":
        return safe_redirect_next(request, "cloud_customer_detail", customer_id=customer.id)
    edge = _edge(customer.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این مشتری یافت نشد.")
        action = (request.POST.get("action") or "deposit").strip()
        if action not in {"deposit", "adjust"}:
            raise ValueError("نوع عملیات کیف پول نامعتبر است.")
        amount = _int(request.POST.get("amount"), "مبلغ")
        if action == "deposit" and amount <= 0:
            raise ValueError("مبلغ شارژ باید بزرگ‌تر از صفر باشد.")
        if action == "adjust" and amount == 0:
            raise ValueError("مبلغ اصلاح نمی‌تواند صفر باشد.")
        reason = (request.POST.get("reason") or request.POST.get("note") or "").strip()[:255]
        if not reason:
            raise ValueError("دلیل یا یادداشت عملیات الزامی است.")

        entry_id = str(uuid.uuid4())
        tracking_code = generate_tracking_code()
        op_label = _operator_label(request.user)
        cmd = _issue(
            request,
            edge,
            "wallet.deposit" if action == "deposit" else "wallet.adjust",
            {
                "customer_id": str(customer.id),
                "amount": amount,
                "reason": reason,
                "requested_by": op_label,
                "entry_id": entry_id,
                "tracking_code": tracking_code,
                "operator_label": op_label,
            },
            action=f"remote.wallet.{action}",
        )
        if (
            action == "deposit"
            and not LedgerEntry.objects.filter(source_command_id=cmd.id).exists()
        ):
            wallet_obj, _ = Wallet.objects.get_or_create(
                customer=customer, defaults={"balance": 0}
            )
            wallet_obj.balance += amount
            wallet_obj.save(update_fields=["balance"])
            LedgerEntry.objects.create(
                id=entry_id,
                customer=customer,
                edge_id=edge.id,
                entry_type=LedgerEntryType.DEPOSIT,
                amount=amount,
                balance_after=wallet_obj.balance,
                note=reason,
                tracking_code=tracking_code,
                operator_label=op_label,
                source_command_id=cmd.id,
                created_by=request.user,
                is_replica=True,
            )
            messages.success(
                request,
                f"کیف پول {customer.full_name} به مبلغ {amount:,} تومان شارژ شد. "
                f"موجودی پس از شارژ: {wallet_obj.balance:,} تومان · کد پیگیری: {tracking_code}",
            )
        else:
            messages.success(
                request,
                f"درخواست ثبت تراکنش ({amount:,} تومان) برای {customer.full_name} با کد پیگیری {tracking_code} ارسال شد.",
            )
    except ValueError as exc:
        messages.error(request, str(exc))
    return safe_redirect_next(request, "cloud_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def session_start(request, customer_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    edge = _edge(customer.edge_id)
    try:
        if edge is None:
            raise ValueError("Edge مربوط به این مشتری یافت نشد.")
        raw_sid = (request.POST.get("session_id") or "").strip()
        if raw_sid:
            try:
                session_id = str(uuid.UUID(raw_sid))
            except (TypeError, ValueError) as exc:
                raise ValueError("شناسه نشست نامعتبر است.") from exc
        else:
            session_id = str(uuid.uuid4())
        device = ClientDevice.objects.filter(
            id=request.POST.get("device_id"), edge_id=customer.edge_id, is_active=True
        ).first()
        if device is None:
            raise ValueError("دستگاه انتخاب‌شده معتبر نیست.")

        rate_choice = (request.POST.get("rate_choice") or "").strip()
        rate_id = (request.POST.get("customer_rate_id") or "").strip() or None
        tariff_id = (request.POST.get("tariff_id") or "").strip() or None
        if rate_choice.startswith("rate:"):
            rate_id = rate_choice.split(":", 1)[1].strip() or None
            tariff_id = None
        elif rate_choice.startswith("tariff:"):
            tariff_id = rate_choice.split(":", 1)[1].strip() or None
            rate_id = None

        rate = (
            CustomerRate.objects.filter(
                id=rate_id, customer=customer, is_active=True
            ).first()
            if rate_id
            else None
        )
        if rate_id and rate is None:
            raise ValueError("نرخ انتخاب‌شده معتبر نیست.")
        tariff = (
            Tariff.objects.filter(
                id=tariff_id, edge_id=customer.edge_id, is_active=True
            ).first()
            if tariff_id and rate is None
            else None
        )
        if tariff_id and rate is None and tariff is None:
            raise ValueError("تعرفه انتخاب‌شده معتبر نیست.")

        billing_mode = (request.POST.get("billing_mode") or BillingMode.CREDIT).strip().upper()
        if billing_mode not in BillingMode.values:
            billing_mode = BillingMode.CREDIT

        planned_minutes = None
        if billing_mode == BillingMode.TIMED:
            planned_minutes = _int(
                request.POST.get("planned_duration_minutes"), "مدت زمان نشست (دقیقه)"
            )
            if planned_minutes < 5 or planned_minutes > 720:
                raise ValueError("مدت نشست زمانی باید بین ۵ تا ۷۲۰ دقیقه باشد.")

        disconnect_policy = (
            (request.POST.get("disconnect_policy") or DisconnectPolicy.PAUSE).strip().upper()
        )
        if disconnect_policy not in DisconnectPolicy.values:
            disconnect_policy = DisconnectPolicy.PAUSE

        _issue(
            request,
            edge,
            "session.start",
            {
                "session_id": session_id,
                "customer_id": str(customer.id),
                "device_id": str(device.id),
                "customer_rate_id": str(rate.id) if rate else None,
                "tariff_id": str(tariff.id) if tariff else None,
                "billing_mode": billing_mode,
                "planned_duration_minutes": planned_minutes,
                "disconnect_policy": disconnect_policy,
            },
            action="remote.session.started",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return safe_redirect_next(request, "cloud_customer_detail", customer_id=customer.id)


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

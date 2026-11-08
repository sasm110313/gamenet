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
from django.db import IntegrityError
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

            # نرمال‌سازی ارقام فارسی/عربی کد ورود به انگلیسی
            persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
            english = "01234567890123456789"
            if username:
                username = username.translate(str.maketrans(persian_arabic, english)).strip()

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
            from apps.customers.models import Customer
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
                _issue(
                    request,
                    salon_server,
                    "wallet.deposit",
                    {
                        "customer_id": customer_id,
                        "amount": initial_deposit,
                        "reason": "شارژ اولیه هنگام ثبت نام",
                    },
                    action="remote.customer.initial_deposit",
                )
                wallet.balance += initial_deposit
                wallet.save(update_fields=["balance"])
                LedgerEntry.objects.create(
                    customer=cloud_cust,
                    edge_id=salon_server.id,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=initial_deposit,
                    balance_after=wallet.balance,
                    note="شارژ اولیه هنگام ثبت نام",
                    is_replica=True,
                )

            messages.success(request, f"مشتری «{full_name}» با موفقیت ثبت شد.")
            return redirect("cloud_customers")
        except (ValueError, IntegrityError) as exc:
            if "customers_unique_phone_per_edge" in str(exc) or "phone" in str(exc):
                messages.error(request, "مشتری دیگری با این شماره تماس از قبل ثبت شده است.")
            else:
                messages.error(request, str(exc))

    # GET request: render the form
    groups = CustomerGroup.objects.filter(is_active=True).order_by("name")
    return render(
        request,
        "cloud/customer_create.html",
        {
            "salon_server": salon_server,
            "groups": groups,
        },
    )


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
    except Exception:
        pass
    ctx["rahro_status"] = rahro_status

    return render(request, "cloud/manage_customer.html", ctx)


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
        duration_minutes = int(request.POST.get("duration_minutes") or 45)
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
            active_session = customer.sessions.filter(id=session_id, status=SessionStatus.ACTIVE).first()
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

        # ۳. حالت ب: ثبت مستقیم بازی باجه و پرداخت نقدی نصف قیمت (بدون نشست فعال)
        elif action_type == "record_paid_desk" or (not active_session and action_type != "reserve_coupon"):
            dur_mins = duration_minutes
            dur_secs = dur_mins * 60
            hourly_rate = 40000
            base_cost = (hourly_rate * dur_mins) // 60
            discount_amount = ((base_cost * discount_percent) + 50) // 100
            final_cost = max(0, base_cost - discount_amount)

            edge = EdgeNode.objects.filter(revoked_at__isnull=True).order_by("-last_heartbeat_at").first()
            edge_id = edge.id if edge else (customer.edge_id or uuid.UUID("01a18e45-00ea-7f5b-8631-0d6406670e55"))

            device = ClientDevice.objects.filter(edge_id=edge_id, is_active=True).first()
            if not device:
                device = ClientDevice.objects.filter(is_active=True).first()

            new_sess_id = uuid.uuid4()
            started_at = now - timedelta(seconds=dur_secs)

            # ایجاد سابقه نشست تکمیل‌شده در گیم‌نت
            sess = GamingSession.objects.create(
                id=new_sess_id,
                edge_id=edge_id,
                customer=customer,
                device=device,
                tariff_name="اعضای رهرو",
                hourly_rate=hourly_rate,
                started_at=started_at,
                ended_at=now,
                elapsed_seconds=dur_secs,
                cost=final_cost,
                discount_percent=discount_percent,
                discount_amount=discount_amount,
                discount_source=f"رهرو ({voucher_code or 'کوپن'})",
                status=SessionStatus.COMPLETED,
                end_reason=f"ثبت باجه و پرداخت نقدی نصف قیمت ({final_cost:,} تومان)",
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
                    note=f"پرداخت نقدی/پوز باجه (نصف قیمت: {final_cost:,} تومان) بابت {voucher_code or 'تخفیف رهرو'}",
                    is_replica=True,
                )
                wallet.save(update_fields=["balance"])

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
                f"بازی {dur_mins} دقیقه‌ای با تخفیف {discount_percent}٪ و پرداخت نقدی {final_cost:,} تومان (نصف قیمت) "
                f"با موفقیت ثبت و تسویه شد. ({data.get('message', '')})"
            )

        # ۴. حالت ج: صرفاً اعمال تخفیف روی نشست فعال در حال اجرا
        elif action_type == "apply_active" and active_session:
            active_session.discount_percent = discount_percent
            active_session.discount_source = data.get("source", "RAHRO")
            active_session.save(update_fields=["discount_percent", "discount_source", "updated_at"])
            messages.success(request, f"تخفیف {discount_percent}٪ با موفقیت روی نشست جاری {customer.full_name} ثبت شد. ({data.get('message')})")

        # ۵. حالت د: صدور کوپن رزرو برای بازی‌های بعدی
        else:
            messages.success(request, f"کوپن تخفیف {discount_percent}٪ برای {customer.full_name} در رهرو صادر شد: {data.get('message')}")

    except Exception as exc:
        messages.error(request, str(exc))

    referer = request.META.get("HTTP_REFERER")
    if referer and ("customers/" in referer or "manage/customers/" in referer):
        return redirect(referer)
    return redirect("cloud_manage_customer", customer_id=customer.id)


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

        # به‌روزرسانی کلود رپلیکا
        customer.full_name = full_name or customer.full_name
        customer.phone = phone
        if username:
            customer.username = username
        customer.group = group
        customer.credit_limit = _int(request.POST.get("credit_limit"), "سقف اعتبار")
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
                "notes": customer.notes,
                "is_active": customer.is_active,
            },
            action="remote.customer.updated",
        )

        # اگر کاربر در رهرو باشد، کد ورود گیم‌نت را در رهرو هم هماهنگ کن
        if username:
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
def wallet(request, customer_id):
    require_cloud()
    customer = get_object_or_404(Customer, id=customer_id)
    if request.method != "POST":
        return redirect("cloud_manage_customer", customer_id=customer.id)
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

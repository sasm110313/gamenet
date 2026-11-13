"""Edge customer counter: search, registration, wallet operations."""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.redirects import safe_redirect_next
from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ConnectionStatus, OccupancyStatus
from apps.core.catalog_payload import build_catalog_json
from apps.core.dashboard import edge_common
from apps.customers.models import Customer
from apps.customers.services import CustomerError, create_customer, update_customer
from apps.customer_groups.models import CustomerGroup
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.pricing.models import CustomerRate, Tariff
from apps.pricing.services import (
    CustomerRateError,
    create_customer_rate,
    deactivate_customer_rate,
    set_default_customer_rate,
    update_customer_rate,
)
from apps.sessions.models import BillingMode, DisconnectPolicy, GamingSession, SessionStatus
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
            Q(full_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(username__icontains=q)
            | Q(id__icontains=q)
        )
    ctx.update(
        {
            "customers": qs[:300],
            "groups": CustomerGroup.objects.filter(is_active=True).select_related("tariff").order_by("name"),
            "q": q,
            "default_credit_limit": ctx["config"].get("default_credit_limit"),
            "customers_total": Customer.objects.filter(is_active=True).count(),
            "wallet_total": Wallet.objects.aggregate(total=Sum("balance"))["total"] or 0,
            "sessions_active": GamingSession.objects.filter(status=SessionStatus.ACTIVE).count(),
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
                return redirect(reverse("edge_customers") + "#create")
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
                deposit(
                    customer,
                    initial_deposit,
                    actor=request.user,
                    note="شارژ اولیه هنگام ثبت نام",
                )
        except (CustomerError, ValueError) as exc:
            messages.error(request, str(exc))
            return redirect(reverse("edge_customers") + "#create")

        _audit(request, "customer.created", "customer", customer.id, {"name": customer.full_name})
        messages.success(request, f"مشتری {customer.full_name} با موفقیت ثبت شد.")
        return redirect("edge_customer_detail", customer_id=customer.id)

    # GET: unified tabbed Customers view
    return redirect(reverse("edge_customers") + "#create")


@login_required
def customer_detail(request, customer_id):
    ctx = edge_common()
    customer = get_object_or_404(
        Customer.objects.select_related("group__tariff", "wallet").prefetch_related("rates"),
        id=customer_id,
    )
    wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})
    entries = customer.ledger_entries.select_related("session", "created_by").order_by("-created_at")[:80]
    sessions_qs = customer.sessions.select_related("device", "tariff", "customer_rate").order_by("-started_at")
    active = sessions_qs.filter(status=SessionStatus.ACTIVE).first()
    sessions = sessions_qs[:20]
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
    rates = customer.rates.order_by("-is_default", "-is_active", "name")
    edit_rate = None
    edit_id = request.GET.get("edit", "").strip()
    if edit_id:
        edit_rate = rates.filter(id=edit_id).first()
    try:
        _, _, effective_hourly_rate, effective_rate_name = resolve_rate(customer)
    except SessionError:
        effective_hourly_rate, effective_rate_name = None, "نرخ نامعتبر"
    default_hourly_rate = int(ctx["config"].get("default_hourly_rate", 60000))
    operator_label = request.user.label or request.user.username
    catalog_json = build_catalog_json(
        customers=[customer],
        tariffs=tariffs,
        devices=devices,
        default_hourly_rate=default_hourly_rate,
        operator_label=operator_label,
    )
    ctx.update(
        {
            "customer": customer,
            "wallet": wallet,
            "available": wallet.balance + customer.credit_limit,
            "entries": entries,
            "sessions": sessions,
            "active_session": active,
            "devices": devices,
            "tariffs": tariffs,
            "BillingMode": BillingMode,
            "DisconnectPolicy": DisconnectPolicy,
            "default_hourly_rate": default_hourly_rate,
            "operator_label": operator_label,
            "catalog_json": catalog_json,
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

    # استعلام سریع وضعیت از سامانه رهرو با کش هوشمند محلی
    from django.core.cache import cache
    cache_key = f"rahro_status_{customer.id}_{customer.phone}"
    rahro_status = cache.get(cache_key)

    if rahro_status is None and customer.phone:
        try:
            import requests
            from django.conf import settings
            rahro_url = getattr(settings, "RAHRO_API_URL", "https://hammasjedy.ir/rahro/api/gamenet/")
            shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
            r = requests.get(
                f"{rahro_url.rstrip('/')}/status/",
                params={"phone": customer.phone, "username": customer.username},
                headers={"X-Internal-Secret": shared_secret},
                timeout=0.5,
            )
            if r.status_code == 200:
                rahro_status = r.json()
                cache.set(cache_key, rahro_status, timeout=600)  # 10 minutes cache
            else:
                cache.set(cache_key, False, timeout=120)  # avoid repeated slow calls
        except Exception:
            cache.set(cache_key, False, timeout=120)

    if rahro_status and rahro_status.get("found"):
        # تثبیت قطعی گروه کاربری و تعرفه در دیتابیس محلی بر اساس وضعیت تایید شده رهرو
        # تا در صورت قطع اینترنت همواره تعرفه کاربر (کادر ۲۰ک یا لیگ رهرو ۴۰ک) به درستی محاسبه شود
        tier = str(rahro_status.get("pricing_tier") or "")
        target_group_name = None
        if "CADRE" in tier:
            target_group_name = "کادر"
        elif any(k in tier for k in ["STUDENT", "RAHRO", "LEAGUE"]):
            target_group_name = "لیگ رهرو"

        if target_group_name and (not customer.group or customer.group.name != target_group_name):
            matching_group = CustomerGroup.objects.filter(
                edge_id=customer.edge_id, name=target_group_name
            ).first()
            if matching_group:
                customer.group = matching_group
                customer.revision += 1
                customer.save(update_fields=["group", "revision", "updated_at"])
                wallet = getattr(customer, "wallet", None)
                if wallet:
                    try:
                        from apps.synchronization.events import emit
                        from django.db import transaction
                        with transaction.atomic():
                            emit("customer.updated", aggregate_type="customer", aggregate_id=str(customer.id), payload=_payload(customer, wallet))
                    except Exception:
                        pass

    ctx["rahro_status"] = rahro_status

    return render(request, "edge/customer_detail.html", ctx)


@login_required
@require_POST
def customer_rahro_discount(request, customer_id):
    """اعمال کوپن یا تخفیف رهرو برای مشتری در پنل محلی"""
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        discount_percent = int(request.POST.get("discount_percent", 50))
        action_type = (request.POST.get("action_type") or "").strip()
        duration_minutes = int(request.POST.get("duration_minutes") or 60)
        session_id = request.POST.get("session_id")

        import requests
        from django.conf import settings
        from datetime import timedelta
        from django.utils import timezone
        from apps.ledger.models import LedgerEntry, LedgerEntryType
        from apps.wallets.models import Wallet
        from apps.pricing.models import CustomerRate
        from apps.clients.models import ClientDevice

        rahro_url = getattr(settings, "RAHRO_API_URL", "https://hammasjedy.ir/rahro/api/gamenet/")
        shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")

        actor_name = request.user.get_full_name() or request.user.username or "مدیر بازی‌سرای رهرو"
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
        hourly_rate = int(data.get("base_hourly_rate") or (customer.group.tariff.hourly_rate if customer.group and customer.group.tariff else 40000))
        disc_rate_amount = ((hourly_rate * discount_percent) + 50) // 100
        discounted_hourly_rate = max(0, hourly_rate - disc_rate_amount)

        active_session = None
        if session_id:
            active_session = customer.sessions.filter(id=session_id, status=SessionStatus.ACTIVE).first()
        if not active_session:
            active_session = customer.sessions.filter(status=SessionStatus.ACTIVE).first()

        # ۱. تسویه نقدی نشست در حال اجرا
        if (action_type == "settle_active" or (active_session and not action_type)) and active_session:
            elapsed = max(60, int((now - active_session.started_at).total_seconds()))
            dur_mins = max(1, elapsed // 60)
            rate = active_session.hourly_rate or hourly_rate
            from apps.core.money import session_cost
            base_cost = session_cost(rate, elapsed)
            discount_amount = ((base_cost * discount_percent) + 50) // 100
            final_cost = max(0, base_cost - discount_amount)

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
                    created_by=request.user,
                    operator_label=actor_name,
                    is_replica=False,
                )

                wallet.balance += final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=active_session.edge_id,
                    session=active_session,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=final_cost,
                    balance_after=wallet.balance,
                    note=f"پرداخت نقدی/پوز باجه ({final_cost:,} تومان) بابت {voucher_code or 'تخفیف رهرو'}",
                    created_by=request.user,
                    operator_label=actor_name,
                    is_replica=False,
                )
                wallet.save(update_fields=["balance"])

            messages.success(
                request,
                f"نشست متوقف و تسویه شد. مبلغ نصف قیمت ({final_cost:,} تومان) به صورت نقدی در باجه دریافت و ثبت گردید. ({data.get('message', '')})"
            )

        # ۲. ثبت باجه ۱ ساعت بازی و پرداخت نقدی نصف قیمت
        elif action_type == "record_paid_desk" or (not active_session and action_type not in ["auto_charge_rate", "reserve_coupon"]):
            dur_mins = duration_minutes
            dur_secs = dur_mins * 60
            base_cost = (hourly_rate * dur_mins) // 60
            discount_amount = ((base_cost * discount_percent) + 50) // 100
            final_cost = max(0, base_cost - discount_amount)

            device = ClientDevice.objects.filter(edge_id=customer.edge_id, is_active=True).first()
            if not device:
                device = ClientDevice.objects.filter(is_active=True).first()

            sess = GamingSession.objects.create(
                id=uuid.uuid4(),
                edge_id=customer.edge_id,
                customer=customer,
                device=device,
                tariff_name=customer.group.name if customer.group else "آزاد",
                hourly_rate=hourly_rate,
                started_at=now - timedelta(seconds=dur_secs),
                ended_at=now,
                elapsed_seconds=dur_secs,
                cost=final_cost,
                discount_percent=discount_percent,
                discount_amount=discount_amount,
                discount_source=f"رهرو ({voucher_code or 'کوپن'})",
                status=SessionStatus.COMPLETED,
                end_reason=f"ثبت باجه و پرداخت نقدی ۱ ساعت بازی ({final_cost:,} تومان)",
                is_replica=False,
            )

            wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})
            if final_cost > 0:
                wallet.balance -= final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=customer.edge_id,
                    session=sess,
                    entry_type=LedgerEntryType.SESSION_CHARGE,
                    amount=-final_cost,
                    balance_after=wallet.balance,
                    note=f"شارژ نشست باجه ({dur_mins} دقیقه با تخفیف {discount_percent}٪)",
                    created_by=request.user,
                    operator_label=actor_name,
                    is_replica=False,
                )

                wallet.balance += final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=customer.edge_id,
                    session=sess,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=final_cost,
                    balance_after=wallet.balance,
                    note=f"پرداخت نقدی/پوز باجه ({final_cost:,} تومان) بابت {voucher_code or 'تخفیف رهرو'}",
                    created_by=request.user,
                    operator_label=actor_name,
                    is_replica=False,
                )
                wallet.save(update_fields=["balance"])

            # تنظیم نرخ مشتری در سالن
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
                    CustomerRate.objects.create(
                        edge_id=customer.edge_id,
                        customer=customer,
                        name=f"تخفیف کوپن رهرو ({discount_percent}٪)",
                        hourly_rate=discounted_hourly_rate,
                        is_default=True,
                        is_active=True,
                        is_replica=False,
                    )
            elif discount_percent == 100:
                wallet.balance += hourly_rate
                wallet.save(update_fields=["balance"])
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=customer.edge_id,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=hourly_rate,
                    balance_after=wallet.balance,
                    note="شارژ خودکار کیف پول بابت ۱ ساعت بازی رایگان کوپن رهرو (۱۰۰٪)",
                    created_by=request.user,
                    operator_label=actor_name,
                    is_replica=False,
                )

            messages.success(
                request,
                f"بازی {dur_mins} دقیقه‌ای با تخفیف {discount_percent}٪ و پرداخت نقدی {final_cost:,} تومان "
                f"با موفقیت ثبت و تسویه شد. همچنین نرخ ساعتی در کلاینت برای ۱ ساعت روی {discounted_hourly_rate:,} ت شارژ گردید. ({data.get('message', '')})"
            )

        # ۳. شارژ خودکار نرخ ۱ ساعت بازی در کلاینت سالن
        elif action_type == "auto_charge_rate":
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
                    CustomerRate.objects.create(
                        edge_id=customer.edge_id,
                        customer=customer,
                        name=f"تخفیف کوپن رهرو ({discount_percent}٪)",
                        hourly_rate=discounted_hourly_rate,
                        is_default=True,
                        is_active=True,
                        is_replica=False,
                    )
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
                    edge_id=customer.edge_id,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=hourly_rate,
                    balance_after=wallet.balance,
                    note="شارژ خودکار کیف پول بابت ۱ ساعت بازی رایگان کوپن رهرو (۱۰۰٪)",
                    created_by=request.user,
                    operator_label=actor_name,
                    is_replica=False,
                )
                messages.success(
                    request,
                    f"شارژ خودکار ۱ ساعت بازی رایگان (۱۰۰٪) انجام شد: مبلغ {hourly_rate:,} تومان به کیف پول کاربر اضافه گردید. ({data.get('message', '')})"
                )

        # ۴. اعمال روی نشست فعال
        elif action_type == "apply_active" and active_session:
            active_session.discount_percent = discount_percent
            active_session.discount_source = data.get("source", "RAHRO")
            active_session.save(update_fields=["discount_percent", "discount_source", "updated_at"])
            messages.success(request, f"تخفیف {discount_percent}٪ با موفقیت روی نشست جاری {customer.full_name} ثبت شد. ({data.get('message')})")

        # ۵. رزرو کوپن
        else:
            messages.success(request, f"کوپن تخفیف {discount_percent}٪ برای {customer.full_name} در رهرو صادر شد: {data.get('message')}")

    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_rahro_recharge(request, customer_id):
    """شارژ سریع و هوشمند حساب کاربری گیم‌نت در سرور لبه"""
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        raw_amount = str(request.POST.get("amount") or "0").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")).replace(",", "").replace("،", "").strip()
        amount = int(raw_amount or 0)
        use_coupon = (request.POST.get("use_coupon") or "").strip()
        payment_method = (request.POST.get("payment_method") or "pos").strip()
        submitted_tier = str(request.POST.get("tier") or "").strip()

        # تثبیت همیشگی گروه کاربری مشتری در دیتابیس محلی
        target_group_name = None
        if "CADRE" in submitted_tier:
            target_group_name = "کادر"
        elif any(k in submitted_tier for k in ["STUDENT", "RAHRO", "LEAGUE"]):
            target_group_name = "لیگ رهرو"

        if target_group_name and (not customer.group or customer.group.name != target_group_name):
            matching_group = CustomerGroup.objects.filter(
                edge_id=customer.edge_id, name=target_group_name
            ).first()
            if matching_group:
                customer.group = matching_group
                customer.revision += 1
                customer.save(update_fields=["group", "revision", "updated_at"])

        import requests
        from django.conf import settings
        from apps.pricing.models import CustomerRate
        from apps.wallets.models import Wallet
        from apps.wallets.services import deposit

        rahro_url = getattr(settings, "RAHRO_API_URL", "https://hammasjedy.ir/rahro/api/gamenet/")
        shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
        actor_name = request.user.get_full_name() or request.user.username or "مدیر بازی‌سرای رهرو"
        is_debt = request.POST.get("is_debt") in ("1", "true", "on", True)
        if is_debt:
            method_title = "نسیه و بدهی"
        else:
            method_title = "کارتخوان باجه" if payment_method == "pos" else "نقدی"

        applied_coupon_note = ""
        discount_percent = 0
        if use_coupon in ["50", "100"]:
            discount_percent = int(use_coupon)
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
                    timeout=3.5,
                )
                data = resp.json() if resp.status_code == 200 else {}
                if resp.status_code == 200 and data.get("success"):
                    applied_coupon_note = data.get("message") or f"سهمیه {discount_percent}٪ رهرو اعمال شد."
                else:
                    err = data.get("error") or data.get("message") or "عدم پاسخ مناسب از سامانه رهرو"
                    messages.warning(request, f"هشدار سهمیه رهرو: {err}")
            except Exception as e:
                messages.warning(request, f"خطا در ارتباط با رهرو: {str(e)}")

        if discount_percent == 50:
            CustomerRate.objects.filter(customer=customer, is_default=True).update(is_default=False)
            rate_obj = CustomerRate.objects.filter(customer=customer, name__startswith="تخفیف کوپن رهرو").first()
            if rate_obj:
                rate_obj.name = "تخفیف کوپن رهرو (۵۰٪)"
                rate_obj.hourly_rate = 20000
                rate_obj.is_default = True
                rate_obj.is_active = True
                rate_obj.save(update_fields=["name", "hourly_rate", "is_default", "is_active", "updated_at"])
            else:
                CustomerRate.objects.create(
                    edge_id=customer.edge_id,
                    customer=customer,
                    name="تخفیف کوپن رهرو (۵۰٪)",
                    hourly_rate=20000,
                    is_default=True,
                    is_active=True,
                    is_replica=False,
                )

        total_credit = amount
        if discount_percent == 100 and amount == 0:
            total_credit = 40000

        if total_credit > 0:
            note_custom = (request.POST.get("note") or "").strip()[:160]
            note = f"شارژ کیف پول ({total_credit:,} ت - {method_title})"
            if discount_percent == 50:
                note += " [همراه با سهمیه ۵۰٪ رهرو - نرخ کلاینت ۲۰,۰۰۰ ت]"
            elif discount_percent == 100:
                note += " [اعتبار هدیه کوپن ۱۰۰٪ رایگان رهرو]"
            if note_custom:
                note = f"{note} — {note_custom}"[:255]
            entry = deposit(
                customer,
                total_credit,
                actor=request.user,
                is_debt=is_debt,
                note=note,
                operator_label=actor_name,
            )
            msg = (
                f"کیف پول {customer.full_name} با موفقیت به مبلغ {total_credit:,} تومان ({method_title}) شارژ شد. "
                f"موجودی جدید: {entry.balance_after:,} تومان. کد پیگیری: {entry.tracking_code}"
            )
            if applied_coupon_note:
                msg += f" ({applied_coupon_note})"
            messages.success(request, msg)
        else:
            messages.info(request, "هیچ مبلغی برای شارژ وارد نشد.")

    except Exception as exc:
        messages.error(request, f"خطا در شارژ: {str(exc)}")

    return safe_redirect_next(request, "edge_customer_detail", customer_id=customer.id)


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
        return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")
    _audit(
        request, "customer_rate.created", "customer_rate", rate.id,
        {"customer": customer.full_name, "name": rate.name, "rate": rate.hourly_rate},
    )
    messages.success(request, f"نرخ «{rate.name}» ثبت شد.")
    return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


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
        return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")
    _audit(
        request, "customer_rate.updated", "customer_rate", rate.id,
        {"customer": customer.full_name, "name": rate.name, "rate": rate.hourly_rate,
         "active": rate.is_active, "default": rate.is_default},
    )
    messages.success(request, f"نرخ «{rate.name}» به‌روزرسانی شد؛ نشست‌های فعال تغییر نمی‌کنند.")
    return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


@login_required
@require_POST
def customer_rate_default(request, customer_id, rate_id):
    customer = get_object_or_404(Customer, id=customer_id)
    rate = get_object_or_404(CustomerRate, id=rate_id, customer=customer)
    try:
        rate = set_default_customer_rate(rate, actor=request.user)
    except CustomerRateError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")
    _audit(
        request, "customer_rate.default", "customer_rate", rate.id,
        {"customer": customer.full_name, "name": rate.name},
    )
    messages.success(request, f"نرخ «{rate.name}» پیش‌فرض این مشتری شد.")
    return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


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
        return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")
    _audit(
        request, "customer_rate.deactivated", "customer_rate", rate.id,
        {"customer": customer.full_name, "name": rate.name},
    )
    messages.warning(request, f"نرخ «{rate.name}» غیرفعال شد.")
    return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


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
            return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer_id}) + "#profile")
    try:
        persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
        english = "01234567890123456789"
        trans = str.maketrans(persian_arabic, english)

        raw_user = (request.POST.get("username") or "").translate(trans).strip()
        raw_pass = (request.POST.get("password") or "").translate(trans).strip() or None
        raw_phone = (request.POST.get("phone") or "").translate(trans).strip()

        credit_limit = _int(request.POST.get("credit_limit"), default=0)
        max_debt_limit = _int(request.POST.get("max_debt_limit"), default=40000) if "max_debt_limit" in request.POST else None
        expected = request.POST.get("expected_revision")
        is_active_val = None
        if "is_active" in request.POST:
            is_active_val = request.POST.get("is_active") == "1"
        update_customer(
            customer,
            full_name=request.POST.get("full_name", "").strip(),
            username=raw_user,
            password=raw_pass,
            phone=raw_phone,
            group=group,
            clear_group=not bool(group),
            credit_limit=credit_limit,
            max_debt_limit=max_debt_limit,
            notes=request.POST.get("notes", ""),
            is_active=is_active_val,
            expected_revision=_int(expected, default=None) if expected else None,
            actor=request.user,
        )
    except (CustomerError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}))
    except Exception as exc:
        logger.exception("Unexpected error updating customer %s: %s", customer_id, exc)
        messages.error(request, f"خطا در ثبت اطلاعات مشتری: {exc}")
        return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}))
    _audit(request, "customer.updated", "customer", customer.id)
    messages.success(request, "اطلاعات مشتری ذخیره شد.")
    return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}))


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
        return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")
    _audit(request, "customer.toggled", "customer", customer.id, {"active": customer.is_active})
    messages.warning(
        request, f"وضعیت مشتری {customer.full_name} به {'فعال' if customer.is_active else 'غیرفعال'} تغییر کرد."
    )
    return redirect(reverse("edge_customer_detail", kwargs={"customer_id": customer.id}) + "#profile")


@login_required
@require_POST
def customer_deposit(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        actor_label = (
            getattr(request.user, "label", "")
            or request.user.get_full_name()
            or request.user.get_username()
        )
        is_debt = request.POST.get("is_debt") in ("1", "true", "on", True)
        entry = deposit(
            customer,
            _int(request.POST.get("amount")),
            actor=request.user,
            is_debt=is_debt,
            note=request.POST.get("note", "")[:255],
            operator_label=actor_label,
        )
    except (WalletError, ValueError) as exc:
        messages.error(request, str(exc))
        return safe_redirect_next(request, "edge_customer_detail", customer_id=customer.id)
    _audit(
        request,
        "wallet.deposit",
        "ledger_entry",
        entry.id,
        {"amount": entry.amount, "is_debt": is_debt, "tracking_code": entry.tracking_code},
    )
    title = "به صورت بدهی (نسیه)" if is_debt else ""
    messages.success(
        request,
        f"{entry.amount:,} تومان {title} به کیف پول {customer.full_name} شارژ شد. "
        f"موجودی پس از شارژ: {entry.balance_after:,} تومان · کد پیگیری: {entry.tracking_code}",
    )
    return safe_redirect_next(request, "edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_settle_debt(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    raw_amount = request.POST.get("amount")
    amount = _int(raw_amount) if raw_amount else None
    actor_label = (
        getattr(request.user, "label", "")
        or request.user.get_full_name()
        or request.user.get_username()
    )
    note = (request.POST.get("note") or "").strip()[:255]
    try:
        from apps.wallets.services import settle_debt
        paid, entry = settle_debt(
            customer,
            amount=amount,
            actor=request.user,
            note=note,
            operator_label=actor_label,
        )
        customer.refresh_from_db()
        messages.success(
            request,
            f"مبلغ {paid:,} تومان بدهی مشتری «{customer.full_name}» با موفقیت تسویه شد. "
            f"بدهی باقیمانده: {customer.debt_balance:,} تومان · کد پیگیری: {entry.tracking_code}"
        )
    except (WalletError, ValueError) as exc:
        messages.error(request, f"خطا در تسویه بدهی: {str(exc)}")
    return safe_redirect_next(request, "edge_customer_detail", customer_id=customer.id)


@login_required
@require_POST
def customer_adjust(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    try:
        actor_label = (
            getattr(request.user, "label", "")
            or request.user.get_full_name()
            or request.user.get_username()
        )
        entry = adjust(
            customer,
            _int(request.POST.get("amount")),
            actor=request.user,
            note=request.POST.get("note", "")[:255],
            operator_label=actor_label,
        )
    except (WalletError, ValueError) as exc:
        messages.error(request, str(exc))
        return safe_redirect_next(request, "edge_customer_detail", customer_id=customer.id)
    _audit(
        request,
        "wallet.adjust",
        "ledger_entry",
        entry.id,
        {"amount": entry.amount, "tracking_code": entry.tracking_code},
    )
    messages.success(
        request,
        f"اصلاح {entry.amount:,} تومان ثبت شد. موجودی پس از ثبت: {entry.balance_after:,} تومان · کد پیگیری: {entry.tracking_code}",
    )
    return safe_redirect_next(request, "edge_customer_detail", customer_id=customer.id)


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

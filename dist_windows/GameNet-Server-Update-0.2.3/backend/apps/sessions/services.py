"""Session start/stop. The edge is the only writer of play time and charges.

Lock order is deliberate: session row (stop only) -> customer row -> customer
advisory lock -> wallet row -> device row. A concurrent start for the same
customer therefore waits and re-reads the committed balance and active-session
exposure before it can pass the credit check.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.clients.models import (
    ClientDevice,
    ClientStatus,
    ConnectionStatus,
    KioskStatus,
    OccupancyStatus,
)
from apps.core.locks import customer_lock
from apps.core.money import session_cost
from apps.core.roles import require_edge
from apps.customers.models import Customer
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.pricing.models import CustomerRate, Tariff
from apps.sessions.models import (
    BillingMode,
    DisconnectPolicy,
    GamingSession,
    SessionStatus,
)
from apps.synchronization.command_service import queue_device_command
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.events import emit
from apps.wallets.models import Wallet
from apps.wallets.services import post_entry


class SessionError(ValueError):
    pass


STARTABLE_DEVICE_STATES = {ClientStatus.ONLINE, ClientStatus.LOCKED, ClientStatus.IDLE}


def resolve_rate(
    customer: Customer,
    customer_rate: CustomerRate | None = None,
    tariff: Tariff | None = None,
    device: ClientDevice | None = None,
):
    """Return (tariff, customer_rate, hourly_rate, rate_name) for a new session.

    Priority:
    1. explicitly selected personal CustomerRate
    2. explicitly selected Tariff
    3. customer's default personal rate
    4. customer group's tariff
    5. device's default tariff (metadata.default_tariff_id)
    6. global config default rate
    """
    if customer_rate is not None:
        if customer_rate.customer_id != customer.id:
            raise SessionError("نرخ انتخاب‌شده به این مشتری تعلق ندارد.")
        if not customer_rate.is_active:
            raise SessionError("نرخ انتخاب‌شده غیرفعال است.")
        if customer_rate.hourly_rate <= 0:
            raise SessionError("نرخ انتخاب‌شده نامعتبر است.")
        return None, customer_rate, customer_rate.hourly_rate, customer_rate.name

    if tariff is not None:
        if tariff.edge_id != customer.edge_id:
            raise SessionError("تعرفه انتخاب‌شده به این سرور سالن تعلق ندارد.")
        if not tariff.is_active:
            raise SessionError("تعرفه انتخاب‌شده غیرفعال است.")
        if tariff.hourly_rate <= 0:
            raise SessionError("نرخ تعرفه نامعتبر است.")
        return tariff, None, tariff.hourly_rate, tariff.name

    personal = CustomerRate.objects.filter(
        customer=customer, is_active=True, is_default=True
    ).first()
    if personal is not None:
        if personal.hourly_rate <= 0:
            raise SessionError("نرخ پیش‌فرض مشتری نامعتبر است.")
        return None, personal, personal.hourly_rate, personal.name

    group = customer.group
    if group is not None and not group.is_active:
        raise SessionError("گروه مشتری غیرفعال است.")
    group_tariff = group.tariff if group is not None else None
    if group_tariff is not None:
        if not group_tariff.is_active:
            raise SessionError("تعرفه گروه غیرفعال است.")
        if group_tariff.hourly_rate <= 0:
            raise SessionError("نرخ تعرفه نامعتبر است.")
        return group_tariff, None, group_tariff.hourly_rate, group_tariff.name

    if device is not None:
        default_tid = str((device.metadata or {}).get("default_tariff_id") or "").strip()
        if default_tid:
            dev_tariff = Tariff.objects.filter(
                id=default_tid, edge_id=customer.edge_id, is_active=True
            ).first()
            if dev_tariff is not None and dev_tariff.hourly_rate > 0:
                return dev_tariff, None, dev_tariff.hourly_rate, dev_tariff.name

    default_t = Tariff.objects.filter(name="آزاد", is_active=True).first()
    if default_t is not None and default_t.hourly_rate > 0:
        return default_t, None, default_t.hourly_rate, default_t.name

    rate = int(current_config().get("default_hourly_rate", settings.DEFAULT_HOURLY_RATE))
    if rate <= 0:
        raise SessionError("نرخ پیش‌فرض نامعتبر است.")
    return None, None, rate, "آزاد"


def _session_payload(session: GamingSession) -> dict:
    return {
        "session_id": str(session.id),
        "customer_id": str(session.customer_id),
        "device_id": str(session.device_id),
        "tariff_id": str(session.tariff_id) if session.tariff_id else None,
        "customer_rate_id": (
            str(session.customer_rate_id) if session.customer_rate_id else None
        ),
        "tariff_name": session.tariff_name,
        "hourly_rate": session.hourly_rate,
        "coupon_hours": getattr(session, "coupon_hours", 0),
        "coupon_hourly_rate": getattr(session, "coupon_hourly_rate", 20000),
        "billing_mode": session.billing_mode,
        "planned_duration_minutes": session.planned_duration_minutes,
        "estimated_cost": session.estimated_cost,
        "disconnect_policy": session.disconnect_policy,
        "paused_seconds": int(session.paused_seconds or 0),
        "started_at": session.started_at.isoformat(),
    }


@transaction.atomic
def start_session(
    customer: Customer,
    device: ClientDevice,
    *,
    customer_rate: CustomerRate | None = None,
    tariff: Tariff | None = None,
    billing_mode: str = BillingMode.CREDIT,
    planned_duration_minutes: int | None = None,
    disconnect_policy: str = DisconnectPolicy.PAUSE,
    session_id=None,
    actor=None,
) -> GamingSession:
    require_edge()
    identity = ensure_identity()
    now = timezone.now()

    clean_mode = (billing_mode or BillingMode.CREDIT).strip().upper()
    if clean_mode not in BillingMode.values:
        raise SessionError("نوع محاسبه نشست نامعتبر است.")

    clean_policy = (disconnect_policy or DisconnectPolicy.PAUSE).strip().upper()
    if clean_policy not in DisconnectPolicy.values:
        raise SessionError("سیاست قطع ارتباط نشست نامعتبر است.")

    duration_mins: int | None = None
    if planned_duration_minutes not in (None, ""):
        try:
            duration_mins = int(planned_duration_minutes)
        except (TypeError, ValueError) as exc:
            raise SessionError("مدت زمان انتخاب‌شده نامعتبر است.") from exc
        if duration_mins < 5 or duration_mins > 1440:
            raise SessionError("مدت زمان نشست باید بین ۵ تا ۱۴۴۰ دقیقه باشد.")
    elif clean_mode == BillingMode.TIMED:
        raise SessionError("در حالت محاسبه زمانی، انتخاب مدت زمان الزامی است.")

    # A retried remote-start command carries a cloud-generated session id. The
    # session status and this lookup make the command idempotent.
    if session_id is not None:
        existing = GamingSession.objects.filter(id=session_id).first()
        if existing is not None:
            if (
                existing.edge_id != identity.edge_id
                or existing.customer_id != customer.id
                or existing.device_id != device.id
            ):
                raise SessionError("شناسه نشست با مشتری یا دستگاه مطابقت ندارد.")
            return existing

    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if not customer.is_active:
        raise SessionError("مشتری غیرفعال است.")
    if customer.edge_id != identity.edge_id:
        raise SessionError("مشتری به این Edge تعلق ندارد.")

    customer_lock(customer.id)
    wallet = Wallet.objects.select_for_update().filter(customer=customer).first()
    if wallet is None:
        wallet = Wallet.objects.create(customer=customer, balance=0)

    device = ClientDevice.objects.select_for_update().get(pk=device.pk)
    if not device.is_active:
        raise SessionError("دستگاه غیرفعال است.")
    if device.edge_id != identity.edge_id:
        raise SessionError("دستگاه به این Edge تعلق ندارد.")
    if (
        device.occupancy_status == OccupancyStatus.MAINTENANCE
        or device.status == ClientStatus.MAINTENANCE
    ):
        raise SessionError("دستگاه در حالت تعمیرات است و آماده شروع نشست نیست.")
    if (
        device.occupancy_status == OccupancyStatus.BUSY
        or GamingSession.objects.filter(device=device, status=SessionStatus.ACTIVE).exists()
    ):
        raise SessionError("این دستگاه در یک نشست فعال است.")
    if (
        device.connection_status != ConnectionStatus.ONLINE
        and device.status not in STARTABLE_DEVICE_STATES
    ):
        raise SessionError("کلاینت دستگاه به سرور متصل (آنلاین) نیست و امکان باز کردن آن وجود ندارد.")

    if customer_rate is not None:
        customer_rate = CustomerRate.objects.get(pk=customer_rate.pk)
    if tariff is not None:
        tariff = Tariff.objects.get(pk=tariff.pk)

    tariff_obj, rate_obj, hourly_rate, tariff_name = resolve_rate(
        customer, customer_rate=customer_rate, tariff=tariff, device=device
    )

    # بررسی و اعمال هوشمند کوپن تخفیف ۵۰٪ برای اعضای لیگ رهرو (سهمیه ماهانه یا کوپن‌های امتیازی)
    is_league = (
        (customer.group and "لیگ" in customer.group.name)
        or "لیگ" in tariff_name
        or hourly_rate == 40000
    )
    coupon_hours = 0
    coupon_hourly_rate = 20000
    coupon_message = ""

    coupons_available = getattr(customer, "active_coupons", 0) or 0
    if is_league and customer.phone:
        try:
            import requests
            from django.core.cache import cache
            cache_key = f"rahro_status_{customer.id}_{customer.phone}"
            cached_status = cache.get(cache_key)
            if cached_status is None:
                rahro_url = getattr(settings, "RAHRO_API_URL", "https://hammasjedy.ir/rahro/api/gamenet/")
                shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
                r = requests.get(
                    f"{rahro_url.rstrip('/')}/status/",
                    params={"phone": customer.phone, "username": customer.username},
                    headers={"X-Internal-Secret": shared_secret},
                    timeout=0.6,
                )
                if r.status_code == 200:
                    cached_status = r.json()
                    cache.set(cache_key, cached_status, timeout=300)
            if cached_status and cached_status.get("found"):
                r_coupons = int(cached_status.get("total_coupons") or cached_status.get("remaining_monthly_quotas") or 0)
                if r_coupons != customer.active_coupons:
                    customer.active_coupons = r_coupons
                    customer.save(update_fields=["active_coupons", "updated_at"])
                coupons_available = r_coupons
        except Exception:
            pass

    if is_league and coupons_available > 0:
        coupon_hours = coupons_available
        coupon_hourly_rate = 20000
        coupon_message = (
            f"🎁 شما دارای {coupon_hours} کوپن تخفیف ۵۰٪ رهرو هستید؛ "
            f"تا {coupon_hours} ساعت با تعرفه ویژه ۲۰,۰۰۰ تومان در ساعت محاسبه می‌شوید."
        )

    effective_start_rate = coupon_hourly_rate if coupon_hours > 0 else hourly_rate
    if clean_mode == BillingMode.TIMED and duration_mins:
        estimated_cost = session_cost(hourly_rate, duration_mins * 60)
        required_balance = max(1, estimated_cost)
    else:
        estimated_cost = effective_start_rate
        required_balance = max(1000, effective_start_rate // 4) if effective_start_rate >= 4000 else effective_start_rate

    # Reserve the accrued cost of every live session so concurrent starts stay within balance.
    reserved = 0
    for s in GamingSession.objects.filter(customer=customer, status=SessionStatus.ACTIVE):
        elapsed = s.billable_elapsed_seconds(now)
        reserved += max(s.hourly_rate, session_cost(s.hourly_rate, elapsed))
    available = (wallet.balance if wallet else 0) - reserved

    # Strict rule: Cannot start session with zero or negative balance, or with unpaid debt after balance exhaustion
    if getattr(customer, "debt_balance", 0) > 0 and available <= 0:
        raise SessionError(
            f"مشتری «{customer.full_name}» دارای {customer.debt_balance:,} تومان بدهی پرداخت‌نشده است و موجودی کیف‌پول به پایان رسیده. "
            f"برای باز کردن سیستم یا شروع نشست جدید، ابتدا باید بدهی قبلی تسویه شود."
        )

    if available <= 0 or available < required_balance:
        raise SessionError(
            f"موجودی کیف‌پول کاربر «{customer.full_name}» برای شروع بازی کافی نیست (موجودی فعلی: {max(0, available):,} تومان؛ حداقل اعتبار مورد نیاز: {required_balance:,} تومان). "
            f"امکان باز کردن سیستم بدون داشتن اعتبار وجود ندارد."
        )

    session = GamingSession.objects.create(
        id=session_id,
        edge_id=identity.edge_id,
        customer=customer,
        device=device,
        status=SessionStatus.ACTIVE,
        tariff=tariff_obj,
        customer_rate=rate_obj,
        tariff_name=tariff_name,
        hourly_rate=hourly_rate,
        coupon_hours=coupon_hours,
        coupon_hourly_rate=coupon_hourly_rate,
        discount_source=f"{coupon_hours} کوپن ۵۰٪ رهرو" if coupon_hours > 0 else "",
        billing_mode=clean_mode,
        planned_duration_minutes=duration_mins if clean_mode == BillingMode.TIMED else None,
        estimated_cost=estimated_cost,
        disconnect_policy=clean_policy,
        started_at=now,
        started_by=actor if getattr(actor, "pk", None) else None,
    )

    from apps.devices.services import set_status

    wallet_balance = wallet.balance if wallet else 0

    set_status(
        device,
        ClientStatus.STARTING,
        force=True,
        connection_status=ConnectionStatus.ONLINE,
        kiosk_status=KioskStatus.UNLOCKED,
        occupancy_status=OccupancyStatus.BUSY,
        reason="session started",
    )
    queue_device_command(
        device,
        "client.unlock",
        {
            "session_id": str(session.id),
            "customer_id": str(customer.id),
            "customer_name": customer.full_name,
            "username": customer.username or customer.phone,
            "wallet_balance": wallet_balance,
            "credit_limit": 0,
            "hourly_rate": hourly_rate,
            "rate_name": tariff_name,
            "coupon_hours": coupon_hours,
            "coupon_hourly_rate": coupon_hourly_rate,
            "has_coupon": coupon_hours > 0,
            "coupon_message": coupon_message,
            "billing_mode": session.billing_mode,
            "planned_duration_minutes": session.planned_duration_minutes,
            "estimated_cost": session.estimated_cost,
            "disconnect_policy": session.disconnect_policy,
            "started_at": session.started_at.isoformat(),
        },
        actor=actor,
    )
    emit(
        "session.started",
        aggregate_type="session",
        aggregate_id=str(session.id),
        payload=_session_payload(session),
    )
    return session


@transaction.atomic
def stop_session(
    session: GamingSession, *, actor=None, reason: str = "پایان دستی", keep_processes: bool = False
) -> tuple[GamingSession, LedgerEntry | None]:
    """Finish a session and charge actual elapsed time exactly once.

    Safe to call twice: a non-ACTIVE session is not charged again, and the
    ledger's unique (session, entry_type) constraint is the database backstop.
    """
    require_edge()
    session = GamingSession.objects.select_for_update().select_related(
        "customer", "device"
    ).get(pk=session.pk)

    if session.status != SessionStatus.ACTIVE:
        entry = LedgerEntry.objects.filter(
            session=session, entry_type=LedgerEntryType.SESSION_CHARGE
        ).first()
        return session, entry

    now = timezone.now()
    if session.paused_at is not None:
        session.paused_seconds = int(session.paused_seconds or 0) + max(
            0, int((now - session.paused_at).total_seconds())
        )
        session.paused_at = None
    session.connection_lost_at = None

    elapsed = session.billable_elapsed_seconds(now)
    cost, discount_amount = session.calculate_cost(elapsed)
    base_cost = cost + discount_amount

    # بررسی و کسر کوپن‌های مصرف‌شده در این نشست
    used_coupons = 0
    if session.coupon_hours > 0 and elapsed >= 60:
        used_coupons = min(session.coupon_hours, max(1, (elapsed + 3599) // 3600))
        if used_coupons > 0:
            cust = session.customer
            cust.active_coupons = max(0, cust.active_coupons - used_coupons)
            cust.save(update_fields=["active_coupons", "updated_at"])
            session.discount_source = f"مصرف {used_coupons} کوپن ۵۰٪ رهرو"

    entry = LedgerEntry.objects.filter(
        session=session, entry_type=LedgerEntryType.SESSION_CHARGE
    ).first()
    if entry is None and cost > 0:
        note_text = f"شارژ نشست {str(session.id)[:8]}"
        if session.coupon_hours > 0:
            note_text += f" (تخفیف کوپن رهرو: {used_coupons} ساعت با نرخ ۲۰,۰۰۰ ت)"
        elif session.discount_percent > 0:
            note_text += f" (تخفیف {session.discount_percent}٪)"
        entry = post_entry(
            customer=session.customer,
            amount=-cost,
            entry_type=LedgerEntryType.SESSION_CHARGE,
            session=session,
            note=note_text,
            actor=actor,
            allow_over_limit=True,
        )

    session.status = SessionStatus.COMPLETED
    session.ended_at = now
    session.elapsed_seconds = elapsed
    session.cost = cost
    session.discount_amount = discount_amount
    if session.coupon_hours > 0 and not session.discount_percent:
        session.discount_percent = 50
    session.ended_by = actor if getattr(actor, "pk", None) else None
    session.end_reason = (reason or "")[:120]
    session.save(
        update_fields=[
            "status", "ended_at", "elapsed_seconds", "cost", "discount_amount",
            "discount_percent", "discount_source",
            "ended_by", "end_reason", "paused_at", "paused_seconds",
            "connection_lost_at", "updated_at",
        ]
    )

    # اطلاع به سامانه رهرو جهت ثبت دقایق بازی در پنل دانش‌آموز و مصرف کوپن‌ها
    try:
        import requests
        from django.conf import settings
        rahro_url = getattr(settings, "RAHRO_API_URL", "https://hammasjedy.ir/rahro/api/gamenet/")
        shared_secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
        payload = {
            "session_id": str(session.id),
            "phone": session.customer.phone,
            "username": session.customer.username,
            "device_name": session.device.name if session.device else "",
            "started_at": session.started_at.isoformat(),
            "ended_at": now.isoformat(),
            "duration_seconds": elapsed,
            "hourly_rate": session.hourly_rate,
            "base_cost": base_cost,
            "discount_percent": session.discount_percent,
            "discount_amount": discount_amount,
            "final_cost": cost,
            "discount_source": session.discount_source,
            "coupons_used": used_coupons,
            "coupon_hours_used": used_coupons,
        }
        requests.post(
            f"{rahro_url.rstrip('/')}/record-session/",
            json=payload,
            headers={"X-Internal-Secret": shared_secret, "Content-Type": "application/json"},
            timeout=3,
        )
    except Exception as exc:
        import logging
        logging.getLogger("gamenet.sessions").warning(f"Failed to notify Rahro of session {session.id}: {exc}")

    from apps.devices.services import set_status

    is_connected = session.device.connection_status == ConnectionStatus.ONLINE
    set_status(
        session.device,
        ClientStatus.STOPPING if is_connected else ClientStatus.OFFLINE,
        force=True,
        connection_status=ConnectionStatus.ONLINE if is_connected else ConnectionStatus.OFFLINE,
        kiosk_status=KioskStatus.LOCKED,
        occupancy_status=OccupancyStatus.FREE,
        bump_heartbeat=is_connected,
        reason="session ended",
    )
    queue_device_command(
        session.device,
        "client.lock",
        {
            "session_id": str(session.id),
            "cost": cost,
            "elapsed_seconds": elapsed,
            "keep_processes": keep_processes,
            "close_games": not keep_processes,
            "reason": reason,
        },
        actor=actor,
    )
    emit(
        "session.ended",
        aggregate_type="session",
        aggregate_id=str(session.id),
        payload={
            "session_id": str(session.id),
            "status": session.status,
            "ended_at": session.ended_at.isoformat(),
            "elapsed_seconds": elapsed,
            "paused_seconds": int(session.paused_seconds or 0),
            "cost": cost,
            "discount_percent": session.discount_percent,
            "discount_amount": session.discount_amount,
            "discount_source": session.discount_source,
            "end_reason": session.end_reason,
            "ledger_entry_id": str(entry.id) if entry is not None else None,
        },
    )
    return session, entry


def enforce_active_session_policies(now=None) -> int:
    """Enforce TIMED expirations, disconnect policies (AUTO_STOP / PAUSE), and wallet caps."""
    from apps.devices.services import handle_device_disconnect

    require_edge()
    now = now or timezone.now()
    handled = 0
    active_sessions = list(
        GamingSession.objects.filter(status=SessionStatus.ACTIVE).select_related(
            "customer", "customer__wallet", "device"
        )
    )
    for session in active_sessions:
        dev = session.device
        if dev.connection_status == ConnectionStatus.OFFLINE:
            if session.connection_lost_at is None or (
                session.disconnect_policy == DisconnectPolicy.PAUSE and session.paused_at is None
            ):
                with transaction.atomic():
                    handle_device_disconnect(dev, now=now)
                session.refresh_from_db()

            if (
                session.disconnect_policy == DisconnectPolicy.AUTO_STOP
                and session.connection_lost_at is not None
                and (now - session.connection_lost_at).total_seconds() >= 60
            ):
                stop_session(session, reason="توقف خودکار پس از قطع ارتباط دستگاه")
                handled += 1
                continue

        elapsed = session.billable_elapsed_seconds(now)
        if (
            session.billing_mode == BillingMode.TIMED
            and session.planned_duration_minutes
            and elapsed >= session.planned_duration_minutes * 60
        ):
            stop_session(session, reason="پایان مدت زمان انتخاب‌شده نشست", keep_processes=False)
            handled += 1
            continue

        wallet = getattr(session.customer, "wallet", None)
        balance = wallet.balance if wallet else 0
        cost = session_cost(session.hourly_rate, elapsed)
        if session.paused_at is None and (balance - cost) <= 0:
            stop_session(session, reason="اتمام خودکار موجودی کیف‌پول (بدهی مجاز نیست)", keep_processes=False)
            handled += 1

    return handled

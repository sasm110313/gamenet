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

from apps.clients.models import ClientDevice, ClientStatus
from apps.core.locks import customer_lock
from apps.core.money import session_cost
from apps.core.roles import require_edge
from apps.customers.models import Customer
from apps.ledger.models import LedgerEntry, LedgerEntryType
from apps.pricing.models import CustomerRate
from apps.sessions.models import GamingSession, SessionStatus
from apps.synchronization.command_service import queue_device_command
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity
from apps.synchronization.events import emit
from apps.wallets.models import Wallet
from apps.wallets.services import post_entry


class SessionError(ValueError):
    pass


STARTABLE_DEVICE_STATES = {ClientStatus.ONLINE, ClientStatus.LOCKED, ClientStatus.IDLE}


def resolve_rate(customer: Customer, customer_rate: CustomerRate | None = None):
    """Return (tariff, customer_rate, hourly_rate, rate_name) for a new session.

    Priority: explicitly selected personal rate -> customer's default personal
    rate -> group tariff -> global default.
    """
    if customer_rate is not None:
        if customer_rate.customer_id != customer.id:
            raise SessionError("نرخ انتخاب‌شده به این مشتری تعلق ندارد.")
        if not customer_rate.is_active:
            raise SessionError("نرخ انتخاب‌شده غیرفعال است.")
        if customer_rate.hourly_rate <= 0:
            raise SessionError("نرخ انتخاب‌شده نامعتبر است.")
        return None, customer_rate, customer_rate.hourly_rate, customer_rate.name

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
    tariff = group.tariff if group is not None else None
    if tariff is not None:
        if not tariff.is_active:
            raise SessionError("تعرفه گروه غیرفعال است.")
        if tariff.hourly_rate <= 0:
            raise SessionError("نرخ تعرفه نامعتبر است.")
        return tariff, None, tariff.hourly_rate, tariff.name
    rate = int(current_config().get("default_hourly_rate", settings.DEFAULT_HOURLY_RATE))
    if rate <= 0:
        raise SessionError("نرخ پیش‌فرض نامعتبر است.")
    return None, None, rate, "تعرفه پیش‌فرض"


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
        "started_at": session.started_at.isoformat(),
    }


@transaction.atomic
def start_session(
    customer: Customer,
    device: ClientDevice,
    *,
    customer_rate: CustomerRate | None = None,
    session_id=None,
    actor=None,
) -> GamingSession:
    require_edge()
    identity = ensure_identity()
    now = timezone.now()

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
    if device.status not in STARTABLE_DEVICE_STATES:
        raise SessionError(f"دستگاه در وضعیت قابل شروع نیست ({device.status}).")

    if GamingSession.objects.filter(device=device, status=SessionStatus.ACTIVE).exists():
        raise SessionError("این دستگاه در یک نشست فعال است.")

    if customer_rate is not None:
        customer_rate = CustomerRate.objects.get(pk=customer_rate.pk)

    tariff, customer_rate, hourly_rate, tariff_name = resolve_rate(
        customer, customer_rate
    )

    # Reserve the accrued cost of every live session, not just one hour. A long
    # running session can already be over the limit; a second start must not
    # increase that exposure.
    reserved = 0
    for active_rate, started_at in GamingSession.objects.filter(
        customer=customer, status=SessionStatus.ACTIVE
    ).values_list("hourly_rate", "started_at"):
        elapsed = max(0, int((now - started_at).total_seconds()))
        reserved += max(active_rate, session_cost(active_rate, elapsed))
    available = wallet.balance + customer.credit_limit - reserved
    if available < hourly_rate:
        raise SessionError(
            "موجودی و سقف اعتبار برای شروع یک ساعت بازی کافی نیست."
        )

    session = GamingSession.objects.create(
        id=session_id,
        edge_id=identity.edge_id,
        customer=customer,
        device=device,
        status=SessionStatus.ACTIVE,
        tariff=tariff,
        customer_rate=customer_rate,
        tariff_name=tariff_name,
        hourly_rate=hourly_rate,
        started_at=now,
        started_by=actor if getattr(actor, "pk", None) else None,
    )

    from apps.devices.services import set_status

    wallet_balance = wallet.balance if wallet else 0

    set_status(device, ClientStatus.STARTING, force=True, reason="session started")
    queue_device_command(
        device,
        "client.unlock",
        {
            "session_id": str(session.id),
            "customer_id": str(customer.id),
            "customer_name": customer.full_name,
            "username": customer.username or customer.phone,
            "wallet_balance": wallet_balance,
            "credit_limit": customer.credit_limit,
            "hourly_rate": hourly_rate,
            "rate_name": tariff_name,
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
    session: GamingSession, *, actor=None, reason: str = "پایان دستی"
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
    elapsed = max(0, int((now - session.started_at).total_seconds()))
    base_cost = session_cost(session.hourly_rate, elapsed)

    if session.discount_percent > 0:
        discount_amount = (base_cost * session.discount_percent + 50) // 100
        cost = max(0, base_cost - discount_amount)
    else:
        discount_amount = 0
        cost = base_cost

    entry = LedgerEntry.objects.filter(
        session=session, entry_type=LedgerEntryType.SESSION_CHARGE
    ).first()
    if entry is None and cost > 0:
        note_text = f"شارژ نشست {str(session.id)[:8]}"
        if session.discount_percent > 0:
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
    session.ended_by = actor if getattr(actor, "pk", None) else None
    session.end_reason = (reason or "")[:120]
    session.save(
        update_fields=[
            "status", "ended_at", "elapsed_seconds", "cost", "discount_amount",
            "ended_by", "end_reason", "updated_at",
        ]
    )

    # اطلاع به سامانه رهرو جهت ثبت دقایق بازی در پنل دانش‌آموز
    try:
        import requests
        from django.conf import settings
        rahro_url = getattr(settings, "RAHRO_API_URL", "http://127.0.0.1:8000/rahro/api/gamenet/")
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

    set_status(session.device, ClientStatus.STOPPING, force=True, reason="session ended")
    queue_device_command(
        session.device,
        "client.lock",
        {
            "session_id": str(session.id),
            "cost": cost,
            "elapsed_seconds": elapsed,
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
            "cost": cost,
            "discount_percent": session.discount_percent,
            "discount_amount": session.discount_amount,
            "discount_source": session.discount_source,
            "end_reason": session.end_reason,
            "ledger_entry_id": str(entry.id) if entry is not None else None,
        },
    )
    return session, entry

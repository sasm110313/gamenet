"""LAN API served by the edge to Windows clients."""

from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ConnectionStatus, HealthStatus, KioskStatus, PowerStatus
from apps.commands.models import DeviceCommand, DeviceCommandStatus
from apps.core.api import ApiError, AuthenticationFailed
from apps.core.auth import authenticate_device_header, client_ip
from apps.core.roles import require_edge
from apps.devices.services import (
    RegistrationError,
    device_snapshot,
    register_device,
    set_status,
)
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity

logger = logging.getLogger("gamenet.deviceapi")


def device_or_401(request) -> ClientDevice:
    device = authenticate_device_header(request.headers.get("Authorization", ""))
    if device is None:
        raise AuthenticationFailed("invalid device credentials")
    return device


def _hub_config() -> dict:
    cfg = current_config()
    identity = ensure_identity()
    return {
        "hub_name": identity.name,
        "device_heartbeat_seconds": int(cfg["device_heartbeat_seconds"]),
        "device_offline_after_missed": int(cfg["device_offline_after_missed"]),
        "config_version": int(cfg["version"]),
        "cloud_registered": bool(identity.command_public_key),
    }


class DeviceRegisterView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "registration"

    def post(self, request):
        require_edge()
        data = request.data
        try:
            device, token = register_device(
                code=str(data.get("code", "")),
                name=str(data.get("name", "")).strip(),
                hostname=str(data.get("hostname", "")),
                operating_system=str(data.get("operating_system", "")),
                application_version=str(data.get("application_version", "")),
                ip_address=client_ip(request),
                mac_address=str(data.get("mac_address", "")).strip(),
                device_id=data.get("device_id") or None,
            )
        except RegistrationError as exc:
            raise ApiError("registration_failed", str(exc), status.HTTP_400_BAD_REQUEST) from exc

        cfg = _hub_config()
        return Response(
            {
                "device_id": str(device.id),
                "token": token,
                "name": device.name,
                "ws_path": "/ws/device/",
                **cfg,
                "server_time": timezone.now().isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


def _clean_enum(value, enum_cls):
    if value is None:
        return None
    text = str(value).strip().upper()
    return text if text in enum_cls.values else None


class DeviceHeartbeatView(APIView):
    def post(self, request):
        require_edge()
        device = device_or_401(request)
        state = request.data.get("state")
        set_status(
            device,
            state if isinstance(state, str) else None,
            force=False,
            app_version=str(request.data.get("app_version", "")),
            ip_address=client_ip(request),
            mac_address=str(request.data.get("mac_address", "")).strip(),
            connection_status=ConnectionStatus.ONLINE,
            power_status=_clean_enum(request.data.get("power_state"), PowerStatus) or PowerStatus.ON,
            kiosk_status=_clean_enum(request.data.get("kiosk_state"), KioskStatus),
            health_status=_clean_enum(request.data.get("health_status"), HealthStatus),
            health_message=request.data.get("health_message"),
            reason="rest heartbeat",
        )
        device.refresh_from_db(
            fields=[
                "status",
                "connection_status",
                "power_status",
                "kiosk_status",
                "occupancy_status",
                "health_status",
            ]
        )
        cfg = _hub_config()
        return Response(
            {
                "server_time": timezone.now().isoformat(),
                "desired_state": device.status,
                "connection_status": device.connection_status,
                "power_status": device.power_status,
                "kiosk_status": device.kiosk_status,
                "occupancy_status": device.occupancy_status,
                "health_status": device.health_status,
                **cfg,
            }
        )


class DeviceMeView(APIView):
    def get(self, request):
        require_edge()
        device = device_or_401(request)
        return Response(
            {
                "device": device_snapshot(device),
                **_hub_config(),
                "server_time": timezone.now().isoformat(),
            }
        )


class DeviceCommandsPendingView(APIView):
    def get(self, request):
        require_edge()
        device = device_or_401(request)
        now = timezone.now()
        commands = DeviceCommand.objects.filter(
            client=device, status=DeviceCommandStatus.PENDING, expires_at__gt=now
        ).order_by("issued_at")[:20]
        return Response(
            {
                "commands": [
                    {
                        "command_id": str(cmd.id),
                        "command_type": cmd.command_type,
                        "payload": cmd.payload,
                        "expires_at": cmd.expires_at.isoformat(),
                    }
                    for cmd in commands
                ],
                "server_time": now.isoformat(),
            }
        )


class DeviceCommandAckView(APIView):
    def post(self, request, command_id):
        require_edge()
        device = device_or_401(request)
        from apps.synchronization.command_service import acknowledge_device_command

        try:
            command = acknowledge_device_command(
                device,
                str(command_id),
                status=str(request.data.get("status", "ok")),
                result=request.data.get("result"),
                error=str(request.data.get("error", "")),
            )
        except ValueError as exc:
            raise ApiError("unknown_command", str(exc), status.HTTP_404_NOT_FOUND) from exc
        return Response({"command_id": str(command.id), "status": command.status})


class ClientUserLoginView(APIView):
    """Allows a customer/gamer to log in directly from the client machine with 4-6 digit code, username, or phone."""

    def post(self, request):
        require_edge()
        device = device_or_401(request)
        data = request.data or {}
        raw_identifier = str(data.get("username", "")).strip()
        raw_password = str(data.get("password", "")).strip()

        if not raw_identifier:
            raise ApiError("invalid_credentials", "کد ورود ۴ تا ۶ رقمی یا شماره همراه الزامی است.", status.HTTP_400_BAD_REQUEST)

        # تبدیل ارقام فارسی و عربی به ارقام استاندارد انگلیسی
        persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
        english = "01234567890123456789"
        trans = str.maketrans(persian_arabic, english)
        clean_identifier = raw_identifier.translate(trans).strip()
        clean_password = raw_password.translate(trans).strip()

        identity = ensure_identity()
        from django.db.models import Q
        from apps.customers.models import Customer
        from apps.wallets.models import Wallet
        from apps.sessions.services import start_session, SessionError

        customer = (
            Customer.objects.filter(edge_id=identity.edge_id, is_active=True)
            .filter(
                Q(username__iexact=clean_identifier)
                | Q(username__iexact=raw_identifier)
                | Q(phone=clean_identifier)
                | Q(phone=raw_identifier)
            )
            .first()
        )

        if customer is None:
            raise ApiError("invalid_credentials", "کاربری با این مشخصات یافت نشد یا حساب غیرفعال است.", status.HTTP_401_UNAUTHORIZED)

        if not raw_password:
            raise ApiError("password_required", "وارد کردن رمز عبور الزامی است.", status.HTTP_400_BAD_REQUEST)

        # اعتبارسنجی رمز عبور (اجباری - رمز اولیه شماره موبایل است و در صورت تغییر، رمز جدید)
        valid_password = False
        if customer.password_hash:
            if customer.check_password(raw_password) or customer.check_password(clean_password):
                valid_password = True

        # اگر رمز اولیه همان شماره موبایل باشد
        if not valid_password and customer.phone:
            clean_phone = customer.phone.translate(trans).strip()
            if clean_password == clean_phone or raw_password == customer.phone:
                valid_password = True
                customer.set_password(clean_phone)
                customer.save(update_fields=["password_hash"])

        if not valid_password:
            raise ApiError("invalid_credentials", "رمز عبور اشتباه است.", status.HTTP_401_UNAUTHORIZED)

        try:
            session = start_session(customer=customer, device=device)
        except SessionError as exc:
            raise ApiError("session_start_failed", str(exc), status.HTTP_400_BAD_REQUEST) from exc
        except Exception as exc:
            logger.exception("Unexpected error in start_session for %s on %s: %s", customer.id, device.id, exc)
            raise ApiError("session_start_error", f"خطای سرور در شروع نشست و باز کردن سیستم: {exc}", status.HTTP_500_INTERNAL_SERVER_ERROR) from exc

        wallet = Wallet.objects.filter(customer=customer).first()
        balance = wallet.balance if wallet else 0

        return Response(
            {
                "ok": True,
                "session_id": str(session.id),
                "customer_id": str(customer.id),
                "customer_name": customer.full_name,
                "username": customer.username or customer.phone,
                "wallet_balance": balance,
                "credit_limit": customer.credit_limit,
                "hourly_rate": session.hourly_rate,
                "tariff_name": session.tariff_name,
                "coupon_hours": getattr(session, "coupon_hours", 0) or 0,
                "coupon_hourly_rate": getattr(session, "coupon_hourly_rate", 20000) or 20000,
                "has_coupon": bool(getattr(session, "coupon_hours", 0) > 0),
                "coupon_message": (
                    f"🎁 شما دارای {session.coupon_hours} کوپن تخفیف ۵۰٪ رهرو هستید؛ "
                    f"تا {session.coupon_hours} ساعت با تعرفه ویژه ۲۰,۰۰۰ تومان در ساعت محاسبه می‌شوید."
                ) if getattr(session, "coupon_hours", 0) > 0 else "",
                "billing_mode": session.billing_mode,
                "planned_duration_minutes": session.planned_duration_minutes,
                "disconnect_policy": session.disconnect_policy,
                "started_at": session.started_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class ClientUserLogoutView(APIView):
    """Allows the logged in gamer to end their session and relock the machine."""

    def post(self, request):
        require_edge()
        device = device_or_401(request)
        from apps.sessions.models import GamingSession, SessionStatus
        from apps.sessions.services import stop_session
        from apps.wallets.models import Wallet

        session = GamingSession.objects.filter(device=device, status=SessionStatus.ACTIVE).first()
        if session is None:
            return Response({"ok": True, "message": "هیچ نشست فعالی برای این دستگاه یافت نشد."})

        data = request.data if isinstance(request.data, dict) else {}
        keep_processes = bool(data.get("keep_processes"))
        reason = "خروج موقت و قفل سیستم توسط کاربر (Alt+F5)" if keep_processes else "خروج توسط کاربر از کلاینت"

        session, entry = stop_session(session, reason=reason, keep_processes=keep_processes)
        wallet = Wallet.objects.filter(customer=session.customer).first()
        balance = wallet.balance if wallet else 0

        return Response(
            {
                "ok": True,
                "session_id": str(session.id),
                "elapsed_seconds": session.elapsed_seconds,
                "cost": session.cost,
                "wallet_balance": balance,
            },
            status=status.HTTP_200_OK,
        )


class ClientAdminUnlockView(APIView):
    """Allows an administrator to authenticate from the client and exit kiosk / launch explorer."""

    def post(self, request):
        require_edge()
        device = device_or_401(request)
        data = request.data or {}
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        from django.contrib.auth import authenticate

        user = authenticate(request, username=username, password=password)
        if user is None and password != password.strip():
            user = authenticate(request, username=username, password=password.strip())
        if user is None or not (user.is_staff or user.is_superuser):
            raise ApiError("unauthorized", "نام کاربری یا رمز عبور ادمین نامعتبر است.", status.HTTP_401_UNAUTHORIZED)

        AuditLog.objects.create(
            actor=user,
            actor_label=user.label,
            action="client.admin_unlock_local",
            object_type="device",
            object_id=str(device.id),
            metadata={"device_name": device.name},
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        return Response({"ok": True, "message": "دسترسی ادمین تایید شد."})


class ClientResetPairingView(APIView):
    """Allows an authenticated admin on the client PC to unpair & reset the station slot cleanly."""

    def post(self, request):
        require_edge()
        device = device_or_401(request)
        data = request.data or {}
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))

        from django.contrib.auth import authenticate
        from apps.devices.services import RegistrationError, reset_device_pairing

        user = authenticate(request, username=username, password=password)
        if user is None and password != password.strip():
            user = authenticate(request, username=username, password=password.strip())
        if user is None or not (user.is_staff or user.is_superuser):
            raise ApiError("unauthorized", "نام کاربری یا رمز عبور ادمین نامعتبر است.", status.HTTP_401_UNAUTHORIZED)

        try:
            reset_device_pairing(device, actor=user, notify_client=False)
        except RegistrationError as exc:
            raise ApiError("reset_blocked", str(exc), status.HTTP_400_BAD_REQUEST) from exc

        AuditLog.objects.create(
            actor=user,
            actor_label=user.label,
            action="device.reset_by_client",
            object_type="device",
            object_id=str(device.id),
            metadata={"device_name": device.name},
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        return Response({"ok": True, "message": f"اتصال ایستگاه «{device.name}» با موفقیت بازنشانی شد."})


class ClientChangePasswordView(APIView):
    """Allows the currently logged in gamer on this device to change their password."""

    def post(self, request):
        require_edge()
        device = device_or_401(request)
        from apps.sessions.models import GamingSession, SessionStatus

        session = GamingSession.objects.filter(device=device, status=SessionStatus.ACTIVE).first()
        if session is None:
            raise ApiError("no_active_session", "نشست فعالی برای این دستگاه یافت نشد. ابتدا وارد سیستم شوید.", status.HTTP_400_BAD_REQUEST)

        customer = session.customer
        data = request.data or {}
        raw_current = str(data.get("current_password", "")).strip()
        raw_new = str(data.get("new_password", "")).strip()

        persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
        english = "01234567890123456789"
        trans = str.maketrans(persian_arabic, english)
        clean_current = raw_current.translate(trans).strip()
        clean_new = raw_new.translate(trans).strip()

        if not raw_new or len(clean_new) < 4:
            raise ApiError("invalid_new_password", "رمز عبور جدید باید حداقل ۴ رقم یا کاراکتر باشد.", status.HTTP_400_BAD_REQUEST)

        valid_current = False
        if customer.password_hash:
            if customer.check_password(raw_current) or customer.check_password(clean_current):
                valid_current = True

        if not valid_current and customer.phone:
            clean_phone = customer.phone.translate(trans).strip()
            if clean_current == clean_phone or raw_current == customer.phone:
                valid_current = True

        if not valid_current:
            raise ApiError("invalid_current_password", "رمز عبور فعلی نادرست است.", status.HTTP_401_UNAUTHORIZED)

        from django.db import transaction

        with transaction.atomic():
            customer.set_password(clean_new)
            customer.save(update_fields=["password_hash"])

            AuditLog.objects.create(
                actor=None,
                actor_label=customer.full_name,
                action="customer.password_changed_by_client",
                object_type="customer",
                object_id=str(customer.id),
                metadata={"device_id": str(device.id), "device_name": device.name},
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        return Response({"ok": True, "message": "رمز عبور با موفقیت تغییر یافت."})


def download_update_file(request, filename: str):
    """High-performance direct serving of client auto-update assets (app.asar, latest.json, exe)."""
    import os
    from django.conf import settings
    from django.http import HttpResponse, Http404

    safe_filename = os.path.basename(filename)
    for static_dir in getattr(settings, "STATICFILES_DIRS", []):
        filepath = os.path.join(static_dir, "updates", safe_filename)
        if os.path.isfile(filepath):
            with open(filepath, "rb") as f:
                content = f.read()
            content_type = "application/json" if safe_filename.endswith(".json") else "application/octet-stream"
            resp = HttpResponse(content, content_type=content_type)
            resp["Content-Length"] = str(len(content))
            resp["Access-Control-Allow-Origin"] = "*"
            resp["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
    raise Http404("Update file not found")




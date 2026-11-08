"""LAN API served by the edge to Windows clients."""

from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.clients.models import ClientDevice
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
            reason="rest heartbeat",
        )
        device.refresh_from_db(fields=["status"])
        cfg = _hub_config()
        return Response(
            {
                "server_time": timezone.now().isoformat(),
                "desired_state": device.status,
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

        # اعتبارسنجی رمز عبور:
        # ۱. اگر پسورد هش تنظیم شده باشد: بررسی پسورد یا انطباق با کد ۴-۶ رقمی/شماره تماس
        # ۲. اگر پسورد هش تنظیم نشده باشد: پذیرش ورود با همان کد ۴-۶ رقمی یا شماره
        valid_password = False
        if customer.password_hash:
            if clean_password and (
                customer.check_password(raw_password)
                or customer.check_password(clean_password)
                or clean_password == customer.username
                or clean_password == customer.phone
                or raw_password == customer.username
            ):
                valid_password = True
        else:
            # بدون نیاز به رمز پیچیده؛ ورود با کد ۴-۶ رقمی
            if not clean_password or clean_password == customer.username or clean_password == customer.phone:
                valid_password = True

        if not valid_password:
            raise ApiError("invalid_credentials", "کد ورود یا رمز عبور اشتباه است.", status.HTTP_401_UNAUTHORIZED)

        try:
            session = start_session(customer=customer, device=device)
        except SessionError as exc:
            raise ApiError("session_start_failed", str(exc), status.HTTP_400_BAD_REQUEST) from exc

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

        session, entry = stop_session(session, reason="خروج توسط کاربر از کلاینت")
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


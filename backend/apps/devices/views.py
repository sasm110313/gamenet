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

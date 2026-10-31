"""Cloud-facing API used by edge nodes. All inbound traffic from the site."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import CommandStatus, RemoteCommand
from apps.core.api import ApiError, AuthenticationFailed, Conflict
from apps.core.auth import authenticate_edge_header, client_ip
from apps.core.ids import uuid7
from apps.core.roles import require_cloud
from apps.core.security import canonical_json
from apps.synchronization.crypto import generate_command_keypair, hash_token, new_secret
from apps.synchronization.ingest import InvalidEvent, ingest_batch
from apps.synchronization.models import (
    ConfigSnapshot,
    EdgeNode,
    EdgeRegistrationCode,
    EdgeStatus,
    SyncEvent,
)

logger = logging.getLogger("gamenet.ingress")


def edge_or_401(request) -> EdgeNode:
    edge = authenticate_edge_header(request.headers.get("Authorization", ""))
    if edge is None:
        raise AuthenticationFailed("invalid edge credentials")
    return edge


class EdgeRegisterView(APIView):
    """One-time code -> edge identity + credentials. Retries with the same edge_id
    and code within 10 minutes rotate the secret instead of dead-ending."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "registration"

    def post(self, request):
        require_cloud()
        data = request.data
        code = str(data.get("code", "")).strip().upper()
        name = str(data.get("name", "")).strip()[:120]
        software_version = str(data.get("software_version", ""))[:40]
        raw_edge_id = data.get("edge_id")

        if not code or not name:
            raise ApiError("invalid_request", "code and name are required")
        try:
            requested_edge_id = uuid.UUID(str(raw_edge_id)) if raw_edge_id else uuid7()
        except (ValueError, TypeError) as exc:
            raise ApiError("invalid_request", "edge_id must be a UUID") from exc

        now = timezone.now()
        with transaction.atomic():
            registration = (
                EdgeRegistrationCode.objects.select_for_update()
                .filter(code=code)
                .first()
            )
            if registration is None:
                raise AuthenticationFailed("invalid or expired registration code")

            if registration.used_at is not None:
                # Retry of a successful registration whose response was lost.
                recent = registration.used_at > now - timedelta(minutes=10)
                if recent and registration.used_by_id == requested_edge_id:
                    edge = EdgeNode.objects.select_for_update().get(pk=requested_edge_id)
                    secret = new_secret()
                    public_key, encrypted_private = generate_command_keypair()
                    edge.secret_hash = hash_token(secret)
                    edge.command_public_key = public_key
                    edge.command_private_key_enc = encrypted_private
                    edge.software_version = software_version
                    edge.save()
                    return Response(self._payload(edge, secret))
                raise AuthenticationFailed("registration code already used")

            if not registration.is_usable():
                raise AuthenticationFailed("registration code expired")

            if EdgeNode.objects.filter(pk=requested_edge_id).exists():
                raise Conflict("edge_id is already registered")

            secret = new_secret()
            public_key, encrypted_private = generate_command_keypair()
            edge = EdgeNode.objects.create(
                id=requested_edge_id,
                name=name,
                site_name=str(data.get("site_name", ""))[:160],
                software_version=software_version,
                secret_hash=hash_token(secret),
                command_public_key=public_key,
                command_private_key_enc=encrypted_private,
                status=EdgeStatus.REGISTERED,
            )
            registration.used_at = now
            registration.used_by = edge
            registration.save(update_fields=["used_at", "used_by"])
            AuditLog.objects.create(
                actor=registration.created_by,
                actor_label=registration.created_by.label if registration.created_by else "system",
                action="edge.registered",
                object_type="edge",
                object_id=str(edge.id),
                metadata={"name": edge.name, "software_version": software_version},
                ip_address=client_ip(request),
            )
        logger.info("edge %s registered as %s", edge.name, edge.id)
        return Response(self._payload(edge, secret), status=status.HTTP_201_CREATED)

    @staticmethod
    def _payload(edge: EdgeNode, secret: str) -> dict:
        latest = ConfigSnapshot.objects.filter(is_active=True).order_by("-version").first()
        return {
            "edge_id": str(edge.id),
            "secret": secret,
            "command_public_key": edge.command_public_key,
            "config_version": latest.version if latest else 0,
            "heartbeat_seconds": settings.EDGE_HEARTBEAT_SECONDS,
            "server_time": timezone.now().isoformat(),
            "ws_path": "/ws/edge/",
        }


class EdgeEventsView(APIView):
    def post(self, request):
        require_cloud()
        edge = edge_or_401(request)
        try:
            result = ingest_batch(edge, request.data.get("events", []))
        except InvalidEvent as exc:
            raise ApiError("invalid_event", str(exc)) from exc
        return Response(result)


class EdgeHeartbeatView(APIView):
    def post(self, request):
        require_cloud()
        edge = edge_or_401(request)
        now = timezone.now()
        devices = request.data.get("devices", [])
        if not isinstance(devices, list):
            raise ApiError("invalid_request", "devices must be a list")

        from apps.ingress.telemetry import apply_device_telemetry, mark_edge_seen

        apply_device_telemetry(edge, devices, now=now)
        mark_edge_seen(edge, now=now)
        edge.software_version = str(request.data.get("software_version", ""))[:40] or edge.software_version
        edge.last_acked_sequence = max(edge.last_acked_sequence, int(request.data.get("last_acked_sequence", 0) or 0))
        edge.save(update_fields=["software_version", "last_acked_sequence", "updated_at"])
        return Response(
            {
                "server_time": now.isoformat(),
                "pending_commands": RemoteCommand.objects.filter(
                    edge=edge, status=CommandStatus.PENDING, expires_at__gt=now
                ).count(),
                "errors": SyncEvent.objects.filter(edge=edge, status="REJECTED").count(),
            }
        )


class EdgeCommandsPendingView(APIView):
    def get(self, request):
        require_cloud()
        edge = edge_or_401(request)
        now = timezone.now()
        RemoteCommand.objects.filter(
            edge=edge, status=CommandStatus.PENDING, expires_at__lte=now
        ).update(status=CommandStatus.EXPIRED)
        limit = min(int(request.query_params.get("limit", 50) or 50), 200)
        commands = RemoteCommand.objects.filter(
            edge=edge, status=CommandStatus.PENDING, expires_at__gt=now
        ).order_by("issued_at")[:limit]
        return Response(
            {
                "commands": [
                    {**cmd.envelope(), "signature": cmd.signature} for cmd in commands
                ],
                "server_time": now.isoformat(),
            }
        )


class EdgeConfigView(APIView):
    def get(self, request):
        require_cloud()
        edge_or_401(request)
        try:
            after = int(request.query_params.get("after", 0) or 0)
        except ValueError:
            after = 0
        snapshot = (
            ConfigSnapshot.objects.filter(is_active=True, version__gt=after)
            .order_by("-version")
            .first()
        )
        if snapshot is None:
            latest = ConfigSnapshot.objects.filter(is_active=True).order_by("-version").first()
            return Response(
                {"up_to_date": True, "version": latest.version if latest else 0,
                 "server_time": timezone.now().isoformat()}
            )
        return Response(
            {
                "up_to_date": False,
                "snapshot": {
                    "version": snapshot.version,
                    "content_hash": snapshot.content_hash,
                    "payload": snapshot.payload,
                },
                "server_time": timezone.now().isoformat(),
            }
        )

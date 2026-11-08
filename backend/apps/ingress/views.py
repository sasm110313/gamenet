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


class RahroCustomerSyncView(APIView):
    """
    دریافت و ثبت/به‌روزرسانی خودکار کاربران سامانه رهرو در گیم‌نت:
    تخصیص خودکار به گروه مالی «اعضای رهرو» با نرخ ساعتی ۴۰,۰۰۰ تومان
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
        token = request.headers.get("X-Internal-Secret") or request.data.get("secret")
        if token != secret:
            return Response({"error": "Forbidden (invalid secret)"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        username = (data.get("username") or "").strip()
        phone = (data.get("phone") or "").strip()
        full_name = (data.get("full_name") or "").strip() or username
        password_hash = data.get("password_hash") or ""
        is_active = bool(data.get("is_active", True))
        action = data.get("action", "sync")
        is_deleted = bool(data.get("is_deleted", False))

        if not phone and not username:
            return Response({"error": "phone or username required"}, status=status.HTTP_400_BAD_REQUEST)

        import uuid
        from apps.customers.models import Customer
        from apps.customer_groups.models import CustomerGroup
        from apps.pricing.models import Tariff
        from apps.wallets.models import Wallet
        from apps.synchronization.models import EdgeNode
        from apps.ingress.management import _issue

        # پیدا کردن سرور لبه (سالن اصلی)
        edge = EdgeNode.objects.filter(revoked_at__isnull=True).order_by("-last_heartbeat_at").first()
        edge_id = edge.id if edge else uuid.UUID("01a18e45-00ea-7f5b-8631-0d6406670e55")

        # در صورتی که کاربر از رهرو حذف یا غیرفعال شده باشد
        if action == "remove" or is_deleted or not is_active:
            customer = None
            if phone:
                customer = Customer.objects.filter(phone=phone).first()
            if not customer and username:
                customer = Customer.objects.filter(username=username).first()

            if customer is None:
                return Response({"success": True, "message": "کاربر در گیم‌نت یافت نشد."})

            # تضمین وجود تعرفه ۶۰ هزار تومانی عادی
            normal_tariff, _ = Tariff.objects.get_or_create(
                name="عادی",
                edge_id=edge_id,
                defaults={"hourly_rate": 60000, "is_active": True, "is_replica": False}
            )
            normal_group, _ = CustomerGroup.objects.get_or_create(
                name="عادی",
                edge_id=edge_id,
                defaults={"tariff": normal_tariff, "is_active": True, "is_replica": False}
            )

            customer.group = normal_group
            customer.notes = "عضویت رهرو لغو/حذف گردید (تعرفه عادی ۶۰,۰۰۰ تومان)"
            customer.save(update_fields=["group", "notes", "updated_at"])

            # لغو تخفیف‌های رهرو روی نشست فعال
            from apps.sessions.models import SessionStatus
            active_session = customer.sessions.filter(status=SessionStatus.ACTIVE).first()
            if active_session and active_session.discount_source in ["RAHRO", "MONTHLY_QUOTA", "POINTS"]:
                active_session.discount_percent = 0
                active_session.discount_source = ""
                active_session.save(update_fields=["discount_percent", "discount_source", "updated_at"])

            if edge is not None:
                try:
                    _issue(
                        request,
                        edge,
                        "catalog.customer.upsert",
                        {
                            "customer_id": str(customer.id),
                            "base_revision": customer.revision,
                            "full_name": customer.full_name,
                            "username": customer.username,
                            "password": "",
                            "phone": customer.phone,
                            "group_id": str(normal_group.id),
                            "credit_limit": customer.credit_limit,
                            "notes": customer.notes,
                            "is_active": customer.is_active,
                        },
                        action="remote.customer.removed_from_rahro",
                    )
                except Exception:
                    pass

            return Response({
                "success": True,
                "action": "removed_from_rahro",
                "customer_id": str(customer.id),
                "full_name": customer.full_name,
                "group": normal_group.name,
                "hourly_rate": normal_tariff.hourly_rate,
                "message": "خدمات رهرو لغو شد؛ نرخ ساعتی به ۶۰,۰۰۰ تومان تغییر یافت."
            })

        # تضمین وجود تعرفه ۴۰ هزار تومانی رهرو
        rahro_tariff, _ = Tariff.objects.get_or_create(
            name="تعرفه اعضای رهرو",
            edge_id=edge_id,
            defaults={"hourly_rate": 40000, "is_active": True, "is_replica": False}
        )
        if rahro_tariff.hourly_rate != 40000:
            rahro_tariff.hourly_rate = 40000
            rahro_tariff.save(update_fields=["hourly_rate"])

        # تضمین وجود گروه مشتریان اعضای رهرو
        rahro_group, _ = CustomerGroup.objects.get_or_create(
            name="اعضای رهرو",
            edge_id=edge_id,
            defaults={"tariff": rahro_tariff, "is_active": True, "is_replica": False}
        )
        if rahro_group.tariff_id != rahro_tariff.id:
            rahro_group.tariff = rahro_tariff
            rahro_group.save(update_fields=["tariff"])

        # جستجو یا ایجاد مشتری
        customer = None
        if phone:
            customer = Customer.objects.filter(phone=phone).first()
        if not customer and username:
            customer = Customer.objects.filter(username=username).first()

        created = False
        if customer is None:
            customer_id = uuid.uuid4()
            customer = Customer.objects.create(
                id=customer_id,
                edge_id=edge_id,
                full_name=full_name,
                username=username,
                phone=phone,
                password_hash=password_hash,
                group=rahro_group,
                credit_limit=getattr(settings, "DEFAULT_CREDIT_LIMIT", 60000),
                is_active=is_active,
                notes="عضو سامانه رهرو (همگام‌سازی خودکار)",
                is_replica=True,
            )
            created = True
        else:
            customer.full_name = full_name or customer.full_name
            if username:
                customer.username = username
            if phone:
                customer.phone = phone
            if password_hash:
                customer.password_hash = password_hash
            customer.group = rahro_group
            customer.is_active = is_active
            customer.save(update_fields=["full_name", "username", "phone", "password_hash", "group", "is_active", "updated_at"])

        # تضمین وجود کیف پول
        wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})

        # ارسال فرمان به لبه در صورت فعال بودن
        if edge is not None:
            try:
                _issue(
                    request,
                    edge,
                    "catalog.customer.upsert",
                    {
                        "customer_id": str(customer.id),
                        "base_revision": customer.revision,
                        "full_name": customer.full_name,
                        "username": customer.username,
                        "password": "",
                        "phone": customer.phone,
                        "group_id": str(rahro_group.id),
                        "credit_limit": customer.credit_limit,
                        "notes": customer.notes,
                        "is_active": customer.is_active,
                    },
                    action="remote.customer.synced_from_rahro",
                )
            except Exception:
                pass

        return Response({
            "success": True,
            "created": created,
            "customer_id": str(customer.id),
            "full_name": customer.full_name,
            "username": customer.username,
            "phone": customer.phone,
            "group": rahro_group.name,
            "hourly_rate": rahro_tariff.hourly_rate,
        })

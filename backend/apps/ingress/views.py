"""Cloud-facing API used by edge nodes. All inbound traffic from the site."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
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


def _active_salon_edge() -> EdgeNode | None:
    return (
        EdgeNode.objects.exclude(status=EdgeStatus.REVOKED)
        .filter(revoked_at__isnull=True)
        .order_by(F("last_heartbeat_at").desc(nulls_last=True), "-created_at")
        .first()
    )


def _adopt_revoked_edge_catalog(new_edge_id: uuid.UUID) -> None:
    """When a new salon server replaces a revoked one, hand over shared salon customers & tariffs."""
    from apps.customer_groups.models import CustomerGroup
    from apps.customers.models import Customer
    from apps.ledger.models import LedgerEntry
    from apps.pricing.models import CustomerRate, Tariff
    from apps.sessions.models import GamingSession

    revoked_ids = list(
        EdgeNode.objects.filter(status=EdgeStatus.REVOKED).values_list("id", flat=True)
    )
    if not revoked_ids:
        return
    Tariff.objects.filter(edge_id__in=revoked_ids).update(edge_id=new_edge_id)
    CustomerGroup.objects.filter(edge_id__in=revoked_ids).update(edge_id=new_edge_id)
    Customer.objects.filter(edge_id__in=revoked_ids).update(edge_id=new_edge_id)
    CustomerRate.objects.filter(edge_id__in=revoked_ids).update(edge_id=new_edge_id)
    LedgerEntry.objects.filter(edge_id__in=revoked_ids).update(edge_id=new_edge_id)
    GamingSession.objects.filter(edge_id__in=revoked_ids).update(edge_id=new_edge_id)


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
            _adopt_revoked_edge_catalog(edge.id)
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
        from apps.applications.services import get_games_catalog_state, save_games_catalog

        edge_games_version = int(request.data.get("games_version") or 0)
        edge_games_hash = str(request.data.get("games_hash") or "")
        edge_games_catalog = request.data.get("games_catalog")
        cloud_games_state = get_games_catalog_state()

        # If edge sent a games catalog that differs from cloud replica, save edge's catalog
        if (
            isinstance(edge_games_catalog, list)
            and len(edge_games_catalog) > 0
            and edge_games_hash != cloud_games_state["hash"]
        ):
            save_games_catalog(edge_games_catalog, version=max(edge_games_version, int(cloud_games_state["version"] or 0) + 1))
            cloud_games_state = get_games_catalog_state()

        resp_payload = {
            "server_time": now.isoformat(),
            "pending_commands": RemoteCommand.objects.filter(
                edge=edge, status=CommandStatus.PENDING, expires_at__gt=now
            ).count(),
            "errors": SyncEvent.objects.filter(edge=edge, status="REJECTED").count(),
            "games_version": cloud_games_state["version"],
            "games_hash": cloud_games_state["hash"],
        }
        # Only push cloud games to Edge if Edge has an empty/uninitialized catalog
        if edge_games_version == 0 and len(edge_games_catalog or []) == 0 and len(cloud_games_state.get("games") or []) > 0:
            resp_payload["games_catalog"] = cloud_games_state["games"]

        return Response(resp_payload)


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
        from apps.applications.services import get_games_catalog_state

        games_state = get_games_catalog_state()
        if snapshot is None:
            latest = ConfigSnapshot.objects.filter(is_active=True).order_by("-version").first()
            return Response(
                {
                    "up_to_date": True,
                    "version": latest.version if latest else 0,
                    "games_catalog": games_state["games"],
                    "games_version": games_state["version"],
                    "games_hash": games_state["hash"],
                    "server_time": timezone.now().isoformat(),
                }
            )
        return Response(
            {
                "up_to_date": False,
                "snapshot": {
                    "version": snapshot.version,
                    "content_hash": snapshot.content_hash,
                    "payload": snapshot.payload,
                },
                "games_catalog": games_state["games"],
                "games_version": games_state["version"],
                "games_hash": games_state["hash"],
                "server_time": timezone.now().isoformat(),
            }
        )


class EdgeSeedCatalogView(APIView):
    """Serve existing Cloud tariffs, groups, and customers so a newly installed Edge syncs seamlessly."""

    def get(self, request):
        require_cloud()
        edge = edge_or_401(request)
        from apps.customer_groups.models import CustomerGroup
        from apps.customers.models import Customer
        from apps.pricing.models import CustomerRate, Tariff

        _adopt_revoked_edge_catalog(edge.id)
        tariffs = [
            {
                "id": str(t.id),
                "name": t.name,
                "hourly_rate": t.hourly_rate,
                "is_active": t.is_active,
                "revision": t.revision,
            }
            for t in Tariff.objects.filter(edge_id=edge.id, is_active=True)
        ]
        groups = [
            {
                "id": str(g.id),
                "name": g.name,
                "tariff_id": str(g.tariff_id) if g.tariff_id else None,
                "is_active": g.is_active,
                "revision": g.revision,
            }
            for g in CustomerGroup.objects.filter(edge_id=edge.id, is_active=True)
        ]
        customers = []
        for c in Customer.objects.filter(edge_id=edge.id).select_related("wallet"):
            wallet_bal = getattr(getattr(c, "wallet", None), "balance", 0)
            rates = [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "hourly_rate": r.hourly_rate,
                    "is_default": r.is_default,
                    "is_active": r.is_active,
                    "revision": r.revision,
                }
                for r in CustomerRate.objects.filter(customer=c, is_active=True)
            ]
            customers.append(
                {
                    "id": str(c.id),
                    "full_name": c.full_name,
                    "username": c.username,
                    "password_hash": c.password_hash,
                    "phone": c.phone,
                    "group_id": str(c.group_id) if c.group_id else None,
                    "group_name": c.group.name if c.group else None,
                    "credit_limit": c.credit_limit,
                    "debt_balance": c.debt_balance,
                    "max_debt_limit": c.max_debt_limit,
                    "active_coupons": getattr(c, "active_coupons", 0),
                    "is_active": c.is_active,
                    "notes": c.notes,
                    "revision": c.revision,
                    "wallet_balance": int(wallet_bal or 0),
                    "rates": rates,
                }
            )
        return Response(
            {
                "edge_id": str(edge.id),
                "tariffs": tariffs,
                "groups": groups,
                "customers": customers,
            }
        )


def _queue_rahro_command(request, edge, command_type, payload, *, action):
    from apps.synchronization.command_service import issue_command

    command = issue_command(edge, command_type, payload, ttl_seconds=86400)
    AuditLog.objects.create(
        actor_label="Rahro", action=action, object_type="remote_command",
        object_id=str(command.id), metadata={"edge_id": str(edge.id)},
    )
    return command


class RahroCustomerSyncView(APIView):
    """
    دریافت و ثبت/به‌روزرسانی خودکار کاربران سامانه رهرو در گیم‌نت:
    تخصیص خودکار به گروه مالی «اعضای رهرو» با نرخ ساعتی ۴۰,۰۰۰ تومان
    """
    authentication_classes = []
    permission_classes = []

    @transaction.atomic
    def post(self, request):
        require_cloud()
        data = request.data
        if not isinstance(data, dict):
            return Response({"error": "payload must be an object"}, status=400)
        secret = getattr(settings, "RAHRO_GAMENET_SHARED_SECRET", "rahro_gamenet_secret_2026")
        token = request.headers.get("X-Internal-Secret") or data.get("secret")
        if token != secret:
            return Response({"error": "Forbidden (invalid secret)"}, status=status.HTTP_403_FORBIDDEN)

        if any(key in data and not isinstance(data[key], bool) for key in ("is_active", "is_deleted")):
            return Response({"error": "is_active and is_deleted must be booleans"}, status=400)
        username = str(data.get("username") or "").strip()
        raw_username = str(data.get("raw_username") or "").strip()
        login_code = str(data.get("login_code") or "").strip()
        phone = str(data.get("phone") or "").strip()
        full_name = str(data.get("full_name") or "").strip() or raw_username or username
        password_hash = data.get("password_hash") or ""
        is_active = bool(data.get("is_active", True))
        action = data.get("action", "sync")
        is_deleted = bool(data.get("is_deleted", False))
        role = str(data.get("role") or "").strip().upper()
        try:
            raw_coupons = data["active_coupons"] if "active_coupons" in data else data.get("coupon_hours")
            active_coupons = int(raw_coupons) if raw_coupons is not None else None
            if isinstance(raw_coupons, (bool, float)) or (active_coupons is not None and active_coupons < 0):
                raise ValueError
        except (TypeError, ValueError):
            return Response({"error": "invalid coupon count"}, status=400)

        if not phone and not username and not raw_username:
            return Response({"error": "phone or username required"}, status=status.HTTP_400_BAD_REQUEST)

        # استثنای قطعی والدین: والدین به هیچ وجه نباید در گیم‌نت ثبت یا سینک شوند
        if role == "PARENT" or "والدین" in full_name:
            import uuid
            from apps.customers.models import Customer
            from apps.wallets.models import Wallet
            from apps.ledger.models import LedgerEntry
            from apps.synchronization.models import EdgeNode
            _issue = _queue_rahro_command

            edge = _active_salon_edge()

            customer = None
            if phone:
                customer = Customer.objects.filter(phone=phone).first()
            if not customer and username:
                customer = Customer.objects.filter(username=username).first()
            if not customer and raw_username:
                customer = Customer.objects.filter(username=raw_username).first()

            if customer:
                cust_id_str = str(customer.id)
                has_ledger = LedgerEntry.objects.filter(customer=customer).exists()
                has_sessions = customer.sessions.exists()
                has_balance = Wallet.objects.filter(customer=customer).exclude(balance=0).exists()
                if not has_ledger and not has_sessions and not has_balance:
                    Wallet.objects.filter(customer=customer).delete()
                    customer.delete()
                    if edge is not None:
                        try:
                            _issue(
                                request,
                                edge,
                                "catalog.customer.delete",
                                {"customer_id": cust_id_str},
                                action="remote.customer.parent_excluded",
                            )
                        except Exception:
                            logger.exception("Could not queue Rahro parent exclusion")
                            raise
                else:
                    customer.is_active = False
                    customer.notes = "حساب والد (غیرفعال‌شده - خارج از گیم‌نت)"
                    customer.save(update_fields=["is_active", "notes", "updated_at"])

            return Response({
                "success": True,
                "message": "والدین در گیم‌نت سینک نمی‌شوند (نادیده گرفته یا حذف شد).",
                "is_parent": True,
            })

        # اعتبارسنجی کد ۴ تا ۶ رقمی ورود کلاینت:
        # اگر کاربر عدد ۴ تا ۶ رقمی در رهرو نداشت، خالی می‌ماند تا در گیم‌نت دستی تعیین شود
        valid_code = ""
        if login_code and login_code.isdigit() and 4 <= len(login_code) <= 6:
            valid_code = login_code
        elif username and username.isdigit() and 4 <= len(username) <= 6:
            valid_code = username

        import uuid
        from apps.customers.models import Customer
        from apps.customer_groups.models import CustomerGroup
        from apps.pricing.models import Tariff
        from apps.wallets.models import Wallet
        from apps.synchronization.models import EdgeNode
        _issue = _queue_rahro_command

        # پیدا کردن سرور لبه (سالن اصلی)
        edge = _active_salon_edge()
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

            if "والدین" in customer.full_name:
                cust_id_str = str(customer.id)
                Wallet.objects.filter(customer=customer).delete()
                customer.delete()
                if edge is not None:
                    try:
                        _issue(request, edge, "catalog.customer.delete", {"customer_id": cust_id_str}, action="remote.customer.parent_excluded")
                    except Exception:
                        logger.exception("Could not queue Rahro parent removal")
                        raise
                return Response({"success": True, "message": "حساب والد با موفقیت از گیم‌نت حذف گردید."})

            # تضمین وجود تعرفه ۶۰ هزار تومانی آزاد (پیش‌فرض)
            free_tariff, _ = Tariff.objects.get_or_create(
                name="آزاد", edge_id=edge_id,
                defaults={"hourly_rate": 60000, "is_active": True, "edge_id": edge_id, "is_replica": False}
            )
            free_group, _ = CustomerGroup.objects.get_or_create(
                name="آزاد", edge_id=edge_id,
                defaults={"tariff": free_tariff, "is_active": True, "edge_id": edge_id, "is_replica": False}
            )

            customer.group = free_group
            customer.notes = "عضویت رهرو لغو/حذف گردید (تعرفه آزاد ۶۰,۰۰۰ تومان)"
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
                            "group_id": str(free_group.id),
                            "credit_limit": customer.credit_limit,
                            "notes": customer.notes,
                            "is_active": customer.is_active,
                        },
                        action="remote.customer.removed_from_rahro",
                    )
                except Exception:
                    logger.exception("Could not queue Rahro membership removal")
                    raise

            return Response({
                "success": True,
                "action": "removed_from_rahro",
                "customer_id": str(customer.id),
                "full_name": customer.full_name,
                "group": free_group.name,
                "hourly_rate": free_tariff.hourly_rate,
                "message": "خدمات رهرو لغو شد؛ نرخ ساعتی به ۶۰,۰۰۰ تومان تغییر یافت."
            })

        try:
            req_rate = int(data.get("hourly_rate") or 0)
        except (TypeError, ValueError):
            return Response({"error": "invalid hourly rate"}, status=400)
        req_group_name = (data.get("group_name") or "").strip()

        # تفکیک تعرفه‌های سه‌گانه: کادر (۲۰ هزار تومان) یا لیگ رهرو (۴۰ هزار تومان)
        if req_rate == 20000 or "کادر" in req_group_name or any(k in req_group_name for k in ["8", "9", "۸", "۹"]):
            target_tariff, _ = Tariff.objects.get_or_create(
                name="کادر", edge_id=edge_id,
                defaults={"hourly_rate": 20000, "is_active": True, "edge_id": edge_id, "is_replica": False}
            )
            if target_tariff.hourly_rate != 20000:
                target_tariff.hourly_rate = 20000
                target_tariff.save(update_fields=["hourly_rate"])

            target_group, _ = CustomerGroup.objects.get_or_create(
                name="کادر", edge_id=edge_id,
                defaults={"tariff": target_tariff, "is_active": True, "edge_id": edge_id, "is_replica": False}
            )
            if target_group.tariff_id != target_tariff.id:
                target_group.tariff = target_tariff
                target_group.save(update_fields=["tariff"])
            notes_text = "عضو کادر رهرو (تعرفه ساعتی ۲۰,۰۰۰ تومان)"
        else:
            target_tariff, _ = Tariff.objects.get_or_create(
                name="لیگ رهرو", edge_id=edge_id,
                defaults={"hourly_rate": 40000, "is_active": True, "edge_id": edge_id, "is_replica": False}
            )
            if target_tariff.hourly_rate != 40000:
                target_tariff.hourly_rate = 40000
                target_tariff.save(update_fields=["hourly_rate"])

            target_group, _ = CustomerGroup.objects.get_or_create(
                name="لیگ رهرو", edge_id=edge_id,
                defaults={"tariff": target_tariff, "is_active": True, "edge_id": edge_id, "is_replica": False}
            )
            if target_group.tariff_id != target_tariff.id:
                target_group.tariff = target_tariff
                target_group.save(update_fields=["tariff"])
            notes_text = "عضو لیگ رهرو (تعرفه ساعتی ۴۰,۰۰۰ تومان)"

        # جستجو یا ایجاد مشتری
        customer = None
        if phone:
            customer = Customer.objects.filter(edge_id=edge_id, phone=phone).first()
        if not customer and valid_code:
            customer = Customer.objects.filter(edge_id=edge_id, username=valid_code).first()
        if not customer and raw_username:
            customer = Customer.objects.filter(edge_id=edge_id, username=raw_username).first()

        created = False
        if customer is None:
            customer_id = uuid.uuid4()
            customer = Customer.objects.create(
                id=customer_id,
                edge_id=edge_id,
                full_name=full_name,
                username=valid_code,  # فقط در صورت داشتن عدد ۴ تا ۶ رقمی؛ در غیر این صورت خالی بگذار تا دستی وارد شود
                phone=phone,
                password_hash=password_hash,
                group=target_group,
                credit_limit=getattr(settings, "DEFAULT_CREDIT_LIMIT", 60000),
                active_coupons=active_coupons or 0,
                is_active=is_active,
                notes=notes_text,
                is_replica=True,
            )
            created = True
        else:
            customer.full_name = full_name or customer.full_name
            if valid_code:
                customer.username = valid_code
            elif customer.username and not (customer.username.isdigit() and 4 <= len(customer.username) <= 6):
                # اگر کد فعلی متنی یا غیرعددی باشد (مانند admin_rahro)، پاکش کن تا خالی بماند
                customer.username = ""
            if phone:
                customer.phone = phone
            if password_hash:
                customer.password_hash = password_hash
            customer.group = target_group
            if active_coupons is not None:
                customer.active_coupons = active_coupons
            customer.notes = notes_text
            customer.is_active = is_active
            customer.save(update_fields=["full_name", "username", "phone", "password_hash", "group", "active_coupons", "notes", "is_active", "updated_at"])

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
                        "password_hash": customer.password_hash,
                        "phone": customer.phone,
                        "group_id": str(target_group.id),
                        "group_name": target_group.name,
                        "credit_limit": customer.credit_limit,
                        **({"active_coupons": customer.active_coupons} if active_coupons is not None else {}),
                        "notes": customer.notes,
                        "is_active": customer.is_active,
                    },
                    action="remote.customer.synced_from_rahro",
                )
            except Exception:
                logger.exception("Could not queue Rahro customer sync")
                raise

        return Response({
            "success": True,
            "created": created,
            "customer_id": str(customer.id),
            "full_name": customer.full_name,
            "username": customer.username,
            "phone": customer.phone,
            "group": target_group.name,
            "hourly_rate": target_tariff.hourly_rate,
        })


class RahroRecordPaidSessionView(APIView):
    """
    ثبت نشست پرداخت‌شده با تخفیف ۵۰٪ (یا هر درصدی) رهرو و ثبت پرداخت نقدی در کیف پول گیم‌نت:
    - ایجاد سابقه نشست تکمیل‌شده (COMPLETED) با نصف قیمت
    - ثبت شارژ نشست (-۱۵,۰۰۰ تومان)
    - ثبت واریز نقدی مشتری در باجه (+۱۵,۰۰۰ تومان)
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
        if not phone and not username:
            return Response({"error": "phone or username required"}, status=status.HTTP_400_BAD_REQUEST)

        import uuid
        from datetime import timedelta
        from django.utils import timezone
        from apps.customers.models import Customer
        from apps.customer_groups.models import CustomerGroup
        from apps.pricing.models import Tariff
        from apps.sessions.models import GamingSession, SessionStatus
        from apps.ledger.models import LedgerEntry, LedgerEntryType
        from apps.wallets.models import Wallet
        from apps.synchronization.models import EdgeNode

        # ۱. جستجوی مشتری در گیم‌نت
        customer = None
        if phone:
            customer = Customer.objects.filter(phone=phone).first()
        if not customer and username:
            customer = Customer.objects.filter(username__iexact=username).first()

        # پیدا کردن سرور لبه فعال
        edge = _active_salon_edge()
        edge_id = edge.id if edge else uuid.UUID("01a18e45-00ea-7f5b-8631-0d6406670e55")

        if not customer:
            rahro_group = CustomerGroup.objects.filter(name="لیگ رهرو").first() or CustomerGroup.objects.filter(name="آزاد").first()
            customer = Customer.objects.create(
                id=uuid.uuid4(),
                edge_id=edge_id,
                full_name=data.get("full_name") or username or phone,
                username=username,
                phone=phone,
                group=rahro_group,
                is_active=True,
                is_replica=True,
            )

        wallet, _ = Wallet.objects.get_or_create(customer=customer, defaults={"balance": 0})

        # ۲. پردازش اطلاعات مالی و زمانی نشست (مبنا: ۱ ساعت بازی)
        raw_sess_id = data.get("session_id")
        try:
            session_id = uuid.UUID(str(raw_sess_id)) if raw_sess_id else uuid.uuid4()
        except Exception:
            session_id = uuid.uuid4()

        duration_minutes = int(data.get("duration_minutes") or 60)
        duration_seconds = int(data.get("duration_seconds") or (duration_minutes * 60))
        hourly_rate = int(data.get("hourly_rate") or (customer.group.tariff.hourly_rate if customer.group and customer.group.tariff else 40000))
        base_cost = int(data.get("base_cost") or ((hourly_rate * duration_minutes) // 60))
        discount_percent = int(data.get("discount_percent") or 50)
        discount_amount = int(data.get("discount_amount") or (((base_cost * discount_percent) + 50) // 100))
        final_cost = int(data.get("final_cost") or max(0, base_cost - discount_amount))
        voucher_code = (data.get("voucher_code") or "").strip()
        device_name = (data.get("device_name") or "PC-01").strip()
        note = (data.get("note") or f"ثبت باجه و پرداخت نقدی ({final_cost:,} تومان)").strip()

        # پیدا کردن دستگاه معتبر در سالن برای انتساب نشست
        device = None
        if device_name:
            device = ClientDevice.objects.filter(name__iexact=device_name).first()
        if not device:
            device = ClientDevice.objects.filter(edge_id=edge_id, is_active=True).first()
        if not device:
            device = ClientDevice.objects.filter(is_active=True).first()

        now = timezone.now()
        started_at = now - timedelta(seconds=duration_seconds)

        # ۳. ثبت یا به‌روزرسانی نشست تکمیل‌شده در گیم‌نت
        tariff_title = customer.group.name if customer.group else "آزاد"
        session, created = GamingSession.objects.update_or_create(
            id=session_id,
            defaults={
                "edge_id": edge_id,
                "customer": customer,
                "device": device,
                "tariff_name": tariff_title,
                "hourly_rate": hourly_rate,
                "started_at": started_at,
                "ended_at": now,
                "elapsed_seconds": duration_seconds,
                "cost": final_cost,
                "discount_percent": discount_percent,
                "discount_amount": discount_amount,
                "discount_source": f"رهرو ({voucher_code or 'کوپن'})",
                "status": SessionStatus.COMPLETED,
                "end_reason": note[:120],
                "is_replica": True,
            }
        )

        # ۴. ثبت تراکنش‌های مالی دوبل (شارژ هزینه نشست + پرداخت نقدی هم‌ارز)
        charge_note = f"شارژ نشست باجه ({duration_minutes} دقیقه با تخفیف {discount_percent}٪)"
        payment_note = f"پرداخت نقدی/پوز باجه ({final_cost:,} تومان) بابت {voucher_code or 'تخفیف رهرو'}"

        if final_cost > 0:
            charge_entry = LedgerEntry.objects.filter(session=session, entry_type=LedgerEntryType.SESSION_CHARGE).first()
            if not charge_entry:
                wallet.balance -= final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=edge_id,
                    session=session,
                    entry_type=LedgerEntryType.SESSION_CHARGE,
                    amount=-final_cost,
                    balance_after=wallet.balance,
                    note=charge_note,
                    operator_label="سامانه رهرو",
                    is_replica=True,
                )

            deposit_entry = LedgerEntry.objects.filter(session=session, entry_type=LedgerEntryType.DEPOSIT).first()
            if not deposit_entry:
                wallet.balance += final_cost
                LedgerEntry.objects.create(
                    customer=customer,
                    edge_id=edge_id,
                    session=session,
                    entry_type=LedgerEntryType.DEPOSIT,
                    amount=final_cost,
                    balance_after=wallet.balance,
                    note=payment_note,
                    operator_label="سامانه رهرو",
                    is_replica=True,
                )
            wallet.save(update_fields=["balance"])

        # ۵. شارژ خودکار نرخ یا کیف پول در گیم‌نت بر مبنای ۱ ساعت بازی (CustomerRate / Wallet):
        from apps.pricing.models import CustomerRate
        disc_rate_amount = ((hourly_rate * discount_percent) + 50) // 100
        discounted_rate_1h = max(0, hourly_rate - disc_rate_amount)

        if discounted_rate_1h > 0:
            CustomerRate.objects.filter(customer=customer, is_default=True).update(is_default=False)
            rate_obj = CustomerRate.objects.filter(customer=customer, name__startswith="تخفیف کوپن رهرو").first()
            if rate_obj:
                rate_obj.name = f"تخفیف کوپن رهرو ({discount_percent}٪)"
                rate_obj.hourly_rate = discounted_rate_1h
                rate_obj.is_default = True
                rate_obj.is_active = True
                rate_obj.save(update_fields=["name", "hourly_rate", "is_default", "is_active", "updated_at"])
            else:
                CustomerRate.objects.create(
                    id=uuid.uuid4(),
                    edge_id=edge_id,
                    customer=customer,
                    name=f"تخفیف کوپن رهرو ({discount_percent}٪)",
                    hourly_rate=discounted_rate_1h,
                    is_default=True,
                    is_active=True,
                    is_replica=True,
                )
        elif discount_percent == 100:
            wallet.balance += hourly_rate
            wallet.save(update_fields=["balance"])
            LedgerEntry.objects.create(
                customer=customer,
                edge_id=edge_id,
                session=session,
                entry_type=LedgerEntryType.DEPOSIT,
                amount=hourly_rate,
                balance_after=wallet.balance,
                note="شارژ خودکار کیف پول بابت ۱ ساعت بازی رایگان کوپن رهرو (۱۰۰٪)",
                operator_label="سامانه رهرو",
                is_replica=True,
            )

        return Response({
            "success": True,
            "session_id": str(session.id),
            "customer_id": str(customer.id),
            "final_cost": final_cost,
            "discount_percent": discount_percent,
            "wallet_balance": wallet.balance,
            "message": f"نشست {duration_minutes} دقیقه‌ای با تخفیف {discount_percent}٪ و پرداخت {final_cost:,} تومان ثبت و تسویه شد.",
        })

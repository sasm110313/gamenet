from __future__ import annotations

import asyncio
import logging
import threading
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.clients.models import (
    ClientDevice,
    ClientStatus,
    ConnectionStatus,
    HealthStatus,
    KioskStatus,
    PowerStatus,
)
from apps.commands.models import DeviceCommand, DeviceCommandStatus
from apps.core.auth import authenticate_device_header
from apps.devices.services import get_client_update_info, handle_device_reconnect, set_status
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity

logger = logging.getLogger("gamenet.ws.device")

# A reconnect inside this window resumes the running session; anything slower is
# treated as an abandoned (zombie) session and is settled instead of resumed.
SESSION_RESUME_GRACE_SECONDS = 90

AUTH_TIMEOUT = 10
HUB_ONLY = {ClientStatus.ACTIVE, ClientStatus.IDLE, ClientStatus.STARTING, ClientStatus.STOPPING}
PUBLIC_STATES = {ClientStatus.LOCKED, ClientStatus.ONLINE, ClientStatus.ERROR}


class DeviceConsumer(AsyncJsonWebsocketConsumer):
    """Edge side of the LAN client connection."""

    async def connect(self):
        from apps.devices.remote_ws import register_asgi_loop

        register_asgi_loop(asyncio.get_running_loop())
        self.device: ClientDevice | None = None
        self.group: str | None = None
        self._shutdown_reported: bool = False
        self._last_update_push: float = 0.0
        await self.accept()
        self._auth_timer = asyncio.create_task(self._close_if_unauthenticated())

    async def _close_if_unauthenticated(self):
        await asyncio.sleep(AUTH_TIMEOUT)
        if self.device is None:
            await self.close(code=4401)

    async def disconnect(self, code):
        self._auth_timer.cancel()
        if self.device is not None:
            await database_sync_to_async(self._disconnect_if_owner)(code)
            if self.group:
                await self.channel_layer.group_discard(self.group, self.channel_name)
            await self.channel_layer.group_discard("gamenet_all_devices", self.channel_name)

    def _is_owner(self):
        return self.device is not None and ClientDevice.objects.filter(
            pk=self.device.pk, connection_owner=self.channel_name
        ).exists()

    @transaction.atomic
    def _disconnect_if_owner(self, code):
        device = ClientDevice.objects.select_for_update().get(pk=self.device.pk)
        if device.connection_owner != self.channel_name:
            return
        device.connection_owner = ""
        device.save(update_fields=["connection_owner"])
        set_status(
            device, ClientStatus.OFFLINE, force=True,
            connection_status=ConnectionStatus.OFFLINE,
            power_status=PowerStatus.OFF if self._shutdown_reported else PowerStatus.ON,
            bump_heartbeat=False, reason=f"ws closed {code}",
        )

    def _idle_shutdown_minutes(self):
        metadata = ClientDevice.objects.values_list("metadata", flat=True).get(pk=self.device.pk)
        return int((metadata or {}).get("idle_shutdown_minutes", current_config().get("idle_shutdown_minutes", 15)))

    def _active_session(self):
        from apps.sessions.models import GamingSession, SessionStatus

        return (
            GamingSession.objects.filter(device=self.device, status=SessionStatus.ACTIVE).first()
            if self.device
            else None
        )

    @staticmethod
    def _clean_choice(value, enum_cls):
        if value is None:
            return None
        text = str(value).strip().upper()
        return text if text in enum_cls.values else None

    async def receive_json(self, content, **kwargs):
        if self.device is None:
            await self._handshake(content)
            return
        if not await database_sync_to_async(self._is_owner)():
            await self.close(code=4409)
            return

        kind = content.get("type")
        if kind == "heartbeat":
            state = content.get("state")
            session_sync = await database_sync_to_async(self._heartbeat)(
                state,
                content.get("app_version", ""),
                str(content.get("mac_address", "")).strip(),
                kiosk_state=self._clean_choice(content.get("kiosk_state"), KioskStatus),
                power_state=self._clean_choice(content.get("power_state"), PowerStatus),
                health_status=self._clean_choice(content.get("health_status"), HealthStatus),
                health_message=content.get("health_message"),
            )
            client_games_hash = str(content.get("games_hash") or "")
            games_state = await database_sync_to_async(self._games_payload)(client_games_hash)
            idle_shutdown = await database_sync_to_async(self._idle_shutdown_minutes)()
            ack_payload = {
                "type": "heartbeat_ack",
                "server_time": timezone.now().isoformat(),
                "session_sync": session_sync,
                "idle_shutdown_minutes": idle_shutdown,
                "pending_commands": await database_sync_to_async(self._pending_commands)(),
                "games_hash": games_state["hash"],
            }
            if "games" in games_state:
                ack_payload["games"] = games_state["games"]
            import time
            now_ts = time.time()
            if now_ts - self._last_update_push > 300:
                update_info = await database_sync_to_async(get_client_update_info)()
                if update_info and update_info.get("version") != content.get("app_version"):
                    ack_payload["client_update"] = update_info
                    self._last_update_push = now_ts
            await self.send_json(ack_payload)
        elif kind == "command_ack":
            await database_sync_to_async(self._command_ack)(content)
        elif kind == "goodbye":
            power_state = self._clean_choice(content.get("power_state"), PowerStatus)
            kiosk_state = self._clean_choice(content.get("kiosk_state"), KioskStatus)
            if power_state == PowerStatus.OFF:
                self._shutdown_reported = True
            await database_sync_to_async(set_status)(
                self.device,
                ClientStatus.OFFLINE,
                force=True,
                connection_status=ConnectionStatus.OFFLINE,
                power_status=power_state or PowerStatus.ON,
                kiosk_status=kiosk_state,
                bump_heartbeat=False,
                reason=str(content.get("reason") or "client goodbye")[:60],
                connection_owner=self.channel_name,
            )
        elif kind == "state":
            state = content.get("state")
            kiosk_state = self._clean_choice(content.get("kiosk_state"), KioskStatus)
            power_state = self._clean_choice(content.get("power_state"), PowerStatus)
            health_status = self._clean_choice(content.get("health_status"), HealthStatus)
            health_message = content.get("health_message")
            if state in PUBLIC_STATES or any(x is not None for x in (kiosk_state, power_state, health_status, health_message)):
                await database_sync_to_async(set_status)(
                    self.device,
                    state if state in PUBLIC_STATES else None,
                    force=True,
                    connection_status=ConnectionStatus.ONLINE,
                    kiosk_status=kiosk_state,
                    power_status=power_state,
                    health_status=health_status,
                    health_message=health_message,
                    reason="client state",
                    connection_owner=self.channel_name,
                )
                await self.send_json({"type": "state_ack", "state": state})
        elif kind == "ping":
            await self.send_json({"type": "pong", "server_time": timezone.now().isoformat()})
        elif kind == "remote_frame":
            from apps.devices.remote_ws import remote_view_group, store_remote_frame
            from apps.synchronization.edge_ws import send_tunnel_message

            frame = store_remote_frame(self.device.id, content)
            await self.channel_layer.group_send(
                remote_view_group(self.device.id),
                {"type": "viewer.frame", "frame": frame},
            )
            send_tunnel_message(
                {
                    "type": "remote_frame",
                    "device_id": str(self.device.id),
                    "kind": frame["kind"],
                    "width": frame["width"],
                    "height": frame["height"],
                    "format": frame["format"],
                    "data": frame["data"],
                    "captured_at": frame["captured_at"],
                    "request_id": frame["request_id"],
                }
            )

    async def _handshake(self, content: dict) -> None:
        if content.get("type") != "hello":
            await self.close(code=4400)
            return
        header = f"Device {content.get('device_id', '')}.{content.get('token', '')}"
        device = await database_sync_to_async(authenticate_device_header)(header)
        if device is None:
            await self.close(code=4401)
            return

        self.device = device
        self.group = f"device_{device.id.hex}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.channel_layer.group_add("gamenet_all_devices", self.channel_name)

        desired, cfg = await database_sync_to_async(self._on_connect)(content)
        identity = await database_sync_to_async(ensure_identity)()
        games_state = await database_sync_to_async(self._games_payload)("")
        ann_state = await database_sync_to_async(self._announcements_payload)()
        update_info = await database_sync_to_async(get_client_update_info)()
        idle_shutdown = await database_sync_to_async(self._idle_shutdown_minutes)()
        try:
            active_session_payload = await database_sync_to_async(
                self._get_active_session_payload
            )()
        except Exception:
            logger.exception("failed to build active session payload; connecting without it")
            active_session_payload = None
        welcome_payload = {
            "type": "welcome",
            "device_id": str(device.id),
            "device_name": device.name,
            "hub_name": identity.name,
            "desired_state": desired,
            "heartbeat_seconds": cfg["device_heartbeat_seconds"],
            "offline_after_missed": cfg["device_offline_after_missed"],
            "config_version": cfg["version"],
            "idle_shutdown_minutes": idle_shutdown,
            "server_time": timezone.now().isoformat(),
            "pending_commands": await database_sync_to_async(self._pending_commands)(),
            "games": games_state.get("games", []),
            "games_hash": games_state["hash"],
            "announcements": ann_state.get("announcements", []),
            "announcements_hash": ann_state.get("hash", ""),
        }
        if active_session_payload:
            welcome_payload["session"] = active_session_payload
        if update_info and update_info.get("version") != content.get("app_version"):
            welcome_payload["client_update"] = update_info
        await self.send_json(welcome_payload)
        logger.info("device %s connected", device.name)

    def _games_payload(self, client_hash: str) -> dict:
        from apps.applications.services import get_games_catalog_state

        state = get_games_catalog_state()
        out = {"hash": state["hash"]}
        if not client_hash or client_hash != state["hash"]:
            out["games"] = state["games"]
        return out

    def _announcements_payload(self) -> dict:
        from apps.core.announcements import get_active_announcements, get_announcements_hash

        return {
            "announcements": get_active_announcements(),
            "hash": get_announcements_hash(),
        }

    def _get_active_session_payload(self) -> dict | None:
        from apps.core.locks import customer_mutex
        from apps.customers.models import Customer

        active = self._active_session()
        if active is None:
            return None
        with customer_mutex(active.customer_id), transaction.atomic():
            Customer.objects.select_for_update().get(pk=active.customer_id)
            return self._session_payload_locked()

    def _session_payload_locked(self) -> dict | None:
        from apps.sessions.models import GamingSession, SessionStatus

        if not self.device:
            return None
        active = (
            GamingSession.objects.filter(device=self.device, status=SessionStatus.ACTIVE)
            .select_related("customer", "customer__wallet")
            .first()
        )
        if not active:
            return None
        if self._abandoned_session_id and str(active.id) == self._abandoned_session_id:
            return None
        customer = active.customer
        wallet = getattr(customer, "wallet", None)
        balance = int(wallet.balance) if wallet else 0
        now = timezone.now()
        elapsed = active.billable_elapsed_seconds(now)
        cost, _ = active.calculate_cost(elapsed)
        return {
            "session_id": str(active.id),
            "customer_id": str(customer.id),
            "customer_name": customer.full_name or customer.username,
            "username": customer.username,
            "wallet_balance": balance,
            "remaining_balance": max(0, balance - sum(
                s.calculate_cost(s.billable_elapsed_seconds(now))[0]
                for s in GamingSession.objects.filter(customer=customer, status=SessionStatus.ACTIVE)
            )),
            "credit_limit": int(customer.credit_limit or 0),
            "hourly_rate": int(active.hourly_rate or 0),
            "normal_rate": int(active.hourly_rate or 0),
            "tariff_name": active.tariff_name or "",
            "started_at": active.started_at.isoformat() if active.started_at else now.isoformat(),
            "elapsed_seconds": elapsed,
            "paused_seconds": active.current_paused_seconds(now),
            "paused": active.paused_at is not None,
            "remaining_seconds": max(0, active.planned_duration_minutes * 60 - elapsed) if active.planned_duration_minutes else None,
            "billing_mode": active.billing_mode,
            "planned_duration_minutes": active.planned_duration_minutes,
            "disconnect_policy": active.disconnect_policy,
            "cost": cost,
            "server_time": now.isoformat(),
            "max_seconds": int((active.planned_duration_minutes or 0) * 60),
            "has_coupon": bool(active.coupon_hours),
            "coupon_hours": int(active.coupon_hours or 0),
            "coupon_hourly_rate": int(active.coupon_hourly_rate or 20000),
            "coupon_message": active.discount_source or "",
        }

    def _peer_ip(self) -> str | None:
        client = self.scope.get("client")
        if isinstance(client, (list, tuple)) and client and client[0]:
            return str(client[0])
        return None

    # -- sync helpers ------------------------------------------------------
    def _on_connect(self, content: dict) -> tuple[str, dict]:
        from django.db import transaction
        from apps.sessions.models import GamingSession, SessionStatus

        cfg = current_config()
        peer_ip = self._peer_ip()
        mac_address = str(content.get("mac_address", "")).strip()
        kiosk_state = self._clean_choice(content.get("kiosk_state"), KioskStatus)
        power_state = self._clean_choice(content.get("power_state"), PowerStatus) or PowerStatus.ON
        health_status = self._clean_choice(content.get("health_status"), HealthStatus) or HealthStatus.HEALTHY
        health_message = content.get("health_message")
        # Settle an abandoned session before taking the device write lock: stopping a
        # session writes a ledger entry, and doing that while holding the row lock
        # made the handshake wait on SQLite and time out.
        self._settle_abandoned_session()

        with transaction.atomic():
            device = ClientDevice.objects.select_for_update().get(pk=self.device.pk)
            device.connection_owner = self.channel_name
            device.save(update_fields=["connection_owner"])
            has_session = (
                False
                if self._abandoned_session_id
                else GamingSession.objects.filter(device=device, status=SessionStatus.ACTIVE).exists()
            )
            if device.status == ClientStatus.MAINTENANCE:
                desired = ClientStatus.MAINTENANCE
            elif has_session:
                desired = ClientStatus.ACTIVE
            else:
                persisted = device.status
                desired = (
                    persisted
                    if persisted not in {ClientStatus.OFFLINE, ClientStatus.ONLINE, ClientStatus.ERROR, ClientStatus.ACTIVE, ClientStatus.STARTING, ClientStatus.STOPPING, ClientStatus.IDLE}
                    else ClientStatus.LOCKED
                )
            set_status(
                device,
                desired,
                force=True,
                app_version=str(content.get("app_version", ""))[:40],
                ip_address=peer_ip,
                mac_address=mac_address,
                connection_status=ConnectionStatus.ONLINE,
                power_status=power_state,
                kiosk_status=kiosk_state,
                health_status=health_status,
                health_message="" if health_status == HealthStatus.HEALTHY else health_message,
                reason="websocket connected",
            )
            handle_device_reconnect(device)
        return desired, cfg

    _abandoned_session_id: str | None = None

    def _settle_abandoned_session(self) -> None:
        """Close an ACTIVE session the station left behind before it reconnects.

        A client that was silent for minutes was already stopped by the watchdog,
        so resuming it would unlock the PC with a stale, multi-hour timer.
        """
        from apps.sessions.models import DisconnectPolicy, GamingSession, SessionStatus

        if not self.device:
            return
        try:
            active = (
                GamingSession.objects.filter(device=self.device, status=SessionStatus.ACTIVE)
                .only("id", "started_at", "disconnect_policy", "connection_lost_at")
                .first()
            )
            if active is None:
                return
            if active.disconnect_policy != DisconnectPolicy.AUTO_STOP:
                return
            seen = self.device.last_heartbeat_at or active.started_at
            if (timezone.now() - (active.connection_lost_at or seen)).total_seconds() <= SESSION_RESUME_GRACE_SECONDS:
                return
            self._abandoned_session_id = str(active.id)
            session_id, end_at = active.id, min(seen, timezone.now())
        except Exception as exc:  # never block the handshake
            logger.warning("Could not inspect session for %s: %s", self.device, exc)
            return

        def _settle() -> None:
            from django.db import close_old_connections
            from apps.sessions.models import GamingSession
            from apps.sessions.services import stop_session

            try:
                stale = GamingSession.objects.filter(id=session_id, status=SessionStatus.ACTIVE).first()
                if stale is not None:
                    logger.info("settling abandoned session %s of %s", session_id, self.device)
                    stop_session(stale, reason="پایان نشست رهاشده پیش از اتصال دوباره کلاینت", at=end_at)
            except Exception as exc:
                logger.warning("Could not settle abandoned session %s: %s", session_id, exc)
            finally:
                close_old_connections()

        # Off the handshake path: the client must get its welcome immediately.
        threading.Thread(target=_settle, name="gamenet-settle-session", daemon=True).start()

    def _heartbeat(
        self,
        state: str | None,
        app_version: str,
        mac_address: str = "",
        *,
        kiosk_state: str | None = None,
        power_state: str | None = None,
        health_status: str | None = None,
        health_message: str | None = None,
    ) -> dict | None:
        if state in HUB_ONLY:
            state = None
        set_status(
            self.device,
            state,
            force=False,
            app_version=app_version,
            ip_address=self._peer_ip(),
            mac_address=mac_address,
            connection_status=ConnectionStatus.ONLINE,
            power_status=power_state or PowerStatus.ON,
            kiosk_status=kiosk_state,
            health_status=health_status,
            health_message=health_message,
            reason="heartbeat",
            connection_owner=self.channel_name,
        )

        from apps.sessions.models import GamingSession, SessionStatus
        from apps.sessions.services import enforce_active_session_policies

        session = (
            GamingSession.objects.filter(device=self.device, status=SessionStatus.ACTIVE)
            .select_related("customer", "customer__wallet")
            .first()
        )
        if not session:
            return None

        now = timezone.now()
        enforce_active_session_policies(now, customer_id=session.customer_id)
        payload = self._get_active_session_payload()
        return {**payload, "expired": False} if payload is not None else None

    def _pending_commands(self) -> list[dict]:
        now = timezone.now()
        return [
            {
                "command_id": str(cmd.id),
                "command_type": cmd.command_type,
                "payload": cmd.payload,
                "expires_at": cmd.expires_at.isoformat(),
            }
            for cmd in DeviceCommand.objects.filter(
                client_id=self.device.id,
                status=DeviceCommandStatus.PENDING,
                expires_at__gt=now,
            ).order_by("issued_at")[:20]
            if self._session_command_is_current(cmd.command_type, cmd.payload)
        ]

    def _session_command_is_current(self, command_type, payload):
        sid = (payload or {}).get("session_id")
        if not sid or command_type not in {"client.lock", "client.unlock"}:
            return True
        active = self._active_session()
        if command_type == "client.unlock":
            return active is not None and str(active.id) == str(sid)
        return active is None or str(active.id) == str(sid)

    def _command_ack(self, content: dict) -> None:
        from apps.synchronization.command_service import acknowledge_device_command

        acknowledge_device_command(
            self.device,
            content.get("command_id"),
            status=content.get("status", "ok"),
            result=content.get("result"),
            error=content.get("error", ""),
        )
        state = content.get("state")
        kiosk_state = self._clean_choice(content.get("kiosk_state"), KioskStatus)
        health_status = self._clean_choice(content.get("health_status"), HealthStatus)
        health_message = content.get("health_message")
        if state in PUBLIC_STATES or any(x is not None for x in (kiosk_state, health_status, health_message)):
            set_status(
                self.device,
                state if state in PUBLIC_STATES else None,
                force=True,
                kiosk_status=kiosk_state,
                health_status=health_status,
                health_message=health_message,
                reason="command ack",
                connection_owner=self.channel_name,
            )

    async def device_command(self, event):
        command = event["command"]
        if await database_sync_to_async(self._is_owner)() and await database_sync_to_async(
            self._session_command_is_current
        )(command.get("command_type"), command.get("payload")):
            await self.send_json({"type": "command", "command": event["command"]})

    async def device_games_updated(self, event):
        games_state = await database_sync_to_async(self._games_payload)("")
        ack = {
            "type": "heartbeat_ack",
            "server_time": timezone.now().isoformat(),
            "games_hash": games_state["hash"],
            "games": games_state.get("games", []),
        }
        gu = dict(ack)
        gu["type"] = "games_updated"
        await self.send_json(gu)

    async def device_announcements_updated(self, event):
        ann_state = await database_sync_to_async(self._announcements_payload)()
        msg = {
            "type": "announcements_updated",
            "announcements": ann_state.get("announcements", []),
            "announcements_hash": ann_state.get("hash", ""),
        }
        await self.send_json(msg)

    async def device_remote_control(self, event):
        payload = dict(event.get("payload") or {})
        payload["type"] = "remote_control"
        await self.send_json(payload)

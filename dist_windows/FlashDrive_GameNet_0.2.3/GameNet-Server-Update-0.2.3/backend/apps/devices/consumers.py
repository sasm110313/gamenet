from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
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
        await self.accept()
        self._auth_timer = asyncio.create_task(self._close_if_unauthenticated())

    async def _close_if_unauthenticated(self):
        await asyncio.sleep(AUTH_TIMEOUT)
        if self.device is None:
            await self.close(code=4401)

    async def disconnect(self, code):
        self._auth_timer.cancel()
        if self.device is not None:
            reported_power = PowerStatus.OFF if self._shutdown_reported else PowerStatus.ON
            await database_sync_to_async(set_status)(
                self.device,
                ClientStatus.OFFLINE,
                force=True,
                connection_status=ConnectionStatus.OFFLINE,
                power_status=reported_power,
                bump_heartbeat=False,
                reason=f"ws closed {code}",
            )
            if self.group:
                await self.channel_layer.group_discard(self.group, self.channel_name)
            await self.channel_layer.group_discard("gamenet_all_devices", self.channel_name)

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
            idle_shutdown = int(self.device.metadata.get("idle_shutdown_minutes", 15))
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
            update_info = await database_sync_to_async(get_client_update_info)()
            if update_info and update_info.get("version") != content.get("app_version"):
                ack_payload["client_update"] = update_info
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
        idle_shutdown = int(device.metadata.get("idle_shutdown_minutes", cfg.get("idle_shutdown_minutes", 15)))
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
        if update_info and update_info.get("version") != content.get("application_version"):
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
        with transaction.atomic():
            device = ClientDevice.objects.select_for_update().get(pk=self.device.pk)
            has_session = GamingSession.objects.filter(
                device=device, status=SessionStatus.ACTIVE
            ).exists()
            if device.status == ClientStatus.MAINTENANCE:
                desired = ClientStatus.MAINTENANCE
            elif has_session:
                desired = ClientStatus.ACTIVE
            else:
                persisted = device.status
                desired = (
                    persisted
                    if persisted not in {ClientStatus.OFFLINE, ClientStatus.ONLINE, ClientStatus.ERROR}
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
        )

        from apps.sessions.models import BillingMode, GamingSession, SessionStatus
        from apps.core.money import session_cost
        from apps.sessions.services import stop_session
        from apps.synchronization.command_service import queue_device_command

        session = (
            GamingSession.objects.filter(device=self.device, status=SessionStatus.ACTIVE)
            .select_related("customer", "customer__wallet")
            .first()
        )
        if not session:
            return None

        now = timezone.now()
        elapsed = session.billable_elapsed_seconds(now)
        cost = session_cost(session.hourly_rate, elapsed)
        wallet = getattr(session.customer, "wallet", None)
        balance = wallet.balance if wallet else 0

        # Check fixed-time expiry first
        remaining_time_seconds = None
        if session.billing_mode == BillingMode.TIMED and session.planned_duration_minutes:
            planned_total_seconds = session.planned_duration_minutes * 60
            remaining_time_seconds = max(0, planned_total_seconds - elapsed)
            if remaining_time_seconds <= 0:
                logger.info(
                    "Device %s timed session %s completed (%s/%s min).",
                    self.device.name,
                    session.id,
                    elapsed // 60,
                    session.planned_duration_minutes,
                )
                queue_device_command(self.device, "client.lock", {"reason": "پایان مدت زمان انتخاب‌شده نشست"})
                stop_session(session, reason="پایان مدت زمان انتخاب‌شده نشست")
                return {
                    "expired": True,
                    "expired_reason": "timed_finished",
                    "remaining_balance": max(0, balance - cost),
                    "elapsed_seconds": elapsed,
                    "remaining_seconds": 0,
                    "cost": cost,
                    "billing_mode": session.billing_mode,
                    "planned_duration_minutes": session.planned_duration_minutes,
                }

        # بدهی کلاً غیرمجاز است: سقف اعتبار منظور نمی‌شود
        available = balance - cost
        if available <= 0:
            logger.warning(
                "Device %s session %s wallet balance exhausted (%s <= 0). Stopping session.",
                self.device.name,
                session.id,
                available,
            )
            queue_device_command(self.device, "client.lock", {"reason": "اتمام موجودی کیف‌پول (بدهی مجاز نیست)"})
            stop_session(session, reason="اتمام خودکار موجودی کیف‌پول")
            return {
                "expired": True,
                "expired_reason": "balance_exhausted",
                "remaining_balance": 0,
                "elapsed_seconds": elapsed,
                "remaining_seconds": 0,
                "cost": cost,
                "billing_mode": session.billing_mode,
                "planned_duration_minutes": session.planned_duration_minutes,
            }

        return {
            "expired": False,
            "session_id": str(session.id),
            "customer_name": session.customer.full_name,
            "remaining_balance": max(0, balance - cost),
            "elapsed_seconds": elapsed,
            "paused_seconds": session.current_paused_seconds(now),
            "remaining_seconds": remaining_time_seconds,
            "billing_mode": session.billing_mode,
            "planned_duration_minutes": session.planned_duration_minutes,
            "disconnect_policy": session.disconnect_policy,
            "cost": cost,
        }

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
        ]

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
            )

    async def device_command(self, event):
        await self.send_json({"type": "command", "command": event["command"]})

    async def device_games_updated(self, event):
        games_state = await database_sync_to_async(self._games_payload)("")
        ack = {
            "type": "heartbeat_ack",
            "server_time": timezone.now().isoformat(),
            "games_hash": games_state["hash"],
            "games": games_state.get("games", []),
        }
        await self.send_json(ack)
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

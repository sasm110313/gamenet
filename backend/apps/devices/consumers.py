from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.utils import timezone

from apps.clients.models import ClientDevice, ClientStatus
from apps.commands.models import DeviceCommand, DeviceCommandStatus
from apps.core.auth import authenticate_device_header
from apps.devices.services import set_status
from apps.synchronization.config import current_config
from apps.synchronization.edge_credentials import ensure_identity

logger = logging.getLogger("gamenet.ws.device")

AUTH_TIMEOUT = 10
HUB_ONLY = {ClientStatus.ACTIVE, ClientStatus.IDLE, ClientStatus.STARTING, ClientStatus.STOPPING}
PUBLIC_STATES = {ClientStatus.LOCKED, ClientStatus.ONLINE, ClientStatus.ERROR}


class DeviceConsumer(AsyncJsonWebsocketConsumer):
    """Edge side of the LAN client connection."""

    async def connect(self):
        self.device: ClientDevice | None = None
        self.group: str | None = None
        await self.accept()
        self._auth_timer = asyncio.create_task(self._close_if_unauthenticated())

    async def _close_if_unauthenticated(self):
        await asyncio.sleep(AUTH_TIMEOUT)
        if self.device is None:
            await self.close(code=4401)

    async def disconnect(self, code):
        self._auth_timer.cancel()
        if self.device is not None:
            await database_sync_to_async(set_status)(
                self.device, ClientStatus.OFFLINE, force=True, reason=f"ws closed {code}"
            )
            if self.group:
                await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if self.device is None:
            await self._handshake(content)
            return

        kind = content.get("type")
        if kind == "heartbeat":
            state = content.get("state")
            session_sync = await database_sync_to_async(self._heartbeat)(state, content.get("app_version", ""))
            await self.send_json(
                {
                    "type": "heartbeat_ack",
                    "server_time": timezone.now().isoformat(),
                    "session_sync": session_sync,
                    "pending_commands": await database_sync_to_async(self._pending_commands)(),
                }
            )
        elif kind == "command_ack":
            await database_sync_to_async(self._command_ack)(content)
        elif kind == "state":
            state = content.get("state")
            if state in PUBLIC_STATES:
                await database_sync_to_async(set_status)(self.device, state, force=True, reason="client state")
                await self.send_json({"type": "state_ack", "state": state})
        elif kind == "ping":
            await self.send_json({"type": "pong", "server_time": timezone.now().isoformat()})

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

        desired, cfg = await database_sync_to_async(self._on_connect)(content)
        identity = await database_sync_to_async(ensure_identity)()
        await self.send_json(
            {
                "type": "welcome",
                "device_id": str(device.id),
                "device_name": device.name,
                "hub_name": identity.name,
                "desired_state": desired,
                "heartbeat_seconds": cfg["device_heartbeat_seconds"],
                "offline_after_missed": cfg["device_offline_after_missed"],
                "config_version": cfg["version"],
                "server_time": timezone.now().isoformat(),
                "pending_commands": await database_sync_to_async(self._pending_commands)(),
            }
        )
        logger.info("device %s connected", device.name)

    # -- sync helpers ------------------------------------------------------
    def _on_connect(self, content: dict) -> tuple[str, dict]:
        from django.db import transaction

        cfg = current_config()
        with transaction.atomic():
            device = ClientDevice.objects.select_for_update().get(pk=self.device.pk)
            persisted = device.status
            # A device that just came online has no session in Phase 0: it starts locked.
            desired = (
                persisted
                if persisted not in {ClientStatus.OFFLINE, ClientStatus.ONLINE}
                else ClientStatus.LOCKED
            )
            set_status(
                device,
                desired,
                force=True,
                app_version=str(content.get("app_version", ""))[:40],
                reason="websocket connected",
            )
        return desired, cfg

    def _heartbeat(self, state: str | None, app_version: str) -> dict | None:
        if state in HUB_ONLY:
            state = None
        set_status(self.device, state, force=False, app_version=app_version, reason="heartbeat")

        from apps.sessions.models import GamingSession, SessionStatus
        from apps.wallets.models import Wallet
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
        elapsed = max(0, int((now - session.started_at).total_seconds()))
        cost = session_cost(session.hourly_rate, elapsed)
        wallet = getattr(session.customer, "wallet", None)
        balance = wallet.balance if wallet else 0
        available = balance + session.customer.credit_limit - cost

        if available <= 0:
            logger.warning(
                "Device %s session %s credit exhausted (%s <= 0). Stopping session.",
                self.device.name,
                session.id,
                available,
            )
            queue_device_command(self.device, "client.lock", {"reason": "اتمام اعتبار حساب"})
            stop_session(session, reason="اتمام خودکار اعتبار")
            return {"expired": True, "remaining_balance": 0, "cost": cost}

        return {
            "expired": False,
            "session_id": str(session.id),
            "customer_name": session.customer.full_name,
            "remaining_balance": max(0, balance - cost),
            "elapsed_seconds": elapsed,
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
        if state in PUBLIC_STATES:
            set_status(self.device, state, force=True, reason="command ack")

    async def device_command(self, event):
        await self.send_json({"type": "command", "command": event["command"]})

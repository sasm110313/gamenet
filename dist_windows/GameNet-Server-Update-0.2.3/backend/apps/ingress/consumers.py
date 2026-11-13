from __future__ import annotations

import asyncio
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.utils import timezone

from apps.core.auth import authenticate_edge_header
from apps.ingress.telemetry import apply_device_telemetry, mark_edge_seen
from apps.synchronization.models import EdgeNode, EdgeStatus

logger = logging.getLogger("gamenet.ws.edge")

AUTH_TIMEOUT = 10


class EdgeConsumer(AsyncJsonWebsocketConsumer):
    """Cloud side of the edge tunnel. The edge authenticates in the first frame;
    the credential is never placed in the URL (it would land in access logs)."""

    async def connect(self):
        from apps.devices.remote_ws import register_asgi_loop

        register_asgi_loop(asyncio.get_running_loop())
        self.edge: EdgeNode | None = None
        self.group: str | None = None
        await self.accept()
        self._auth_timer = asyncio.create_task(self._close_if_unauthenticated())

    async def _close_if_unauthenticated(self):
        await asyncio.sleep(AUTH_TIMEOUT)
        if self.edge is None:
            await self.close(code=4401)

    async def disconnect(self, code):
        self._auth_timer.cancel()
        if self.edge is not None:
            await database_sync_to_async(self._mark_offline)()
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if self.edge is None:
            if content.get("type") != "hello":
                await self.close(code=4400)
                return
            header = f"Edge {content.get('edge_id', '')}.{content.get('secret', '')}"
            edge = await database_sync_to_async(authenticate_edge_header)(header)
            if edge is None:
                await self.close(code=4401)
                return
            self.edge = edge
            self.group = f"edge_{edge.id.hex}"
            await self.channel_layer.group_add(self.group, self.channel_name)
            await database_sync_to_async(mark_edge_seen)(edge)
            await self.send_json(
                {
                    "type": "welcome",
                    "edge_id": str(edge.id),
                    "server_time": timezone.now().isoformat(),
                    "heartbeat_seconds": settings.EDGE_HEARTBEAT_SECONDS,
                }
            )
            logger.info("edge %s connected over wss", edge.id)
            return

        kind = content.get("type")
        if kind == "ping":
            await self.send_json({"type": "pong", "server_time": timezone.now().isoformat()})
        elif kind == "heartbeat":
            devices = content.get("devices") or []
            if isinstance(devices, list):
                await database_sync_to_async(apply_device_telemetry)(self.edge, devices)
                await self.send_json({"type": "heartbeat_ack", "server_time": timezone.now().isoformat()})
        elif kind == "remote_frame":
            from apps.devices.remote_ws import (
                remote_view_group,
                store_remote_frame,
                verify_edge_owns_device,
            )

            device_id = content.get("device_id")
            if device_id and await database_sync_to_async(verify_edge_owns_device)(self.edge.id, device_id):
                frame = store_remote_frame(device_id, content)
                await self.channel_layer.group_send(
                    remote_view_group(device_id),
                    {"type": "viewer.frame", "frame": frame},
                )

    async def edge_command(self, event):
        await self.send_json({"type": "command", "command": event["command"]})

    async def edge_games_pushed(self, event):
        await self.send_json(
            {
                "type": "games_catalog_update",
                "games_catalog": event.get("games_catalog"),
                "games_version": event.get("games_version"),
                "games_hash": event.get("games_hash"),
            }
        )

    async def edge_remote_tunnel(self, event):
        await self.send_json(event["payload"])

    # -- sync helpers ------------------------------------------------------
    def _mark_offline(self):
        EdgeNode.objects.filter(pk=self.edge.pk).update(
            status=EdgeStatus.OFFLINE, last_seen_at=timezone.now()
        )

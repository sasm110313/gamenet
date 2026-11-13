from __future__ import annotations

import asyncio
import base64
import logging
import threading
import time
import uuid
from typing import Any

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache

from apps.clients.models import ClientDevice, ClientStatus

logger = logging.getLogger("gamenet.remote_ws")

_FRAME_CACHE_TTL = 300
_asgi_loop: asyncio.AbstractEventLoop | None = None
_waiters_lock = threading.Lock()
_screenshot_waiters: dict[str, list[dict[str, Any]]] = {}
_viewer_lock = threading.Lock()
_viewer_counts: dict[str, int] = {}
_ownership_cache: dict[tuple[str, str], float] = {}


def remote_view_group(device_id) -> str:
    return f"remote_view_{uuid.UUID(str(device_id)).hex}"


def register_asgi_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _asgi_loop
    _asgi_loop = loop


def dispatch_group_send(group: str, message: dict[str, Any]) -> None:
    """Safely send to a channel group from either the ASGI loop or a worker thread."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    loop = _asgi_loop
    if loop is not None and loop.is_running():
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            asyncio.create_task(channel_layer.group_send(group, message))
            return
        asyncio.run_coroutine_threadsafe(channel_layer.group_send(group, message), loop)
        return
    async_to_sync(channel_layer.group_send)(group, message)


def _frame_cache_key(device_id) -> str:
    return f"remote_latest_frame_{uuid.UUID(str(device_id)).hex}"


def store_remote_frame(device_id, content: dict[str, Any]) -> dict[str, Any]:
    dev_hex = uuid.UUID(str(device_id)).hex
    data = str(content.get("data") or "")
    frame = {
        "device_id": str(uuid.UUID(str(device_id))),
        "kind": str(content.get("kind") or "stream"),
        "width": int(content.get("width") or 0),
        "height": int(content.get("height") or 0),
        "format": str(content.get("format") or "jpeg"),
        "data": data,
        "captured_at": str(content.get("captured_at") or ""),
        "request_id": str(content.get("request_id") or ""),
        "received_at": time.time(),
    }
    cache.set(_frame_cache_key(dev_hex), frame, timeout=_FRAME_CACHE_TTL)

    with _waiters_lock:
        waiters = _screenshot_waiters.get(dev_hex)
        if waiters:
            req_id = frame["request_id"]
            for w in waiters:
                if not req_id or not w["request_id"] or w["request_id"] == req_id:
                    w["frame"] = frame
                    w["event"].set()
    return frame


def get_latest_remote_frame(device_id) -> dict[str, Any] | None:
    return cache.get(_frame_cache_key(device_id))


def request_screenshot_sync(
    device: ClientDevice, *, timeout: float = 8.0, width: int = 1280, quality: int = 84
) -> dict[str, Any] | None:
    """Request an immediate screenshot from a device and wait for the frame."""
    dev_hex = device.id.hex
    req_id = uuid.uuid4().hex
    waiter = {"request_id": req_id, "event": threading.Event(), "frame": None}

    with _waiters_lock:
        _screenshot_waiters.setdefault(dev_hex, []).append(waiter)

    try:
        sent = send_remote_control_sync(
            device,
            {
                "action": "screenshot",
                "request_id": req_id,
                "width": width,
                "quality": quality,
            },
        )
        if not sent:
            return None
        waiter["event"].wait(timeout=timeout)
        return waiter["frame"]
    finally:
        with _waiters_lock:
            lst = _screenshot_waiters.get(dev_hex)
            if lst and waiter in lst:
                lst.remove(waiter)
                if not lst:
                    _screenshot_waiters.pop(dev_hex, None)


def send_remote_control_sync(device: ClientDevice, payload: dict[str, Any]) -> bool:
    if device.status == ClientStatus.OFFLINE:
        return False
    if settings.GAMENET_ROLE == "cloud":
        group = f"edge_{uuid.UUID(str(device.edge_id)).hex}"
        dispatch_group_send(
            group,
            {
                "type": "edge.remote_tunnel",
                "payload": {
                    "type": "remote_tunnel",
                    "device_id": str(device.id),
                    "payload": payload,
                },
            },
        )
    else:
        group = f"device_{device.id.hex}"
        dispatch_group_send(
            group,
            {
                "type": "device.remote_control",
                "payload": payload,
            },
        )
    return True


def verify_edge_owns_device(edge_id, device_id) -> bool:
    key = (str(edge_id), str(device_id))
    now = time.time()
    cached = _ownership_cache.get(key)
    if cached and cached > now:
        return True
    exists = ClientDevice.objects.filter(id=device_id, edge_id=edge_id).exists()
    if exists:
        _ownership_cache[key] = now + 60.0
    return exists


def decode_frame_jpeg(frame: dict[str, Any]) -> bytes:
    return base64.b64decode(frame.get("data") or "")


class RemoteViewerConsumer(AsyncJsonWebsocketConsumer):
    """Browser-facing WebSocket for live screen viewing & remote desktop control."""

    async def connect(self):
        register_asgi_loop(asyncio.get_running_loop())
        user = self.scope.get("user")
        if not user or not user.is_authenticated or not user.is_active:
            await self.close(code=4401)
            return

        raw_id = self.scope["url_route"]["kwargs"].get("device_id")
        device = await database_sync_to_async(self._load_device)(raw_id)
        if device is None:
            await self.close(code=4404)
            return

        self.device_id = str(device.id)
        self.device_hex = device.id.hex
        self.edge_id = str(device.edge_id)
        self.group = remote_view_group(device.id)

        await self.accept()
        await self.channel_layer.group_add(self.group, self.channel_name)

        with _viewer_lock:
            _viewer_counts[self.device_hex] = _viewer_counts.get(self.device_hex, 0) + 1

        from apps.clients.models import ClientStatus, ConnectionStatus, PowerStatus
        from apps.devices.wol import is_lan_host_reachable

        is_connected = (device.connection_status == ConnectionStatus.ONLINE) and (device.status != ClientStatus.OFFLINE)
        lan_reachable = await database_sync_to_async(is_lan_host_reachable)(device.ip_address)

        await self.send_json(
            {
                "type": "viewer_ready",
                "device_id": self.device_id,
                "device_name": device.name,
                "status": device.status,
                "connection_status": device.connection_status,
                "power_status": device.power_status,
                "lan_reachable": lan_reachable,
                "ip_address": device.ip_address or "",
                "online": is_connected,
            }
        )

        latest = get_latest_remote_frame(self.device_id)
        if latest and latest.get("data"):
            await self.send_json({"type": "frame", "frame": latest})

        await self._forward_control(
            {"action": "stream_start", "width": 1024, "quality": 64, "fps": 5}
        )

    async def disconnect(self, code):
        if hasattr(self, "group") and self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)
        if hasattr(self, "device_hex"):
            remaining = 0
            with _viewer_lock:
                cur = _viewer_counts.get(self.device_hex, 0)
                remaining = max(0, cur - 1)
                if remaining == 0:
                    _viewer_counts.pop(self.device_hex, None)
                else:
                    _viewer_counts[self.device_hex] = remaining
            if remaining == 0:
                await self._forward_control({"action": "stream_stop"})

    async def receive_json(self, content, **kwargs):
        action = str(content.get("action") or "")
        if action == "screenshot":
            await self._forward_control(
                {
                    "action": "screenshot",
                    "request_id": str(content.get("request_id") or uuid.uuid4().hex),
                    "width": min(1920, max(640, int(content.get("width") or 1280))),
                    "quality": min(95, max(40, int(content.get("quality") or 84))),
                }
            )
        elif action == "stream_start":
            await self._forward_control(
                {
                    "action": "stream_start",
                    "width": min(1440, max(480, int(content.get("width") or 1024))),
                    "quality": min(90, max(35, int(content.get("quality") or 64))),
                    "fps": min(8, max(1, int(content.get("fps") or 5))),
                }
            )
        elif action == "stream_stop":
            await self._forward_control({"action": "stream_stop"})
        elif action == "ping":
            await self._forward_control({"action": "stream_keepalive"})
        elif action == "input":
            ev = content.get("event")
            if isinstance(ev, dict):
                await self._forward_control({"action": "input", "event": ev})

    async def viewer_frame(self, event):
        await self.send_json({"type": "frame", "frame": event["frame"]})

    async def _forward_control(self, payload: dict[str, Any]) -> None:
        if settings.GAMENET_ROLE == "cloud":
            await self.channel_layer.group_send(
                f"edge_{uuid.UUID(self.edge_id).hex}",
                {
                    "type": "edge.remote_tunnel",
                    "payload": {
                        "type": "remote_tunnel",
                        "device_id": self.device_id,
                        "payload": payload,
                    },
                },
            )
        else:
            await self.channel_layer.group_send(
                f"device_{self.device_hex}",
                {
                    "type": "device.remote_control",
                    "payload": payload,
                },
            )

    def _load_device(self, device_id) -> ClientDevice | None:
        return ClientDevice.objects.filter(id=device_id, is_active=True).first()

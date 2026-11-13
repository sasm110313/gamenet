"""WS client the edge runs in a background thread.

Only networking happens here; parsed commands are handed to the worker thread via
a queue, so all database work stays on one thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import ssl
import threading
from urllib.parse import urlparse

import certifi
import websockets
from django.conf import settings

from apps.synchronization.edge_credentials import EdgeCredentials
from apps.synchronization.sync_log import record_sync_log

logger = logging.getLogger("gamenet.edge_ws")

RECONNECT_BASE = 1.0
RECONNECT_CAP = 30.0

_client_lock = threading.Lock()
_active_client: "EdgeWebSocketClient | None" = None


def send_tunnel_message(payload: dict) -> bool:
    """Thread-safe push from Edge's device/HTTP handlers up to Cloud over WSS."""
    with _client_lock:
        client = _active_client
    if client is None or not client.connected.is_set():
        return False
    return client.enqueue_outbound(payload)


def is_ws_connected() -> bool:
    with _client_lock:
        client = _active_client
    return bool(client is not None and client.connected.is_set())


def websocket_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.netloc or parsed.path
    return f"{scheme}://{host}/ws/edge/"


class EdgeWebSocketClient(threading.Thread):
    daemon = True

    def __init__(self, creds: EdgeCredentials, command_queue: "queue.Queue[dict]"):
        super().__init__(name="edge-ws")
        self.creds = creds
        self.command_queue = command_queue
        self.connected = threading.Event()
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._out_queue: asyncio.Queue | None = None

    def stop(self) -> None:
        self._stop.set()

    def enqueue_outbound(self, payload: dict) -> bool:
        loop = self._loop
        out_q = self._out_queue
        if loop is None or out_q is None or not loop.is_running():
            return False

        def _put():
            if out_q.full():
                try:
                    out_q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                out_q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        try:
            loop.call_soon_threadsafe(_put)
            return True
        except RuntimeError:
            return False

    def run(self) -> None:  # pragma: no cover - integration path
        global _active_client
        with _client_lock:
            _active_client = self
        attempt = 0
        last_err = ""
        while not self._stop.is_set():
            try:
                asyncio.run(self._session())
                attempt = 0
                last_err = ""
            except Exception as exc:
                err_str = f"{type(exc).__name__}: {exc}"
                logger.warning("edge websocket disconnected: %s", err_str)
                if err_str != last_err:
                    record_sync_log("WARNING", "ws", f"قطع ارتباط WebSocket ابر: {err_str}", also_logger=False)
                    last_err = err_str
            finally:
                self.connected.clear()
                self._loop = None
                self._out_queue = None
            delay = min(RECONNECT_BASE * (2 ** min(attempt, 10)), RECONNECT_CAP)
            attempt = min(attempt + 1, 10)
            self._stop.wait(delay)

    async def _session(self) -> None:  # pragma: no cover - integration path
        from apps.devices.remote_ws import dispatch_group_send
        from apps.synchronization.command_service import device_group

        url = websocket_url(self.creds.base_url)
        cafile = settings.CLOUD_CA_BUNDLE or certifi.where()
        ssl_ctx = ssl.create_default_context(cafile=cafile)
        async with websockets.connect(
            url, ssl=ssl_ctx, open_timeout=10, ping_interval=20, ping_timeout=20, max_size=2**22
        ) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "edge_id": self.creds.edge_id,
                        "secret": self.creds.secret,
                        "software_version": settings.GAMENET_VERSION,
                    }
                )
            )
            welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if welcome.get("type") != "welcome":
                raise RuntimeError(f"unexpected handshake: {welcome.get('type')}")
            logger.info("edge websocket connected to %s", url)
            record_sync_log("INFO", "ws", f"اتصال زنده WebSocket با سرور آنلاین برقرار شد ({url})", also_logger=False)

            self._loop = asyncio.get_running_loop()
            self._out_queue = asyncio.Queue(maxsize=24)
            self.connected.set()

            # Instantly wake up the sync worker and clear offline backoff timers
            try:
                from apps.synchronization.daemon import trigger_sync_now
                from apps.synchronization.outbox import unblock_for_reconnect

                unblock_for_reconnect()
                trigger_sync_now()
                logger.info("Triggered instant outbox drain and sync on cloud reconnect.")
            except Exception as exc:
                logger.debug("Immediate reconnect sync trigger error: %s", exc)

            async def keepalive() -> None:
                while True:
                    await asyncio.sleep(20)
                    await self._out_queue.put({"type": "ping"})

            async def sender() -> None:
                while True:
                    item = await self._out_queue.get()
                    await ws.send(json.dumps(item))

            pinger = asyncio.create_task(keepalive())
            writer = asyncio.create_task(sender())
            try:
                while True:
                    message = json.loads(await ws.recv())
                    kind = message.get("type")
                    if kind == "command":
                        self.command_queue.put(message["command"])
                    elif kind == "games_catalog_update":
                        try:
                            from apps.applications.services import save_games_catalog
                            catalog = message.get("games_catalog")
                            version = message.get("games_version")
                            if isinstance(catalog, list):
                                save_games_catalog(catalog, version=version)
                        except Exception as exc:
                            logger.warning("Failed to apply pushed games catalog: %s", exc)
                    elif kind == "remote_tunnel":
                        dev_id = message.get("device_id")
                        if dev_id:
                            dispatch_group_send(
                                device_group(dev_id),
                                {
                                    "type": "device.remote_control",
                                    "payload": message.get("payload") or {},
                                },
                            )
                    elif kind == "pong":
                        continue
            finally:
                pinger.cancel()
                writer.cancel()

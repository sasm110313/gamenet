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

import websockets
from django.conf import settings

from apps.synchronization.edge_credentials import EdgeCredentials

logger = logging.getLogger("gamenet.edge_ws")

RECONNECT_BASE = 1.0
RECONNECT_CAP = 30.0


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

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # pragma: no cover - integration path
        attempt = 0
        while not self._stop.is_set():
            try:
                asyncio.run(self._session())
                attempt = 0
            except Exception as exc:
                logger.warning("edge websocket disconnected: %s", exc)
            finally:
                self.connected.clear()
            delay = min(RECONNECT_BASE * (2**attempt), RECONNECT_CAP)
            attempt += 1
            self._stop.wait(delay)

    async def _session(self) -> None:  # pragma: no cover - integration path
        url = websocket_url(self.creds.base_url)
        ssl_ctx = ssl.create_default_context(cafile=settings.CLOUD_CA_BUNDLE or None)
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
            self.connected.set()

            async def keepalive() -> None:
                while True:
                    await asyncio.sleep(20)
                    await ws.send(json.dumps({"type": "ping"}))

            pinger = asyncio.create_task(keepalive())
            try:
                while True:
                    message = json.loads(await ws.recv())
                    kind = message.get("type")
                    if kind == "command":
                        self.command_queue.put(message["command"])
                    elif kind == "pong":
                        continue
            finally:
                pinger.cancel()

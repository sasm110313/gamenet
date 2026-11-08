"""Background synchronization worker daemon for GameNet Salon Edge Server.

Runs outbox drain, cloud heartbeat, command ingestion, and config synchronization.
If offline, gracefully continues without blocking local operations.
"""

from __future__ import annotations

import logging
import queue
import threading

from django.conf import settings
from django.core.management import call_command
from django.db import close_old_connections

from apps.core.roles import require_edge
from apps.synchronization import command_service
from apps.synchronization.cloud_client import CloudClient
from apps.synchronization.edge_credentials import ensure_identity, is_registered, load_credentials
from apps.synchronization.edge_runtime import run_once
from apps.synchronization.edge_ws import EdgeWebSocketClient

logger = logging.getLogger("gamenet.sync_daemon")

_worker_started = False
_worker_lock = threading.Lock()
_stop_event = threading.Event()


def _sync_worker_loop():
    logger.info("GameNet Edge cloud synchronization worker started.")
    incoming: queue.Queue[dict] = queue.Queue()
    ws_client: EdgeWebSocketClient | None = None
    current_secret: str | None = None

    while not _stop_event.is_set():
        try:
            # Ensure DB connection is clean for this thread cycle
            close_old_connections()

            # 1. Check registration
            if not is_registered():
                reg_code = getattr(settings, "EDGE_REGISTRATION_CODE", None)
                if reg_code:
                    try:
                        call_command("edge_register", code=reg_code)
                    except Exception as exc:
                        logger.debug("Auto edge registration attempt: %s", exc)
                if not is_registered():
                    _stop_event.wait(10.0)
                    continue

            # 2. Check credentials & WebSocket client
            creds = load_credentials()
            if ws_client is None or current_secret != creds.secret:
                if ws_client is not None:
                    try:
                        ws_client.stop()
                    except Exception:
                        pass
                ws_client = EdgeWebSocketClient(creds, incoming)
                ws_client.start()
                current_secret = creds.secret
                logger.info("Cloud WebSocket listener connected to %s", creds.base_url)

            # 3. Process queued pushed commands from cloud WSS
            while True:
                try:
                    envelope = incoming.get_nowait()
                except queue.Empty:
                    break
                try:
                    command_service.receive_command(envelope)
                except Exception as exc:
                    logger.warning("Rejected cloud pushed command: %s", exc)

            # 4. Run worker cycle: outbox drain + heartbeat + config pull + local device offline check
            client = CloudClient(creds)
            try:
                run_once(client=client)
            except Exception as exc:
                logger.debug("Worker sync cycle exception (expected when offline): %s", exc)

        except Exception as exc:
            logger.debug("Unexpected error in sync daemon loop: %s", exc)
        finally:
            close_old_connections()

        interval = getattr(settings, "EDGE_SYNC_INTERVAL_SECONDS", 2)
        _stop_event.wait(interval)

    if ws_client is not None:
        try:
            ws_client.stop()
        except Exception:
            pass
    logger.info("GameNet Edge cloud synchronization worker stopped.")


def start_sync_daemon():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        t = threading.Thread(target=_sync_worker_loop, name="gamenet_cloud_sync_daemon", daemon=True)
        t.start()

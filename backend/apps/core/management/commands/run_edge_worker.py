"""The edge runtime: one process that owns the outbox, command queue and heartbeats.

Run under a Windows service wrapper (NSSM/WinSW) in production:
    python manage.py run_edge_worker

Exactly one instance must run per edge database. The outbox sequence allocation
and the in-process channel layer both assume a single worker.
"""

from __future__ import annotations

import logging
import queue
import signal
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.core.roles import require_edge
from apps.synchronization import command_service
from apps.synchronization.cloud_client import CloudClient
from apps.synchronization.edge_credentials import ensure_identity, is_registered, load_credentials
from apps.synchronization.edge_runtime import run_once
from apps.synchronization.edge_ws import EdgeWebSocketClient

logger = logging.getLogger("gamenet.worker")


class Command(BaseCommand):
    help = "Run the edge synchronization worker (outbox, commands, heartbeat, config)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
        parser.add_argument("--no-ws", action="store_true", help="disable the WSS listener (polling only)")
        parser.add_argument("--interval", type=float, default=None)

    def handle(self, *args, **options):
        require_edge()
        ensure_identity()
        interval = options["interval"] or settings.EDGE_SYNC_INTERVAL_SECONDS
        once = options["once"]
        incoming: queue.Queue[dict] = queue.Queue()
        ws_client: EdgeWebSocketClient | None = None
        current_secret: str | None = None
        stop = False

        def _stop(signum, frame):
            nonlocal stop
            stop = True

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        self.stdout.write(
            f"edge worker starting (interval={interval}s, ws={'off' if options['no_ws'] else 'on'})"
        )
        while not stop:
            registered = is_registered()
            if not registered:
                if settings.EDGE_REGISTRATION_CODE:
                    try:
                        call_command("edge_register", code=settings.EDGE_REGISTRATION_CODE)
                        registered = is_registered()
                    except Exception:
                        logger.exception("automatic edge registration failed")
                        if once:
                            raise
                if registered:
                    continue
                if once:
                    self.stdout.write("edge is not registered; nothing to do")
                    return
                time.sleep(interval)
                continue

            creds = load_credentials()
            if (
                not options["no_ws"]
                and (ws_client is None or current_secret != creds.secret)
            ):
                if ws_client is not None:
                    ws_client.stop()
                ws_client = EdgeWebSocketClient(creds, incoming)
                ws_client.start()
                current_secret = creds.secret
                self.stdout.write("websocket listener started")

            while True:
                try:
                    envelope = incoming.get_nowait()
                except queue.Empty:
                    break
                try:
                    command_service.receive_command(envelope)
                except Exception as exc:
                    logger.warning("rejected pushed command: %s", exc)

            client = CloudClient(creds)
            try:
                stats = run_once(client=client)
                if once:
                    self.stdout.write(self.style.SUCCESS(f"cycle ok: {stats}"))
            except Exception as exc:
                logger.exception("worker cycle failed: %s", exc)
                if once:
                    raise
            if once:
                return
            time.sleep(interval)

        if ws_client is not None:
            ws_client.stop()
        self.stdout.write("edge worker stopped")

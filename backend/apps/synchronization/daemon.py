"""Background synchronization worker daemon for GameNet Salon Edge Server.

Runs outbox drain, cloud heartbeat, command ingestion, and config synchronization.
If offline, gracefully continues without blocking local operations.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading

from django.conf import settings
from django.core.management import call_command
from django.db import close_old_connections

from apps.core.roles import require_edge
from apps.synchronization import command_service
from apps.synchronization.cloud_client import CloudClient
from apps.synchronization.edge_credentials import is_registered, load_credentials
from apps.synchronization.edge_runtime import run_once
from apps.synchronization.edge_ws import EdgeWebSocketClient
from apps.synchronization.sync_log import record_sync_log

logger = logging.getLogger("gamenet.sync_daemon")

_worker_started = False
_worker_lock = threading.Lock()
_stop_event = threading.Event()
_sync_trigger = threading.Event()


def trigger_sync_now() -> None:
    """Wake the synchronization worker immediately without waiting for interval."""
    _sync_trigger.set()


def _local_watchdog_loop():
    from apps.devices.services import mark_stale_devices_offline
    from apps.sessions.services import enforce_active_session_policies

    if _is_edge_server_process():
        try:
            from apps.sessions.services import reconcile_orphaned_sessions
            reconcile_orphaned_sessions()
        except Exception:
            logger.exception("Session recovery initialization failed")
    while not _stop_event.is_set():
        try:
            mark_stale_devices_offline(probe=False)
            enforce_active_session_policies()
        except Exception:
            logger.exception("Local session watchdog failed")
        finally:
            close_old_connections()
        _stop_event.wait(2)


def _is_edge_server_process() -> bool:
    """Only the real ASGI server may reconcile sessions at startup.

    Management commands, shells or test scripts must never end a live session.
    """
    if str(getattr(settings, "GAMENET_ROLE", "edge")) != "edge":
        return False
    argv = " ".join(sys.argv)
    return any(name in argv for name in ("uvicorn", "daphne", "hypercorn"))


def _sync_worker_loop():
    record_sync_log(
        "INFO",
        "daemon",
        f"سرویس همگام‌سازی ابر شروع به کار کرد (مقصد: {settings.CLOUD_BASE_URL or 'تنظیم‌نشده'})",
    )
    incoming: queue.Queue[dict] = queue.Queue()
    ws_client: EdgeWebSocketClient | None = None
    current_credentials = None
    last_status_key = ""

    while not _stop_event.is_set():
        try:
            # Ensure DB connection is clean for this thread cycle
            close_old_connections()

            # 1. Check registration
            if not is_registered():
                if ws_client is not None:
                    try:
                        ws_client.stop()
                    except Exception:
                        pass
                    ws_client = None
                    current_credentials = None
                reg_code = (getattr(settings, "EDGE_REGISTRATION_CODE", "") or "").strip()
                if reg_code:
                    try:
                        call_command("edge_register", code=reg_code)
                        record_sync_log("INFO", "register", "ثبت خودکار Edge با کد تنظیم‌شده انجام شد.")
                    except Exception as exc:
                        err_key = f"reg_err:{exc}"
                        if err_key != last_status_key:
                            record_sync_log("ERROR", "register", f"خطا در ثبت خودکار Edge: {exc}")
                            last_status_key = err_key
                if not is_registered():
                    unreg_key = "unregistered"
                    if last_status_key != unreg_key:
                        record_sync_log(
                            "WARNING",
                            "register",
                            "این سرور محلی هنوز در سرور آنلاین ثبت نشده است (فایل credential موجود نیست). از پنل محلی بخش «همگام‌سازی ابر» کد ثبت را وارد کنید.",
                        )
                        last_status_key = unreg_key
                    try:
                        from apps.devices.services import mark_stale_devices_offline
                        from apps.sessions.services import enforce_active_session_policies

                        mark_stale_devices_offline()
                        enforce_active_session_policies()
                    except Exception as exc:
                        logger.warning("Offline local watchdog cycle error: %s", exc)
                    _sync_trigger.wait(timeout=5.0)
                    _sync_trigger.clear()
                    continue

            # 2. Check credentials & WebSocket client
            creds = load_credentials()
            if ws_client is None or current_credentials != creds:
                if ws_client is not None:
                    try:
                        ws_client.stop()
                    except Exception:
                        pass
                ws_client = EdgeWebSocketClient(creds, incoming)
                ws_client.start()
                current_credentials = creds
                record_sync_log("INFO", "ws", f"شروع اتصال WebSocket به {creds.base_url} (Edge ID: {creds.edge_id})")

            # 3. Process queued pushed commands from cloud WSS
            while True:
                try:
                    envelope = incoming.get_nowait()
                except queue.Empty:
                    break
                try:
                    command_service.receive_command(envelope)
                except Exception as exc:
                    record_sync_log("WARNING", "command", f"فرمان ارسالی از ابر رد شد: {exc}")

            # 4. Run worker cycle: outbox drain + heartbeat + config pull + local device offline check
            client = CloudClient(creds)
            try:
                res = run_once(client=client)
                hb_err = (res.get("heartbeat") or {}).get("error") if isinstance(res.get("heartbeat"), dict) else None
                cmd_err = res.get("command_pull_error")
                cfg_err = (res.get("config") or {}).get("error") if isinstance(res.get("config"), dict) else None
                outbox_err = (res.get("outbox") or {}).get("error")
                first_err = hb_err or cmd_err or cfg_err or outbox_err or res.get("seed_error")
                if first_err:
                    err_key = f"sync_err:{first_err}"
                    if err_key != last_status_key:
                        record_sync_log("WARNING", "heartbeat", f"خطا در ارتباط با سرور آنلاین: {first_err}")
                        last_status_key = err_key
                elif res.get("heartbeat"):
                    if last_status_key != "online":
                        record_sync_log("INFO", "heartbeat", f"ارتباط و همگام‌سازی با سرور آنلاین ({creds.base_url}) برقرار شد.")
                        last_status_key = "online"
            except Exception as exc:
                err_key = f"cycle_err:{exc}"
                if err_key != last_status_key:
                    record_sync_log("ERROR", "daemon", f"خطای چرخه همگام‌سازی: {exc}")
                    last_status_key = err_key
            finally:
                client.close()

        except Exception as exc:
            err_key = f"loop_err:{exc}"
            if err_key != last_status_key:
                record_sync_log("ERROR", "daemon", f"خطای پیش‌بینی‌نشده در سرویس همگام‌سازی: {exc}")
                last_status_key = err_key
        finally:
            close_old_connections()

        interval = getattr(settings, "EDGE_SYNC_INTERVAL_SECONDS", 2)
        # Sleep until next periodic interval or wake immediately upon trigger
        _sync_trigger.wait(timeout=interval)
        _sync_trigger.clear()

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
        threading.Thread(target=_local_watchdog_loop, name="gamenet_local_watchdog", daemon=True).start()
        t = threading.Thread(target=_sync_worker_loop, name="gamenet_cloud_sync_daemon", daemon=True)
        t.start()

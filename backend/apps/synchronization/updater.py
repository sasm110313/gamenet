from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings
from apps.core.roles import require_edge
from apps.synchronization.models import EdgeIdentity

logger = logging.getLogger("gamenet.updater")


def trigger_edge_update(version: str, download_url: str, expected_sha256: str = "") -> dict[str, Any]:
    """Downloads update package from Cloud and runs in-place service update in a detached process."""
    require_edge()
    identity = EdgeIdentity.get_solo()

    if not download_url.startswith("http://") and not download_url.startswith("https://"):
        base = (identity.cloud_base_url or "").rstrip("/")
        download_url = f"{base}/{download_url.lstrip('/')}"

    logger.info("Scheduling Edge in-place update to v%s from %s", version, download_url)

    def _worker():
        try:
            temp_dir = Path(tempfile.gettempdir())
            zip_dest = temp_dir / "gamenet_server_update.zip"

            logger.info("Downloading server update from %s to %s", download_url, zip_dest)
            urllib.request.urlretrieve(download_url, zip_dest)

            if expected_sha256:
                h = hashlib.sha256()
                with open(zip_dest, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                calc_sha = h.hexdigest().lower()
                if calc_sha != expected_sha256.lower().strip():
                    logger.error("Update SHA-256 mismatch! Expected %s got %s", expected_sha256, calc_sha)
                    return

            if os.name == "nt":
                install_dir = r"C:\Program Files\GameNet Server"
                bat_path = temp_dir / "apply_server_update.bat"
                bat_content = f"""@echo off
chcp 65001 >nul
title GameNet Server In-Place Updater
echo [%date% %time%] Waiting for running server to release locks...
ping -n 3 127.0.0.1 >nul

net stop GameNetServer >nul 2>&1
taskkill /F /IM GameNet_Server.exe /T >nul 2>&1
taskkill /F /IM GameNet_Service.exe /T >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq GameNet*" /T >nul 2>&1
ping -n 2 127.0.0.1 >nul

echo [%date% %time%] Extracting update package...
powershell -Command "Expand-Archive -Path '{zip_dest}' -DestinationPath '{temp_dir}\\gamenet_update_extracted' -Force"

set "EXT_DIR={temp_dir}\\gamenet_update_extracted\\GameNet-Server-Update-{version}"
if not exist "%EXT_DIR%" set "EXT_DIR={temp_dir}\\gamenet_update_extracted"

echo [%date% %time%] Applying files to {install_dir}...
robocopy "%EXT_DIR%\\backend" "{install_dir}\\backend" /E /XD data __pycache__ /XF *.sqlite3* *.db *.log .env /R:1 /W:1 >nul 2>&1
robocopy "%EXT_DIR%\\deploy" "{install_dir}\\deploy" /E /XD python __pycache__ /R:1 /W:1 >nul 2>&1
if exist "%EXT_DIR%\\python-deps" (
    robocopy "%EXT_DIR%\\python-deps" "{install_dir}\\deploy\\windows\\python\\Lib\\site-packages" /E /R:1 /W:1 >nul 2>&1
    if errorlevel 8 exit /b 1
)
copy /y "%EXT_DIR%\\GameNet_Server.exe" "{install_dir}\\" >nul 2>&1
copy /y "%EXT_DIR%\\GameNet_Service.exe" "{install_dir}\\" >nul 2>&1
copy /y "%EXT_DIR%\\GameNet_Server.bat" "{install_dir}\\" >nul 2>&1
copy /y "%EXT_DIR%\\Open_Admin_Panel.bat" "{install_dir}\\" >nul 2>&1
copy /y "%EXT_DIR%\\change_admin_credentials.bat" "{install_dir}\\" >nul 2>&1

echo [%date% %time%] Running database migrations...
cd /d "{install_dir}\\backend"
set "GAMENET_ROLE=edge"
set "DJANGO_SETTINGS_MODULE=gamenet.settings.edge"
set "PYTHONUTF8=1"
"{install_dir}\\deploy\\windows\\python\\python.exe" manage.py migrate --noinput
if errorlevel 1 exit /b 1
"{install_dir}\\deploy\\windows\\python\\python.exe" manage.py collectstatic --noinput >nul 2>&1

echo [%date% %time%] Restarting GameNetServer Windows service...
net start GameNetServer >nul 2>&1
if errorlevel 1 (
    "{install_dir}\\GameNet_Service.exe" --ensure-running
)
echo [%date% %time%] Update complete!
exit
"""
                bat_path.write_bytes(bat_content.replace("\n", "\r\n").encode("utf-8"))
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=DETACHED_PROCESS, close_fds=True)
            else:
                logger.info("Server update package downloaded to %s (non-windows OS)", zip_dest)
        except Exception as exc:
            logger.exception("Failed executing server update worker: %s", exc)

    # Launch worker in background thread with 2s initial delay so caller can return HTTP 200/ack first
    timer = threading.Timer(2.0, _worker)
    timer.daemon = True
    timer.start()

    return {
        "status": "updating",
        "version": version,
        "message": f"فرمان آپدیت خودکار سرور سالن به نسخه {version} دریافت شد. سرور طی لحظاتی دیگر بازنشانی و به‌روزرسانی می‌شود.",
    }


def trigger_client_updates(version: str = "", asar_url: str = "", sha256: str = "") -> dict[str, Any]:
    """Syncs latest client update file from Cloud if needed, and pushes update command to all active client devices."""
    require_edge()
    from apps.clients.models import ClientDevice
    from apps.devices.services import queue_device_command

    identity = EdgeIdentity.get_solo()
    base_cloud = (identity.cloud_base_url or "").rstrip("/")

    # If asar_url is remote or not provided, fetch latest client manifest from Cloud
    local_static = getattr(settings, "STATICFILES_DIRS", [None])[0] or (settings.BASE_DIR / "static")
    updates_dir = Path(local_static) / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    local_asar = updates_dir / "app.asar"

    if not version or not sha256:
        try:
            import json
            manifest_url = f"{base_cloud}/static/updates/latest.json"
            req = urllib.request.Request(manifest_url, headers={"User-Agent": "GameNet-Edge/0.2.3"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                version = str(data.get("version") or version)
                sha256 = str(data.get("sha256") or sha256)
                remote_asar = data.get("url") or "/static/updates/app.asar"
                if not remote_asar.startswith("http"):
                    remote_asar = f"{base_cloud}/{remote_asar.lstrip('/')}"
                logger.info("Downloading new client app.asar from %s", remote_asar)
                urllib.request.urlretrieve(remote_asar, local_asar)
        except Exception as exc:
            logger.debug("Could not refresh client manifest from cloud: %s", exc)

    version = version or "0.2.3"
    client_url = "/static/updates/app.asar"

    devices = ClientDevice.objects.filter(is_active=True)
    queued_count = 0
    for device in devices:
        try:
            queue_device_command(
                device,
                "client.update",
                {
                    "version": version,
                    "url": client_url,
                    "sha256": sha256,
                },
            )
            queued_count += 1
        except Exception as exc:
            logger.warning("Failed queuing update for %s: %s", device.name, exc)

    return {
        "status": "ok",
        "queued_count": queued_count,
        "version": version,
        "message": f"فرمان بروزرسانی به {queued_count} سیستم کلاینت سالن ارسال شد.",
    }

#!/usr/bin/env python3
"""Prepare clean CRLF Windows scripts and build GameNet-Server-<version>-Setup.exe via NSIS."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
DEPLOY_WIN_DIR = ROOT_DIR / "deploy" / "windows"
DIST_DIR = ROOT_DIR / "dist_windows"
STAGING_DIR = ROOT_DIR / ".artifacts" / "build" / "server_installer"
NSIS_BIN = Path.home() / ".cache" / "electron-builder" / "nsis" / "nsis-3.0.4.1" / "linux" / "makensis"
VERSION = "0.2.10"


def write_crlf(path: Path, text: str) -> None:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    if not normalized.endswith("\r\n"):
        normalized += "\r\n"
    path.write_bytes(normalized.encode("utf-8"))


def normalize_existing_crlf(path: Path) -> None:
    if not path.is_file():
        return
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    write_crlf(path, text)


def write_fixed_batch_scripts() -> None:
    # 1. GameNet_Server.bat & Open_Admin_Panel.bat (identical reliable launcher)
    open_panel_bat = r"""@echo off
title GameNet Salon Server - Admin Panel
setlocal enabledelayedexpansion

if exist "%~dp0backend\manage.py" (
    set "ROOT_DIR=%~dp0"
) else if exist "%~dp0..\..\backend\manage.py" (
    set "ROOT_DIR=%~dp0..\.."
) else (
    echo [ERROR] Could not locate GameNet backend directory.
    pause
    exit /b 1
)
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

if exist "%ROOT_DIR%\GameNet_Server.exe" (
    start "" "%ROOT_DIR%\GameNet_Server.exe"
    exit /b 0
)
if exist "%ROOT_DIR%\deploy\windows\GameNet_Server.exe" (
    start "" "%ROOT_DIR%\deploy\windows\GameNet_Server.exe"
    exit /b 0
)

if exist "%ROOT_DIR%\GameNet_Service.exe" (
    "%ROOT_DIR%\GameNet_Service.exe" --ensure-running
) else if exist "%ROOT_DIR%\deploy\windows\GameNet_Service.exe" (
    "%ROOT_DIR%\deploy\windows\GameNet_Service.exe" --ensure-running
)

set "SERVER_URL=https://127.0.0.1:19443/"
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app="%SERVER_URL%" --ignore-certificate-errors --allow-insecure-localhost --no-first-run
    exit /b 0
)
if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files\Microsoft\Edge\Application\msedge.exe" --app="%SERVER_URL%" --ignore-certificate-errors --allow-insecure-localhost --no-first-run
    exit /b 0
)
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app="%SERVER_URL%" --ignore-certificate-errors --allow-insecure-localhost --no-first-run
    exit /b 0
)
start "" "%SERVER_URL%"
exit /b 0
"""

    install_bat = r"""@echo off
chcp 65001 >nul
title GameNet Salon Server - Setup
setlocal enabledelayedexpansion

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Administrator privileges are required.
    echo Please right-click this file and select "Run as administrator".
    echo.
    pause
    exit /b 1
)

if exist "%~dp0backend\manage.py" (
    set "ROOT_DIR=%~dp0"
) else if exist "%~dp0..\..\backend\manage.py" (
    set "ROOT_DIR=%~dp0..\.."
) else (
    echo [ERROR] Could not locate GameNet backend directory.
    pause
    exit /b 1
)
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

set "SVC_EXE=%ROOT_DIR%\GameNet_Service.exe"
if not exist "%SVC_EXE%" set "SVC_EXE=%ROOT_DIR%\deploy\windows\GameNet_Service.exe"

if exist "%SVC_EXE%" (
    "%SVC_EXE%" --setup
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Server setup failed. Check "%ROOT_DIR%\backend\data\setup.log".
        pause
        exit /b %errorlevel%
    )
    if exist "%ROOT_DIR%\GameNet_Server.exe" (
        start "" "%ROOT_DIR%\GameNet_Server.exe"
    ) else if exist "%ROOT_DIR%\deploy\windows\GameNet_Server.exe" (
        start "" "%ROOT_DIR%\deploy\windows\GameNet_Server.exe"
    )
    echo.
    echo Setup completed successfully!
    pause
    exit /b 0
)

echo [ERROR] GameNet_Service.exe not found in "%ROOT_DIR%".
pause
exit /b 1
"""

    change_admin_bat = r"""@echo off
chcp 65001 >nul
title GameNet Salon Server - Change Admin Credentials
setlocal enabledelayedexpansion

if exist "%~dp0backend\manage.py" (
    set "ROOT_DIR=%~dp0"
) else if exist "%~dp0..\..\backend\manage.py" (
    set "ROOT_DIR=%~dp0..\.."
) else (
    echo [ERROR] Could not locate GameNet root directory.
    pause
    exit /b 1
)
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

set "SVC_EXE=%ROOT_DIR%\GameNet_Service.exe"
if not exist "%SVC_EXE%" set "SVC_EXE=%ROOT_DIR%\deploy\windows\GameNet_Service.exe"

if exist "%SVC_EXE%" (
    "%SVC_EXE%" --change-admin %*
) else (
    set "PY_EXE=%ROOT_DIR%\deploy\windows\python\python.exe"
    if not exist "%PY_EXE%" set "PY_EXE=%ROOT_DIR%\backend\.venv\Scripts\python.exe"
    if not exist "%PY_EXE%" set "PY_EXE=python.exe"
    cd /d "%ROOT_DIR%\backend"
    set "GAMENET_ROLE=edge"
    set "DJANGO_SETTINGS_MODULE=gamenet.settings.edge"
    set "PYTHONUTF8=1"
    "%PY_EXE%" manage.py change_admin %*
)

echo.
pause
"""

    uninstall_bat = r"""@echo off
chcp 65001 >nul
title GameNet Salon Server - Uninstall Service
setlocal enabledelayedexpansion

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Administrator privileges are required.
    echo Please right-click and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

if exist "%~dp0backend\manage.py" (
    set "ROOT_DIR=%~dp0"
) else if exist "%~dp0..\..\backend\manage.py" (
    set "ROOT_DIR=%~dp0..\.."
) else (
    echo [ERROR] Could not locate GameNet root directory.
    pause
    exit /b 1
)
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

if exist "%ROOT_DIR%\Uninstall.exe" (
    start "" "%ROOT_DIR%\Uninstall.exe"
    exit /b 0
)

set /p "CONFIRM=Remove GameNetServer Windows service and background tasks? [Y/N]: "
if /i not "!CONFIRM!"=="Y" exit /b 0

set "SVC_EXE=%ROOT_DIR%\GameNet_Service.exe"
if not exist "%SVC_EXE%" set "SVC_EXE=%ROOT_DIR%\deploy\windows\GameNet_Service.exe"
if exist "%SVC_EXE%" (
    "%SVC_EXE%" --uninstall
)
sc.exe stop GameNetServer >nul 2>&1
sc.exe delete GameNetServer >nul 2>&1
taskkill /f /im GameNet_Server.exe >nul 2>&1
echo Service and scheduled tasks removed.
pause
"""

    watchdog_bat = r"""@echo off
setlocal
if exist "%~dp0backend\manage.py" (
    set "ROOT_DIR=%~dp0"
) else if exist "%~dp0..\..\backend\manage.py" (
    set "ROOT_DIR=%~dp0..\.."
) else (
    exit /b 1
)
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

if exist "%ROOT_DIR%\GameNet_Service.exe" (
    "%ROOT_DIR%\GameNet_Service.exe" --ensure-running
    exit /b %errorlevel%
)
if exist "%ROOT_DIR%\deploy\windows\GameNet_Service.exe" (
    "%ROOT_DIR%\deploy\windows\GameNet_Service.exe" --ensure-running
    exit /b %errorlevel%
)
exit /b 0
"""

    for target_dir in (ROOT_DIR, DEPLOY_WIN_DIR):
        write_crlf(target_dir / "GameNet_Server.bat", open_panel_bat)
        write_crlf(target_dir / "Open_Admin_Panel.bat", open_panel_bat)
        write_crlf(target_dir / "Install_GameNet_Server.bat", install_bat)
        write_crlf(target_dir / "change_admin_credentials.bat", change_admin_bat)
        write_crlf(target_dir / "Uninstall_GameNet_Server.bat", uninstall_bat)

    write_crlf(DEPLOY_WIN_DIR / "watchdog_server.bat", watchdog_bat)

    # Ensure every remaining .bat and .vbs is strict Windows CRLF
    for p in list(ROOT_DIR.glob("*.bat")) + list(DEPLOY_WIN_DIR.glob("*.bat")) + list(DEPLOY_WIN_DIR.glob("*.vbs")):
        normalize_existing_crlf(p)


def build_go_binaries() -> None:
    launcher_dir = DEPLOY_WIN_DIR / "launcher"
    env = os.environ.copy()
    env["GOOS"] = "windows"
    env["GOARCH"] = "amd64"
    env["CGO_ENABLED"] = "0"

    subprocess.run(
        ["go", "build", "-ldflags", "-s -w", "-o", str(DEPLOY_WIN_DIR / "GameNet_Service.exe"), "./cmd/service"],
        cwd=launcher_dir,
        env=env,
        check=True,
    )
    subprocess.run(
        ["go", "build", "-ldflags", "-s -w -H windowsgui", "-o", str(DEPLOY_WIN_DIR / "GameNet_Server.exe"), "."],
        cwd=launcher_dir,
        env=env,
        check=True,
    )
    shutil.copy2(DEPLOY_WIN_DIR / "GameNet_Server.exe", ROOT_DIR / "GameNet_Server.exe")


def copy_clean_tree() -> None:
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    # Top-level executables and fixed CRLF helpers
    shutil.copy2(DEPLOY_WIN_DIR / "GameNet_Server.exe", STAGING_DIR / "GameNet_Server.exe")
    shutil.copy2(DEPLOY_WIN_DIR / "GameNet_Service.exe", STAGING_DIR / "GameNet_Service.exe")
    for fname in (
        "GameNet_Server.bat",
        "Open_Admin_Panel.bat",
        "Install_GameNet_Server.bat",
        "change_admin_credentials.bat",
        "Uninstall_GameNet_Server.bat",
    ):
        shutil.copy2(ROOT_DIR / fname, STAGING_DIR / fname)

    # Embedded Python + icons + helper scripts under deploy/windows
    target_deploy = STAGING_DIR / "deploy" / "windows"
    target_deploy.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        DEPLOY_WIN_DIR / "python",
        target_deploy / "python",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "websockets-14.1.dist-info"),
    )
    shutil.copytree(DEPLOY_WIN_DIR / "assets", target_deploy / "assets")
    # Pure-Python additions must also reach existing installations via the small updater.
    site_packages = DEPLOY_WIN_DIR / "python" / "Lib" / "site-packages"
    for package in site_packages.glob("websockets*"):
        if package.is_dir() and package.name in {"websockets", "websockets-15.0.1.dist-info"}:
            shutil.copytree(
                package, STAGING_DIR / "python-deps" / package.name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
    for fname in ("run_server.bat", "watchdog_server.bat", "run_server_hidden.vbs", "install_service.bat", "uninstall_service.bat"):
        if (DEPLOY_WIN_DIR / fname).exists():
            shutil.copy2(DEPLOY_WIN_DIR / fname, target_deploy / fname)

    # Clean certificates (exclude private CA/cloud keys)
    target_certs = STAGING_DIR / "dev" / "certs"
    target_certs.mkdir(parents=True, exist_ok=True)
    for cname in ("ca.pem", "edge.pem", "edge.key", "edge.fingerprint"):
        src = ROOT_DIR / "dev" / "certs" / cname
        if src.exists():
            shutil.copy2(src, target_certs / cname)

    # Clean backend source (exclude db, .venv, symlinks, runtime, caches)
    target_backend = STAGING_DIR / "backend"
    target_backend.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BACKEND_DIR / "manage.py", target_backend / "manage.py")
    ignore_backend = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "*.sqlite3*",
        "*.db",
        "*.log",
        ".venv*",
        ".runtime",
        ".pytest_cache",
    )
    for sub in ("apps", "gamenet", "templates", "static"):
        src_sub = BACKEND_DIR / sub
        if src_sub.exists():
            shutil.copytree(src_sub, target_backend / sub, ignore=ignore_backend, symlinks=False)
    # Server self-update packages are served by the cloud, never embedded in the edge installer.
    shutil.rmtree(target_backend / "static" / "updates" / "server", ignore_errors=True)
    (target_backend / "data").mkdir(parents=True, exist_ok=True)

    # Collect static files cleanly into staged .artifacts/static
    venv_py = Path(os.environ.get("GAMENET_BUILD_PYTHON", str(BACKEND_DIR / ".venv" / "bin" / "python")))
    if venv_py.exists():
        collect_env = os.environ.copy()
        collect_env["GAMENET_ROLE"] = "edge"
        collect_env["DJANGO_SETTINGS_MODULE"] = "gamenet.settings.edge"
        collect_env["DJANGO_SECRET_KEY"] = "collectstatic-staging-key-not-used-in-prod"
        collect_env["DJANGO_STATIC_ROOT"] = str(STAGING_DIR / ".artifacts" / "static")
        tmp_db = ROOT_DIR / ".artifacts" / "build" / "_collectstatic.sqlite3"
        tmp_db.parent.mkdir(parents=True, exist_ok=True)
        collect_env["DATABASE_URL"] = f"sqlite:///{tmp_db}"
        subprocess.run(
            [str(venv_py), "manage.py", "collectstatic", "--noinput", "--clear", "--settings=gamenet.settings.edge"],
            cwd=target_backend,
            env=collect_env,
            check=True,
        )
        tmp_db.unlink(missing_ok=True)

    # Guardrail: guarantee zero dev secrets, DBs, or symlinks leaked into staging
    for forbidden in (".env", "backend/python", "dev/certs/ca.key", "dev/certs/cloud.key"):
        p = STAGING_DIR / forbidden
        if p.is_symlink() or p.exists():
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
    for p in STAGING_DIR.rglob("*"):
        if p.is_symlink():
            raise RuntimeError(f"Symlink leaked into staging tree: {p}")


def build_nsis_installer() -> Path:
    if not NSIS_BIN.exists():
        raise FileNotFoundError(f"NSIS compiler not found at {NSIS_BIN}")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    out_exe = DIST_DIR / f"GameNet-Server-{VERSION}-Setup.exe"
    nsi_file = DEPLOY_WIN_DIR / "installer" / "server_installer.nsi"
    icon_file = DEPLOY_WIN_DIR / "assets" / "gamenet-server.ico"

    nsis_env = os.environ.copy()
    nsis_env["NSISDIR"] = str(NSIS_BIN.parent.parent)

    subprocess.run(
        [
            str(NSIS_BIN),
            f"-DPRODUCT_VERSION={VERSION}",
            f"-DSTAGING_DIR={STAGING_DIR}",
            f"-DOUT_FILE={out_exe}",
            f"-DICON_FILE={icon_file}",
            str(nsi_file),
        ],
        env=nsis_env,
        check=True,
    )
    return out_exe


def sync_portable_folder() -> None:
    """Keep dist_windows/GameNet_Server_Win10 clean too (no symlinks, valid CRLF, updated binaries)."""
    portable = DIST_DIR / "GameNet_Server_Win10"
    if portable.exists():
        shutil.rmtree(portable)
    shutil.copytree(STAGING_DIR, portable, symlinks=False)


def main() -> int:
    print("[1/4] Writing synced CRLF batch & VBS scripts...")
    write_fixed_batch_scripts()

    print("[2/4] Compiling GameNet_Service.exe and GameNet_Server.exe (Windows x64)...")
    build_go_binaries()

    print("[3/4] Staging clean dependency-free Server tree & collecting static assets...")
    copy_clean_tree()

    print("[4/4] Building standalone NSIS installer executable...")
    out_exe = build_nsis_installer()
    sync_portable_folder()

    size_mb = out_exe.stat().st_size / (1024 * 1024)
    print(f"[SUCCESS] Built {out_exe} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

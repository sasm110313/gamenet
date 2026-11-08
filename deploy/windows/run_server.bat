@echo off
chcp 65001 >nul
title GameNet Salon Server
setlocal enabledelayedexpansion

cd /d "%~dp0\..\.."
set "ROOT_DIR=%cd%"
cd /d "%ROOT_DIR%\backend"

set "GAMENET_ROLE=edge"
set "DJANGO_SETTINGS_MODULE=gamenet.settings.edge"
set "EDGE_LAN_BIND=0.0.0.0"
set "EDGE_LAN_PORT=19443"
set "EDGE_DISCOVERY_PORT=19445"
set "PYTHONUTF8=1"

if not defined DATABASE_URL (
    set "DATABASE_URL=postgresql://gamenet:110114aliali@127.0.0.1:5432/gamenet_edge"
)
if not defined CERTS (
    set "CERTS=%ROOT_DIR%\dev\certs"
)

echo ========================================================
echo   GameNet Salon Server (Windows Service Process)
echo   HTTPS / WSS Bind : 0.0.0.0:19443
echo   UDP Discovery    : 0.0.0.0:19445 (SmartLaunch Mode)
echo ========================================================

:: Determine Python executable
if exist "%ROOT_DIR%\backend\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT_DIR%\backend\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python.exe"
)

:: Run database migrations
echo [1/2] Checking database migrations...
"%PYTHON_EXE%" manage.py migrate --noinput --settings=gamenet.settings.edge

:: Launch Uvicorn ASGI Server
echo [2/2] Starting GameNet Salon Server engine...
"%PYTHON_EXE%" -m uvicorn gamenet.asgi:application ^
    --host 0.0.0.0 --port 19443 ^
    --ssl-keyfile "%CERTS%\edge.key" --ssl-certfile "%CERTS%\edge.pem" ^
    --ws websockets --log-level info

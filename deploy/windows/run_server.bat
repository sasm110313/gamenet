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

:: If DATABASE_URL is not set, edge defaults automatically to zero-setup SQLite in backend\data\gamenet_edge.sqlite3
:: Uncomment the line below if using a dedicated local PostgreSQL on Windows:
:: set "DATABASE_URL=postgresql://gamenet:110114aliali@127.0.0.1:5432/gamenet_edge"

if not defined CERTS (
    set "CERTS=%ROOT_DIR%\dev\certs"
)

echo ========================================================
echo   GameNet Salon Server (Windows Service Process)
echo   HTTPS / WSS Bind : 0.0.0.0:19443
echo   UDP Discovery    : 0.0.0.0:19445 (SmartLaunch Mode)
echo   Cloud Sync       : https://gamenet.hammasjedy.ir
echo ========================================================

:: Determine Python executable
if exist "%ROOT_DIR%\backend\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT_DIR%\backend\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python.exe"
)

:: Run database migrations
echo [1/3] بررسی و ارتقای دیتابیس (Migrations)...
"%PYTHON_EXE%" manage.py migrate --noinput --settings=gamenet.settings.edge

:: Bootstrap default admin, tariff, and PC-01 to PC-10 if not present
echo [2/3] بررسی استیشن‌ها و کاربر مدیر سالن...
"%PYTHON_EXE%" manage.py bootstrap_edge --settings=gamenet.settings.edge

:: Launch Uvicorn ASGI Server (automatically hosts Dashboard, UDP Discovery, and Cloud Sync)
echo [3/3] اجرای موتور سرور سالن گیم‌نت...
"%PYTHON_EXE%" -m uvicorn gamenet.asgi:application ^
    --host 0.0.0.0 --port 19443 ^
    --ssl-keyfile "%CERTS%\edge.key" --ssl-certfile "%CERTS%\edge.pem" ^
    --ws websockets --log-level info

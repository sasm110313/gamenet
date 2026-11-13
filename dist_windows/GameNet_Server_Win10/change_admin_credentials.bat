@echo off
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

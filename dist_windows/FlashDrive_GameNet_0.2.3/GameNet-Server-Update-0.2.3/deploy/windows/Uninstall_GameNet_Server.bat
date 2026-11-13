@echo off
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

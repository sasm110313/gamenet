@echo off
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

@echo off
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

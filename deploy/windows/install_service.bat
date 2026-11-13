@echo off
setlocal enabledelayedexpansion
title GameNet Salon Server - Windows Service Installer
rem Keep this file pure ASCII: cmd.exe on Windows 7 mis-parses UTF-8 batch
rem files (even with "chcp 65001") and runs fragments of text as commands.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Administrator privileges are required.
    echo Please right-click this file and select "Run as administrator".
    echo.
    pause
    exit /b 1
)

cd /d "%~dp0\..\.."
set "ROOT_DIR=%cd%"
set "RUN_BAT=%ROOT_DIR%\deploy\windows\run_server.bat"

echo ===================================================================
echo     GameNet Salon Server - Windows service installation
echo ===================================================================
echo.

echo [1/3] Configuring Windows Firewall ports...
netsh advfirewall firewall delete rule name="GameNet Salon Server HTTPS" >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Salon Server HTTPS" dir=in action=allow protocol=TCP localport=19443 >nul 2>&1

netsh advfirewall firewall delete rule name="GameNet Salon Server Discovery" >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Salon Server Discovery" dir=in action=allow protocol=UDP localport=19445 >nul 2>&1
echo      Ports 19443 (TCP) and 19445 (UDP) are open.

echo [2/3] Registering the GameNet Salon Server service...

if exist "%~dp0nssm.exe" (
    echo      Installing a native Windows service via NSSM...
    "%~dp0nssm.exe" stop GameNetServer >nul 2>&1
    "%~dp0nssm.exe" remove GameNetServer confirm >nul 2>&1
    "%~dp0nssm.exe" install GameNetServer "%RUN_BAT%"
    "%~dp0nssm.exe" set GameNetServer AppDirectory "%ROOT_DIR%\backend"
    "%~dp0nssm.exe" set GameNetServer DisplayName "GameNet Salon Server"
    "%~dp0nssm.exe" set GameNetServer Description "GameNet Salon Server - clients, sessions and cloud sync"
    "%~dp0nssm.exe" set GameNetServer Start SERVICE_AUTO_START
    "%~dp0nssm.exe" start GameNetServer
) else (
    echo      NSSM not found; registering a SYSTEM startup task instead...
    schtasks /delete /tn "GameNetSalonServer" /f >nul 2>&1
    schtasks /create /tn "GameNetSalonServer" /tr "%RUN_BAT%" /sc onstart /ru "SYSTEM" /rl highest /f
    schtasks /run /tn "GameNetSalonServer" >nul 2>&1
)

echo [3/3] The service is enabled.
echo.
echo ===================================================================
echo  Done:
echo   1. The GameNet server starts automatically with Windows.
echo   2. Admin panel: https://127.0.0.1:19443/
echo.
echo  Default admin login: admin / admin
echo  Change it with change_admin_credentials.bat
echo ===================================================================
echo.
pause

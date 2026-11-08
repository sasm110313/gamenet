@echo off
chcp 65001 >nul
title GameNet Salon Server - Windows Service Installer
setlocal enabledelayedexpansion

:: Check administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [خطا] لطفاً این فایل را به صورت Run as Administrator اجرا کنید.
    echo [ERROR] Please run this batch script as Administrator.
    echo.
    pause
    exit /b 1
)

cd /d "%~dp0\..\.."
set "ROOT_DIR=%cd%"
set "RUN_BAT=%ROOT_DIR%\deploy\windows\run_server.bat"

echo ===================================================================
echo     GameNet Salon Server - نصب خودکار سرویس ویندوز (SmartLaunch)
echo ===================================================================
echo.

:: 1. Windows Firewall Rules
echo [1/3] تنظیم فایروال ویندوز برای پورت‌های سالن...
netsh advfirewall firewall delete rule name="GameNet Salon Server HTTPS" >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Salon Server HTTPS" dir=in action=allow protocol=TCP localport=19443 >nul 2>&1

netsh advfirewall firewall delete rule name="GameNet Salon Server Discovery" >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Salon Server Discovery" dir=in action=allow protocol=UDP localport=19445 >nul 2>&1
echo      پورت ۱۹۴۴۳ (TCP) و ۱۹۴۴۵ (UDP) در فایروال باز شدند.

:: 2. Register Windows Service / Startup Task
echo [2/3] ثبت سرویس ویندوز GameNet Salon Server...

if exist "%~dp0nssm.exe" (
    echo      استفاده از NSSM برای نصب سرویس بومی ویندوز...
    "%~dp0nssm.exe" stop GameNetServer >nul 2>&1
    "%~dp0nssm.exe" remove GameNetServer confirm >nul 2>&1
    "%~dp0nssm.exe" install GameNetServer "%RUN_BAT%"
    "%~dp0nssm.exe" set GameNetServer AppDirectory "%ROOT_DIR%\backend"
    "%~dp0nssm.exe" set GameNetServer DisplayName "GameNet Salon Server"
    "%~dp0nssm.exe" set GameNetServer Description "سرور سالن گیم‌نت - مدیریت کلاینت‌ها و بازی‌ها"
    "%~dp0nssm.exe" set GameNetServer Start SERVICE_AUTO_START
    "%~dp0nssm.exe" start GameNetServer
) else (
    echo      ثبت سرویس از طریق Windows Scheduled Task (اجرا هنگام بوت سیستم با دسترسی SYSTEM)...
    schtasks /delete /tn "GameNetSalonServer" /f >nul 2>&1
    schtasks /create /tn "GameNetSalonServer" /tr "\"%RUN_BAT%\"" /sc onstart /ru "SYSTEM" /rl highest /f >nul 2>&1
    schtasks /run /tn "GameNetSalonServer" >nul 2>&1
)

:: 3. Verification
echo [3/3] سرویس با موفقیت فعال شد!
echo.
echo ===================================================================
echo  عملیات با موفقیت انجام شد:
echo  ۱. سرور گیم‌نت با روشن شدن ویندوز خودکار بالا می‌آید.
echo  ۲. کلاینت‌ها به طور خودکار از طریق شبکه محلی (UDP 19445) سرور را
echo     پیدا کرده و متصل می‌شوند (دقیقاً مشابه اسمارت لانچ).
echo  ۳. آدرس پنل محلی سالن: https://127.0.0.1:19443
echo ===================================================================
echo.
pause

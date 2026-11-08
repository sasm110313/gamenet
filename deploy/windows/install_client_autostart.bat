@echo off
chcp 65001 >nul
title GameNet Client - AutoStart & Kiosk Setup
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

:: Locate client executable
if exist "%ROOT_DIR%\client\dist\win-unpacked\GameNet.exe" (
    set "CLIENT_EXE=%ROOT_DIR%\client\dist\win-unpacked\GameNet.exe"
) else if exist "%ROOT_DIR%\client\node_modules\.bin\electron.cmd" (
    set "CLIENT_EXE=%ROOT_DIR%\client\node_modules\.bin\electron.cmd \"%ROOT_DIR%\client\""
) else (
    echo [هشدار] فایل اجرایی کلاینت یافت نشد. لطفاً ابتدا کلاینت را بیلد کنید: npm run build
    set "CLIENT_EXE=%ROOT_DIR%\client"
)

echo ===================================================================
echo     GameNet Client - فعال‌سازی اجرای خودکار هنگام بوت ویندوز (SmartLaunch)
echo ===================================================================
echo.

:: 1. Add Registry Run key for all users
echo [1/2] ثبت کلاینت در رجیستری اجرای خودکار ویندوز (Run key)...
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /t REG_SZ /d "\"%CLIENT_EXE%\"" /f >nul 2>&1
echo      کلاینت ثبت شد. با روشن شدن کامپیوتر کلاینت بلافاصله باز می‌شود.

:: 2. Firewall rules
echo [2/2] باز کردن پورت‌های ارتباطی شبکه محلی...
netsh advfirewall firewall delete rule name="GameNet Client LAN" >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Client LAN" dir=out action=allow protocol=UDP remoteport=19445 >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Client LAN" dir=in action=allow protocol=UDP localport=19445 >nul 2>&1

echo.
echo ===================================================================
echo  تنظیم کلاینت با موفقیت انجام شد:
echo  - با روشن شدن کامپیوتر، کلاینت به طور تمام‌صفحه باز می‌شود.
echo  - سرور سالن را خودکار پیدا کرده و صفحه را قفل می‌کند.
echo ===================================================================
echo.
pause

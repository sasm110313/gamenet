@echo off
chcp 65001 >nul
title GameNet Salon Server - Uninstall Service
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

echo ===================================================================
echo     GameNet Salon Server - حذف سرویس ویندوز
echo ===================================================================
echo.

if exist "%~dp0nssm.exe" (
    "%~dp0nssm.exe" stop GameNetServer >nul 2>&1
    "%~dp0nssm.exe" remove GameNetServer confirm >nul 2>&1
)

schtasks /delete /tn "GameNetSalonServer" /f >nul 2>&1

netsh advfirewall firewall delete rule name="GameNet Salon Server HTTPS" >nul 2>&1
netsh advfirewall firewall delete rule name="GameNet Salon Server Discovery" >nul 2>&1

powershell -NoProfile -Command ^
    "$desk = [Environment]::GetFolderPath('Desktop'); " ^
    "Remove-Item \"$desk\مدیریت گیم‌نت (GameNet Server).lnk\" -ErrorAction SilentlyContinue" >nul 2>&1

echo سرویس، قوانین فایروال و میانبر دسکتاپ با موفقیت حذف شدند.
pause

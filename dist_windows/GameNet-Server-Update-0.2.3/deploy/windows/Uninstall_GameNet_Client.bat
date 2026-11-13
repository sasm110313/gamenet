@echo off
chcp 65001 >nul
title بازی سرای رهرو - حذف کامل کلاینت (Uninstall Client)
setlocal enabledelayedexpansion

:: 1. Check administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ===================================================================
    echo  [خطا] این اسکریپت برای بازگردانی ویندوز به حالت عادی نیاز به
    echo  دسترسی Administrator دارد.
    echo.
    echo  لطفاً روی این فایل راست‌کلیک کرده و "Run as administrator" را بزنید.
    echo ===================================================================
    echo.
    pause
    exit /b 1
)

echo ===================================================================
echo     حذف کلاینت بازی سرای رهرو و بازگردانی ویندوز به حالت استاندارد
echo ===================================================================
echo.
echo این اسکریپت:
echo  ۱. نرم‌افزار کلاینت کیوسک را متوقف می‌کند.
echo  ۲. پوسته ویندوز (Windows Explorer، دسکتاپ و تسک‌بار) را کاملاً بازمی‌گرداند.
echo  ۳. کلیدهای اجرای خودکار، تسک‌های زمان‌بندی‌شده و میانبرها را حذف می‌کند.
echo  ۴. دسکتاپ را فوراً روی صفحه فعال می‌نماید.
echo.

set /p "CONFIRM=آیا از حذف کلاینت و خروج از حالت کیوسک مطمئن هستید؟ [Y/N]: "
if /i not "!CONFIRM!"=="Y" (
    echo عملیات لغو شد.
    pause
    exit /b 0
)

echo.
echo [1/7] متوقف کردن نرم‌افزار کلاینت (GameNet.exe)...
taskkill /f /im GameNet.exe >nul 2>&1

echo [2/7] بازگردانی پوسته اصلی ویندوز (Windows Explorer)...
reg add "HKLM\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "explorer.exe" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "explorer.exe" /f >nul 2>&1

echo [3/7] حذف کلیدهای اجرای خودکار رجیستری...
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /f >nul 2>&1

echo [4/7] حذف تسک زمان‌بندی‌شده اجرای خودکار (Task Scheduler)...
schtasks /delete /tn "GameNetClient" /f >nul 2>&1

echo [5/7] حذف میانبرهای Startup و دسکتاپ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$startup = [Environment]::GetFolderPath('CommonStartup'); " ^
    "$userStartup = [Environment]::GetFolderPath('Startup'); " ^
    "$desk = [Environment]::GetFolderPath('Desktop'); " ^
    "$commonDesk = [Environment]::GetFolderPath('CommonDesktopDirectory'); " ^
    "Remove-Item \"$startup\GameNet.lnk\" -Force -ErrorAction SilentlyContinue; " ^
    "Remove-Item \"$userStartup\GameNet.lnk\" -Force -ErrorAction SilentlyContinue; " ^
    "Remove-Item \"$desk\GameNet.lnk\" -Force -ErrorAction SilentlyContinue; " ^
    "Remove-Item \"$desk\بازی سرای رهرو.lnk\" -Force -ErrorAction SilentlyContinue; " ^
    "Remove-Item \"$commonDesk\GameNet.lnk\" -Force -ErrorAction SilentlyContinue;" >nul 2>&1

echo [6/7] حذف قوانین فایروال کلاینت...
netsh advfirewall firewall delete rule name="GameNet Client LAN" >nul 2>&1

echo [7/7] راه‌اندازی و نمایش دسکتاپ ویندوز (Explorer)...
tasklist /fi "imagename eq explorer.exe" | findstr /i "explorer.exe" >nul 2>&1
if %errorlevel% neq 0 (
    start "" explorer.exe
)

echo.
echo ===================================================================
echo   کلاینت کیوسک با موفقیت حذف شد و ویندوز به حالت عادی بازگشت.
echo.
echo   آیا مایلید فایل‌های برنامه کلاینت از مسیر Program Files نیز پاک شوند؟
echo ===================================================================
set /p "DEL_FILES=حذف پوشه برنامه از مسیر نصب؟ [Y/N]: "
if /i "!DEL_FILES!"=="Y" (
    if exist "C:\Program Files (x86)\GameNet" (
        rmdir /s /q "C:\Program Files (x86)\GameNet" >nul 2>&1
        echo پوشه C:\Program Files (x86)\GameNet پاک شد.
    )
    if exist "C:\Program Files\GameNet" (
        rmdir /s /q "C:\Program Files\GameNet" >nul 2>&1
        echo پوشه C:\Program Files\GameNet پاک شد.
    )
    if exist "%LOCALAPPDATA%\Programs\GameNet" (
        rmdir /s /q "%LOCALAPPDATA%\Programs\GameNet" >nul 2>&1
        echo پوشه برنامه در LocalAppData پاک شد.
    )
)

echo.
echo ویندوز هم‌اکنون به طور کامل آزاد و در حالت عادی است.
pause

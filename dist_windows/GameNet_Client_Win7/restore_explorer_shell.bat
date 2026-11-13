@echo off
chcp 65001 >nul
title GameNet Client - Restore Windows Explorer Shell
setlocal enabledelayedexpansion

:: Check administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [خطا] لطفاً روی این فایل راست‌کلیک کرده و "Run as administrator" را بزنید.
    echo.
    pause
    exit /b 1
)

echo ===================================================================
echo     بازگردانی پوسته پیش‌فرض ویندوز (Windows Explorer Shell)
echo ===================================================================
echo.

echo [1/3] بازگردانی Shell به explorer.exe...
reg add "HKLM\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "explorer.exe" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "explorer.exe" /f >nul 2>&1

echo [2/3] حذف کلیدهای اجرای خودکار کلاینت...
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /f >nul 2>&1
schtasks /delete /tn "GameNetClient" /f >nul 2>&1

echo [3/3] پاکسازی میانبرهای استارتاپ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$startup = [Environment]::GetFolderPath('CommonStartup'); " ^
    "Remove-Item -Path \"$startup\GameNet.lnk\" -Force -ErrorAction SilentlyContinue;" >nul 2>&1

echo.
echo ===================================================================
echo   پوسته ویندوز با موفقیت به حالت عادی (Explorer) بازگردانده شد.
echo   با ری‌استارت بعدی، ویندوز به صورت عادی با دسکتاپ و تسک‌بار بالا می‌آید.
echo ===================================================================
echo.
pause

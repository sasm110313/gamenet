@echo off
chcp 65001 >nul
title GameNet Salon Management Server
setlocal enabledelayedexpansion

cd /d "%~dp0\..\.."
set "ROOT_DIR=%cd%"
set "BACKEND_DIR=%ROOT_DIR%\backend"
set "SERVER_URL=https://127.0.0.1:19443/"

echo =======================================================
echo        GameNet Salon Management Server (Windows)
echo              مدیریت سالن گیم‌نت - نسخه ویندوز
echo =======================================================
echo.

:: 1. Check if server is running on port 19443
echo [1/3] بررسی وضعیت سرور گیم‌نت...
powershell -NoProfile -Command ^
    "[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}; " ^
    "try { $r = [System.Net.WebRequest]::Create('%SERVER_URL%'); $r.Timeout = 1500; $resp = $r.GetResponse(); exit 0 } catch { exit 1 }" >nul 2>&1

if %errorlevel% equ 0 (
    echo      سرور در حال حاضر فعال است!
) else (
    echo      سرور متوقف است. در حال راه‌اندازی...

    :: Try starting service
    sc start GameNetServer >nul 2>&1
    timeout /t 2 >nul 2>&1

    powershell -NoProfile -Command ^
        "[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}; " ^
        "try { $r = [System.Net.WebRequest]::Create('%SERVER_URL%'); $r.Timeout = 1500; $resp = $r.GetResponse(); exit 0 } catch { exit 1 }" >nul 2>&1

    if %errorlevel% neq 0 (
        echo [2/3] اجرای مستقیم پروسه سرور در پس‌زمینه...
        start "" /b "%ROOT_DIR%\deploy\windows\run_server.bat"

        echo      در انتظار بالا آمدن موتور سرور...
        for /l %%i in (1,1,10) do (
            timeout /t 1 >nul 2>&1
            powershell -NoProfile -Command ^
                "[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}; " ^
                "try { $r = [System.Net.WebRequest]::Create('%SERVER_URL%'); $r.Timeout = 1500; $resp = $r.GetResponse(); exit 0 } catch { exit 1 }" >nul 2>&1
            if !errorlevel! equ 0 goto server_ready
        )
    )
)

:server_ready
echo.
echo [3/3] باز کردن پنل مدیریت سالن (استیشن‌های ۱ تا ۱۰)...

:: Try opening Microsoft Edge in application window mode
set "OPENED=0"
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app="%SERVER_URL%" --ignore-certificate-errors --no-first-run
    set "OPENED=1"
) else if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files\Microsoft\Edge\Application\msedge.exe" --app="%SERVER_URL%" --ignore-certificate-errors --no-first-run
    set "OPENED=1"
) else if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app="%SERVER_URL%" --ignore-certificate-errors --no-first-run
    set "OPENED=1"
)

if "!OPENED!"=="0" (
    start "" "%SERVER_URL%"
)

echo.
echo =======================================================
echo   پنل مدیریت سالن باز شد: %SERVER_URL%
echo   - کلاینت‌ها (سیستم‌های ۱ تا ۱۰) به صورت خودکار متصل می‌شوند.
echo   - در صورت اتصال به اینترنت، اطلاعات با سرور آنلاین همگام می‌شود.
echo =======================================================
echo.
echo برای بستن این پنجره یک کلید را فشار دهید...
pause >nul

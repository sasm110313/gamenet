@echo off
chcp 65001 >nul
title GameNet Salon Server - Full Windows Setup & Installer
setlocal enabledelayedexpansion

:: Check administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ===================================================================
    echo  [خطا] دسترسی مدیر (Administrator) لازم است.
    echo  لطفاً روی این فایل راست‌کلیک کرده و "Run as administrator" را بزنید.
    echo ===================================================================
    echo.
    pause
    exit /b 1
)

cd /d "%~dp0\..\.."
set "ROOT_DIR=%cd%"
set "BACKEND_DIR=%ROOT_DIR%\backend"
set "RUN_BAT=%ROOT_DIR%\deploy\windows\run_server.bat"
set "SERVER_EXE=%ROOT_DIR%\GameNet_Server.exe"

echo ===================================================================
echo     نصب و راه‌اندازی خودکار سرور سالن گیم‌نت (GameNet Salon Server)
echo ===================================================================
echo.
echo مسیر نصب: %ROOT_DIR%
echo.

:: 1. Check Python
echo [1/6] بررسی مفسر پایتون (Python)...
if exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%BACKEND_DIR%\.venv\Scripts\python.exe"
    echo      محیط مجازی اختصاصی یافت شد: .venv
) else (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
        echo      پایتون سیستمی شناسایی شد.
        echo      در حال ایجاد محیط مجازی اختصاصی .venv ...
        python -m venv "%BACKEND_DIR%\.venv"
        if exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
            set "PYTHON_EXE=%BACKEND_DIR%\.venv\Scripts\python.exe"
            echo      نصب پکیج‌های مورد نیاز بک‌اند...
            "%PYTHON_EXE%" -m pip install --upgrade pip >nul 2>&1
            "%PYTHON_EXE%" -m pip install -r "%BACKEND_DIR%\requirements.txt"
        )
    ) else (
        echo [خطا] پایتون روی سیستم نصب نیست!
        echo لطفاً Python 3.12 یا بالاتر را از python.org نصب نموده و تیک "Add Python to PATH" را بزنید.
        pause
        exit /b 1
    )
)

:: 2. Firewall Rules
echo.
echo [2/6] پیکربندی فایروال ویندوز برای پورت‌های سالن...
netsh advfirewall firewall delete rule name="GameNet Salon Server HTTPS" >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Salon Server HTTPS" dir=in action=allow protocol=TCP localport=19443 >nul 2>&1

netsh advfirewall firewall delete rule name="GameNet Salon Server Discovery" >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Salon Server Discovery" dir=in action=allow protocol=UDP localport=19445 >nul 2>&1
echo      پورت‌های ۱۹۴۴۳ (HTTPS) و ۱۹۴۴۵ (UDP Auto-Discovery) با موفقیت باز شدند.

:: 3. Database & Bootstrap
echo.
echo [3/6] راه‌اندازی پایگاه‌داده و استیشن‌های ۱ تا ۱۰...
cd /d "%BACKEND_DIR%"
set "GAMENET_ROLE=edge"
set "DJANGO_SETTINGS_MODULE=gamenet.settings.edge"
"%PYTHON_EXE%" manage.py migrate --noinput --settings=gamenet.settings.edge
"%PYTHON_EXE%" manage.py bootstrap_edge --settings=gamenet.settings.edge

:: 4. Windows Service / Auto-start Setup
echo.
echo [4/6] ثبت سرویس پس‌زمینه ویندوز (شروع خودکار هنگام بوت)...
if exist "%ROOT_DIR%\deploy\windows\nssm.exe" (
    "%ROOT_DIR%\deploy\windows\nssm.exe" stop GameNetServer >nul 2>&1
    "%ROOT_DIR%\deploy\windows\nssm.exe" remove GameNetServer confirm >nul 2>&1
    "%ROOT_DIR%\deploy\windows\nssm.exe" install GameNetServer "%RUN_BAT%"
    "%ROOT_DIR%\deploy\windows\nssm.exe" set GameNetServer AppDirectory "%BACKEND_DIR%"
    "%ROOT_DIR%\deploy\windows\nssm.exe" set GameNetServer DisplayName "GameNet Salon Server"
    "%ROOT_DIR%\deploy\windows\nssm.exe" set GameNetServer Description "سرور سالن گیم‌نت - مدیریت کلاینت‌ها و همگام‌سازی ابری"
    "%ROOT_DIR%\deploy\windows\nssm.exe" set GameNetServer Start SERVICE_AUTO_START
    "%ROOT_DIR%\deploy\windows\nssm.exe" start GameNetServer
    echo      سرویس بومی GameNetServer با موفقیت در ویندوز ثبت و اجرا شد.
) else (
    schtasks /delete /tn "GameNetSalonServer" /f >nul 2>&1
    schtasks /create /tn "GameNetSalonServer" /tr "\"%RUN_BAT%\"" /sc onstart /ru "SYSTEM" /rl highest /f >nul 2>&1
    schtasks /run /tn "GameNetSalonServer" >nul 2>&1
    echo      تسک سرویس GameNetSalonServer برای اجرای خودکار هنگام روشن شدن ویندوز ثبت شد.
)

:: 5. Create Desktop & Start Menu Shortcuts
echo.
echo [5/6] ایجاد میانبر دسکتاپ و منوی استارت...
set "SHORTCUT_TARGET=%SERVER_EXE%"
if not exist "%SERVER_EXE%" (
    set "SHORTCUT_TARGET=%ROOT_DIR%\GameNet_Server.bat"
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$desk = [Environment]::GetFolderPath('Desktop'); " ^
    "$s = $ws.CreateShortcut(\"$desk\مدیریت گیم‌نت (GameNet Server).lnk\"); " ^
    "$s.TargetPath = '%SHORTCUT_TARGET%'; " ^
    "$s.WorkingDirectory = '%ROOT_DIR%'; " ^
    "$s.Description = 'پنل مدیریت سالن گیم‌نت (10 استیشن)'; " ^
    "$s.Save();"

echo      میانبر 'مدیریت گیم‌نت' روی دسکتاپ قرار گرفت.

:: 6. Launch Server & Open Panel
echo.
echo [6/6] آماده‌سازی نهایی و باز کردن پنل مدیریت...
echo.
echo ===================================================================
echo   نصب و راه‌اندازی با موفقیت کامل شد!
echo.
echo   - سرور سالن: https://127.0.0.1:19443
echo   - کاربر پیش‌فرض: admin / admin123
echo   - سیستم‌های ۱ تا ۱۰ به صورت خودکار شناسایی و وصل می‌شوند.
echo   - در صورت دسترسی به اینترنت، خودکار با سرور آنلاین سینک می‌شود.
echo ===================================================================
echo.

:: Launch the launcher which opens the panel
if exist "%SERVER_EXE%" (
    start "" "%SERVER_EXE%"
) else (
    start "" "%ROOT_DIR%\GameNet_Server.bat"
)

pause

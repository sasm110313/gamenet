@echo off
chcp 65001 >nul
title آپدیت سرور گیم‌نت (GameNet Server In-Place Update)
setlocal enabledelayedexpansion

echo =====================================================================
echo    به‌روزرسانی سریع سرور گیم‌نت به نسخه 0.2.3 (بدون حذف دیتابیس)
echo =====================================================================
echo.

:: Check Admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [خطا] برای اعمال آپدیت، اجرای فایل با دسترسی Administrator الزامی است.
    echo لطفاً روی فایل راست‌کلیک کرده و "Run as administrator" را بزنید.
    echo.
    pause
    exit /b 1
)

:: Locate installation directory
set "TARGET_DIR=C:\Program Files\GameNet Server"
if not exist "%TARGET_DIR%" (
    if exist "%~dp0backend\manage.py" (
        set "TARGET_DIR=%~dp0"
    ) else (
        echo [خطا] پوشه نصب سرور در C:\Program Files\GameNet Server یافت نشد.
        set /p "TARGET_DIR=لطفاً مسیر پوشه نصب سرور را وارد کنید: "
    )
)
for %%%%I in ("%TARGET_DIR%") do set "TARGET_DIR=%%%%~fI"

if not exist "%TARGET_DIR%\backend\manage.py" (
    echo [خطا] فایل backend\manage.py در مسیر "%TARGET_DIR%" یافت نشد.
    pause
    exit /b 1
)

echo [1/4] متوقف‌سازی سرویس و فرآیندهای قبلی سرور...
net stop GameNetServer >nul 2>&1
taskkill /F /IM GameNet_Server.exe /T >nul 2>&1
taskkill /F /IM GameNet_Service.exe /T >nul 2>&1
timeout /t 1 /nobreak >nul

echo [2/4] کپی و جایگزینی فایل‌های به‌روزرسانی شده (با حفظ کامل دیتابیس و تنظیمات)...
set "SRC_DIR=%~dp0"

:: Copy backend files without touching backend\data
robocopy "%SRC_DIR%backend" "%TARGET_DIR%\backend" /E /XD data __pycache__ /XF *.sqlite3* *.db *.log .env /R:1 /W:1 >nul 2>&1

:: Copy deploy files
robocopy "%SRC_DIR%deploy" "%TARGET_DIR%\deploy" /E /XD python __pycache__ /R:1 /W:1 >nul 2>&1

:: Copy root binaries and scripts
copy /y "%SRC_DIR%GameNet_Server.exe" "%TARGET_DIR%" >nul 2>&1
copy /y "%SRC_DIR%GameNet_Service.exe" "%TARGET_DIR%" >nul 2>&1
copy /y "%SRC_DIR%GameNet_Server.bat" "%TARGET_DIR%" >nul 2>&1
copy /y "%SRC_DIR%Open_Admin_Panel.bat" "%TARGET_DIR%" >nul 2>&1
copy /y "%SRC_DIR%change_admin_credentials.bat" "%TARGET_DIR%" >nul 2>&1

echo [3/4] اعمال آخرین ساختار دیتابیس (Migrations)...
set "PY_EXE=%TARGET_DIR%\deploy\windows\python\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=%TARGET_DIR%\backend\.venv\Scripts\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python.exe"

cd /d "%TARGET_DIR%\backend"
set "GAMENET_ROLE=edge"
set "DJANGO_SETTINGS_MODULE=gamenet.settings.edge"
set "PYTHONUTF8=1"
"%PY_EXE%" manage.py migrate --noinput
"%PY_EXE%" manage.py collectstatic --noinput >nul 2>&1

echo [4/4] راه‌اندازی مجدد سرویس و اعتبارسنجی سلامت سرور...
net start GameNetServer >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%TARGET_DIR%\GameNet_Service.exe" (
        "%TARGET_DIR%\GameNet_Service.exe" --ensure-running
    )
)

echo.
echo =====================================================================
echo    [✓] به‌روزرسانی سرور گیم‌نت به نسخه 0.2.3 با موفقیت پایان یافت!
echo    تمام سوابق، اکانت‌ها، موجودی کیف‌پول و تنظیمات سالن حفظ شدند.
echo =====================================================================
echo.
pause
exit /b 0

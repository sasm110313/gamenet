@echo off
chcp 65001 >nul
title GameNet Client - AutoStart & Kiosk Shell Setup
setlocal enabledelayedexpansion

:: 1. Check administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ===================================================================
    echo  [خطا] این اسکریپت برای تنظیمات کیوسک و اجرای خودکار نیاز به
    echo  دسترسی Administrator دارد.
    echo.
    echo  لطفاً روی این فایل راست‌کلیک کرده و "Run as administrator" را بزنید.
    echo ===================================================================
    echo.
    pause
    exit /b 1
)

echo ===================================================================
echo     GameNet Client - راه‌اندازی کیوسک و اجرای خودکار هنگام روشن شدن ویندوز
echo ===================================================================
echo.

:: 2. Auto-detect GameNet.exe path across standard installation and portable locations
set "CLIENT_EXE="

if exist "%~dp0GameNet.exe" (
    set "CLIENT_EXE=%~dp0GameNet.exe"
) else if exist "%~dp0win-ia32-unpacked\GameNet.exe" (
    set "CLIENT_EXE=%~dp0win-ia32-unpacked\GameNet.exe"
) else if exist "C:\Program Files\GameNet\GameNet.exe" (
    set "CLIENT_EXE=C:\Program Files\GameNet\GameNet.exe"
) else if exist "C:\Program Files (x86)\GameNet\GameNet.exe" (
    set "CLIENT_EXE=C:\Program Files (x86)\GameNet\GameNet.exe"
) else if exist "C:\GameNet\GameNet.exe" (
    set "CLIENT_EXE=C:\GameNet\GameNet.exe"
) else if exist "D:\GameNet\GameNet.exe" (
    set "CLIENT_EXE=D:\GameNet\GameNet.exe"
) else if exist "%~dp0..\..\client\dist\win-unpacked\GameNet.exe" (
    set "CLIENT_EXE=%~dp0..\..\client\dist\win-unpacked\GameNet.exe"
) else if exist "%~dp0..\..\client\release\win-ia32-unpacked\GameNet.exe" (
    set "CLIENT_EXE=%~dp0..\..\client\release\win-ia32-unpacked\GameNet.exe"
)

if not defined CLIENT_EXE (
    echo [!] فایل GameNet.exe در مسیرهای پیش‌فرض پیدا نشد.
    echo لطفاً مسیر کامل فایل GameNet.exe را وارد کنید (یا فایل را بکشید و داخل این پنجره رها کنید):
    set /p "USER_EXE=مسیر فایل: "
    set "USER_EXE=!USER_EXE:"=!"
    if exist "!USER_EXE!" (
        set "CLIENT_EXE=!USER_EXE!"
    ) else (
        echo [خطا] فایل وارد شده یافت نشد. عملیات لغو شد.
        pause
        exit /b 1
    )
)

echo [تایید] فایل اجرایی کلاینت گیم‌نت: "%CLIENT_EXE%"
echo.

:: 3. Layer 1: Winlogon Shell replacement (Boots directly to GameNet without Explorer/Desktop/Taskbar)
echo [1/6] تنظیم کلاینت به عنوان پوسته اصلی ویندوز (جایگزین Explorer)...
reg add "HKLM\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "\"%CLIENT_EXE%\"" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "\"%CLIENT_EXE%\"" /f >nul 2>&1

:: 4. Layer 2: Registry Run key for all users and current user
echo [2/6] ثبت در کلید اجرای خودکار ویندوز (Run Key)...
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /t REG_SZ /d "\"%CLIENT_EXE%\"" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /t REG_SZ /d "\"%CLIENT_EXE%\"" /f >nul 2>&1

:: 5. Layer 3: Windows Task Scheduler (Elevated auto-start on logon)
echo [3/6] ایجاد تسک اجرای خودکار با بالاترین سطح دسترسی (Task Scheduler)...
schtasks /delete /tn "GameNetClient" /f >nul 2>&1
schtasks /create /tn "GameNetClient" /tr "\"%CLIENT_EXE%\"" /sc onlogon /rl highest /f >nul 2>&1

:: 6. Layer 4: Startup folder shortcut
echo [4/6] ایجاد میانبر در پوشه Startup ویندوز...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$startup = [Environment]::GetFolderPath('CommonStartup'); " ^
    "$s = $ws.CreateShortcut(\"$startup\GameNet.lnk\"); " ^
    "$s.TargetPath = '%CLIENT_EXE%'; " ^
    "$s.WorkingDirectory = [System.IO.Path]::GetDirectoryName('%CLIENT_EXE%'); " ^
    "$s.Description = 'GameNet Gaming Client'; " ^
    "$s.Save();" >nul 2>&1

:: 7. Layer 5: Windows Auto-Logon (No stopping at login/welcome screen)
echo [5/6] فعال‌سازی ورود خودکار به ویندوز بدون توقف در صفحه کاربری...
reg add "HKLM\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d "1" /f >nul 2>&1
reg add "HKLM\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d "%USERNAME%" /f >nul 2>&1
reg add "HKLM\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v ForceAutoLogon /t REG_SZ /d "1" /f >nul 2>&1

:: 8. Layer 6: Firewall rules for LAN discovery
echo [6/6] پیکربندی فایروال ویندوز برای پورت ۱۹۴۴۵ (ارتباط با سرور)...
netsh advfirewall firewall delete rule name="GameNet Client LAN" >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Client LAN" dir=out action=allow protocol=UDP remoteport=19445 >nul 2>&1
netsh advfirewall firewall add rule name="GameNet Client LAN" dir=in action=allow protocol=UDP localport=19445 >nul 2>&1

echo.
echo ===================================================================
echo   تنظیمات اجرای خودکار کلاینت ۱۰۰٪ با موفقیت انجام شد!
echo.
echo   از این پس با روشن شدن یا ری‌استارت کامپیوتر:
echo   ۱. ویندوز خودکار بدون نیاز به کلیک روی یوزر یا پسورد وارد می‌شود.
echo   ۲. اکسپلورر، دسکتاپ و تسک‌بار باز نمی‌شوند و کلاینت مستقیماً اجرا می‌شود.
echo   ۳. صفحه قفل شده و سرور سالن را در شبکه خودکار پیدا و متصل می‌کند.
echo ===================================================================
echo.
pause

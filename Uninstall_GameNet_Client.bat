@echo off
setlocal enabledelayedexpansion
title GameNet Salon - Uninstall Client (restore Windows shell)
rem Keep this file pure ASCII: cmd.exe on Windows 7 mis-parses UTF-8 batch files.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ===================================================================
    echo  [ERROR] Administrator privileges are required to restore Windows.
    echo  Right-click this file and choose "Run as administrator".
    echo ===================================================================
    echo.
    pause
    exit /b 1
)

echo ===================================================================
echo     GameNet Salon - remove kiosk client and restore Windows
echo ===================================================================
echo.
echo This script will:
echo   1. Stop the kiosk client (GameNet.exe).
echo   2. Restore Windows Explorer, desktop and taskbar.
echo   3. Remove startup entries, scheduled tasks and shortcuts.
echo   4. Bring the desktop back immediately.
echo.

set /p "CONFIRM=Remove the kiosk client and exit kiosk mode? [Y/N]: "
if /i not "!CONFIRM!"=="Y" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo [1/7] Stopping the client (GameNet.exe)...
taskkill /f /im GameNet.exe >nul 2>&1

echo [2/7] Restoring the Windows shell (explorer.exe)...
reg add "HKLM\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "explorer.exe" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "explorer.exe" /f >nul 2>&1

echo [3/7] Removing registry auto-start entries...
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "GameNetClient" /f >nul 2>&1

echo [4/7] Removing the scheduled auto-start task...
schtasks /delete /tn "GameNetClient" /f >nul 2>&1

echo [5/7] Removing startup and desktop shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$dirs = @([Environment]::GetFolderPath('CommonStartup'), [Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory')); " ^
    "$shell = New-Object -ComObject WScript.Shell; " ^
    "Get-ChildItem -Path $dirs -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object { try { if ($shell.CreateShortcut($_.FullName).TargetPath -match 'GameNet') { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue } } catch {} }" >nul 2>&1

echo [6/7] Removing client firewall rules...
netsh advfirewall firewall delete rule name="GameNet Client LAN" >nul 2>&1

echo [7/7] Starting the Windows desktop (Explorer)...
tasklist /fi "imagename eq explorer.exe" | findstr /i "explorer.exe" >nul 2>&1
if %errorlevel% neq 0 (
    start "" explorer.exe
)

echo.
echo ===================================================================
echo   The kiosk client was removed and Windows is back to normal.
echo.
echo   Delete the client program folder from Program Files as well?
echo ===================================================================
set /p "DEL_FILES=Delete the program folder from the install path? [Y/N]: "
if /i "!DEL_FILES!"=="Y" (
    if exist "C:\Program Files (x86)\GameNet" (
        rmdir /s /q "C:\Program Files (x86)\GameNet" >nul 2>&1
        echo Removed C:\Program Files (x86)\GameNet
    )
    if exist "C:\Program Files\GameNet" (
        rmdir /s /q "C:\Program Files\GameNet" >nul 2>&1
        echo Removed C:\Program Files\GameNet
    )
    if exist "%LOCALAPPDATA%\Programs\GameNet" (
        rmdir /s /q "%LOCALAPPDATA%\Programs\GameNet" >nul 2>&1
        echo Removed the LocalAppData program folder.
    )
)

echo.
echo Windows is now fully unlocked and back to normal mode.
pause

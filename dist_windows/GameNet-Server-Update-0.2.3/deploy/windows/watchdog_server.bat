@echo off
setlocal
if exist "%~dp0backend\manage.py" (
    set "ROOT_DIR=%~dp0"
) else if exist "%~dp0..\..\backend\manage.py" (
    set "ROOT_DIR=%~dp0..\.."
) else (
    exit /b 1
)
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

if exist "%ROOT_DIR%\GameNet_Service.exe" (
    "%ROOT_DIR%\GameNet_Service.exe" --ensure-running
    exit /b %errorlevel%
)
if exist "%ROOT_DIR%\deploy\windows\GameNet_Service.exe" (
    "%ROOT_DIR%\deploy\windows\GameNet_Service.exe" --ensure-running
    exit /b %errorlevel%
)
exit /b 0

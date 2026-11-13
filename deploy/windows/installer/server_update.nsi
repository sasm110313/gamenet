; GameNet Salon Server — standalone in-place updater (NSIS Unicode)
Unicode True
SetCompressor /SOLID lzma
SetCompressorDictSize 32

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"

!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "0.2.4"
!endif

!ifndef STAGING_DIR
  !error "STAGING_DIR must be defined"
!endif

!ifndef OUT_FILE
  !error "OUT_FILE must be defined"
!endif

!ifndef ICON_FILE
  !error "ICON_FILE must be defined"
!endif

!define APP_SHORT_NAME "GameNet Server"
!define SERVICE_NAME "GameNetServer"
!define UNINST_REG_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${SERVICE_NAME}"
!define UPDATE_TEMP "$TEMP\gamenet_server_update"

Name "${APP_SHORT_NAME} Update ${PRODUCT_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$PROGRAMFILES64\GameNet Server"
InstallDirRegKey HKLM "${UNINST_REG_KEY}" "InstallLocation"
RequestExecutionLevel admin
ManifestSupportedOS all
ShowInstDetails show
BrandingText "GameNet Server Updater ${PRODUCT_VERSION}"

!define MUI_ABORTWARNING
!define MUI_ICON "${ICON_FILE}"
!define MUI_HEADERIMAGE
!define MUI_WELCOMEPAGE_TITLE "به‌روزرسانی سرور سالن GameNet"
!define MUI_WELCOMEPAGE_TEXT "این برنامه نسخه ${PRODUCT_VERSION} سرور را روی نصب فعلی به‌روزرسانی می‌کند.$\r$\n$\r$\nدیتابیس، تنظیمات و اطلاعات سالن (پوشه data) دست‌نخورده می‌مانند."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Section "Update"
  ; Refuse to run against a missing installation instead of creating a half install.
  ${IfNot} ${FileExists} "$INSTDIR\backend\manage.py"
    MessageBox MB_ICONSTOP "نصب فعلی GameNet Server در مسیر «$INSTDIR» پیدا نشد.$\r$\nابتدا نصب‌کننده کامل را اجرا کنید."
    Abort
  ${EndIf}

  DetailPrint "Extracting update package..."
  RMDir /r "${UPDATE_TEMP}"
  SetOutPath "${UPDATE_TEMP}"
  File /r /x python /x .artifacts /x __pycache__ /x .pytest_cache /x .runtime /x data /x *.pyc /x *.pyo /x *.sqlite3 /x *.sqlite3-wal /x *.sqlite3-shm /x *.db /x *.log /x .env "${STAGING_DIR}\*.*"

  DetailPrint "Stopping GameNet Server service..."
  nsExec::ExecToLog 'net stop ${SERVICE_NAME}'
  nsExec::ExecToLog 'taskkill /F /IM GameNet_Server.exe /T'
  nsExec::ExecToLog 'taskkill /F /IM GameNet_Service.exe /T'
  Sleep 2000

  DetailPrint "Applying backend and deploy files (data is preserved)..."
  nsExec::ExecToLog 'robocopy "${UPDATE_TEMP}\backend" "$INSTDIR\backend" /E /XD data __pycache__ .venv /XF *.sqlite3* *.db *.log .env /R:1 /W:1'
  nsExec::ExecToLog 'robocopy "${UPDATE_TEMP}\deploy" "$INSTDIR\deploy" /E /XD python __pycache__ /R:1 /W:1'
  nsExec::ExecToLog 'robocopy "${UPDATE_TEMP}\python-deps" "$INSTDIR\deploy\windows\python\Lib\site-packages" /E /R:1 /W:1'
  Pop $0
  ${If} $0 >= 8
    SetErrorLevel 1
    Abort "Could not update Python dependencies."
  ${EndIf}

  DetailPrint "Applying server binaries and launchers..."
  SetOutPath "$INSTDIR"
  CopyFiles /SILENT "${UPDATE_TEMP}\*.exe" "$INSTDIR"
  CopyFiles /SILENT "${UPDATE_TEMP}\*.bat" "$INSTDIR"
  CopyFiles /SILENT "${UPDATE_TEMP}\*.vbs" "$INSTDIR"

  DetailPrint "Running database migrations..."
  SetOutPath "$INSTDIR\backend"
  nsExec::ExecToLog 'cmd /c cd /d "$INSTDIR\backend" && set GAMENET_ROLE=edge && set DJANGO_SETTINGS_MODULE=gamenet.settings.edge && set PYTHONUTF8=1 && "$INSTDIR\deploy\windows\python\python.exe" manage.py migrate --noinput'
  Pop $0
  ${If} $0 != 0
    SetErrorLevel 1
    Abort "Database migration failed. Service remains stopped; check the installer log."
  ${EndIf}

  DetailPrint "Collecting static assets..."
  nsExec::ExecToLog 'cmd /c cd /d "$INSTDIR\backend" && set GAMENET_ROLE=edge && set DJANGO_SETTINGS_MODULE=gamenet.settings.edge && set PYTHONUTF8=1 && "$INSTDIR\deploy\windows\python\python.exe" manage.py collectstatic --noinput'

  DetailPrint "Starting service..."
  nsExec::ExecToLog 'net start ${SERVICE_NAME}'
  IfErrors 0 +2
    nsExec::ExecToLog '"$INSTDIR\GameNet_Service.exe" --ensure-running'

  RMDir /r "${UPDATE_TEMP}"
  DetailPrint "Update to ${PRODUCT_VERSION} completed."
SectionEnd

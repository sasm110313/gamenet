; GameNet Salon Server & Admin Panel Installer (NSIS Unicode x64)
Unicode True
SetCompressor /SOLID lzma
SetCompressorDictSize 32

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"

!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "0.2.2"
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

!define APP_NAME "بازی سرای رهرو - سرور مدیریت سالن"
!define APP_SHORT_NAME "GameNet Server"
!define SERVICE_NAME "GameNetServer"
!define UNINST_REG_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${SERVICE_NAME}"
!define SM_FOLDER "بازی سرای رهرو (GameNet Server)"

Name "${APP_SHORT_NAME} ${PRODUCT_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$PROGRAMFILES64\GameNet Server"
InstallDirRegKey HKLM "${UNINST_REG_KEY}" "InstallLocation"
RequestExecutionLevel admin
ManifestSupportedOS all
ShowInstDetails show
ShowUnInstDetails show

!define MUI_ICON "${ICON_FILE}"
!define MUI_UNICON "${ICON_FILE}"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\GameNet_Server.exe"
!define MUI_FINISHPAGE_RUN_TEXT "باز کردن اپلیکیشن مدیریت سالن گیم‌نت (GameNet Server)"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Function .onInit
  UserInfo::GetAccountType
  Pop $0
  ${If} $0 != "Admin"
    MessageBox MB_ICONSTOP|MB_OK "Administrator privileges are required to install GameNet Server."
    Abort
  ${EndIf}

  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP|MB_OK "GameNet Server requires 64-bit Windows (Windows 10 / 11 x64)."
    Abort
  ${EndIf}

  ${If} ${Silent}
    SetSilent silent
  ${EndIf}
FunctionEnd

Section "GameNet Salon Server & Admin Panel" SEC_MAIN
  SectionIn RO
  SetShellVarContext all

  DetailPrint "Stopping existing GameNet Server services and processes..."
  IfFileExists "$INSTDIR\GameNet_Service.exe" 0 +3
    nsExec::ExecToLog '"$INSTDIR\GameNet_Service.exe" --uninstall'
    Pop $0
  nsExec::ExecToLog 'sc.exe stop ${SERVICE_NAME}'
  Pop $0
  nsExec::ExecToLog 'taskkill.exe /F /IM GameNet_Server.exe /T'
  Pop $0
  nsExec::ExecToLog 'taskkill.exe /F /IM GameNet_Service.exe /T'
  Pop $0
  Sleep 1200

  DetailPrint "Extracting standalone server files (no external dependencies required)..."
  SetOutPath "$INSTDIR"
  File /r "${STAGING_DIR}\*.*"

  DetailPrint "Configuring Windows service, database migrations, certificates and firewall..."
  nsExec::ExecToLog '"$INSTDIR\GameNet_Service.exe" --setup'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP|MB_OK "Server setup failed with exit code $0.$\r$\nPlease check log: $INSTDIR\backend\data\setup.log"
    Abort "GameNet Server setup failed ($0)."
  ${EndIf}

  DetailPrint "Creating Desktop and Start Menu shortcuts..."
  CreateDirectory "$SMPROGRAMS\${SM_FOLDER}"
  CreateShortcut "$DESKTOP\بازی سرای رهرو - مدیریت سالن.lnk" "$INSTDIR\GameNet_Server.exe" "" "$INSTDIR\deploy\windows\assets\gamenet-server.ico" 0 SW_SHOWNORMAL "" "اپلیکیشن مدیریت سالن بازی سرای رهرو"
  CreateShortcut "$SMPROGRAMS\${SM_FOLDER}\مدیریت سالن (Admin Panel).lnk" "$INSTDIR\GameNet_Server.exe" "" "$INSTDIR\deploy\windows\assets\gamenet-server.ico" 0
  CreateShortcut "$SMPROGRAMS\${SM_FOLDER}\تغییر نام کاربری و رمز مدیر.lnk" "$INSTDIR\change_admin_credentials.bat" "" "$INSTDIR\deploy\windows\assets\gamenet-server.ico" 0
  CreateShortcut "$SMPROGRAMS\${SM_FOLDER}\حذف کامل سرور (Uninstall).lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\deploy\windows\assets\gamenet-server.ico" 0

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  WriteRegStr HKLM "${UNINST_REG_KEY}" "DisplayName" "${APP_NAME} (${APP_SHORT_NAME})"
  WriteRegStr HKLM "${UNINST_REG_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKLM "${UNINST_REG_KEY}" "Publisher" "Rahro GameNet"
  WriteRegStr HKLM "${UNINST_REG_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_REG_KEY}" "DisplayIcon" "$INSTDIR\deploy\windows\assets\gamenet-server.ico"
  WriteRegStr HKLM "${UNINST_REG_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${UNINST_REG_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_REG_KEY}" "NoRepair" 1

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINST_REG_KEY}" "EstimatedSize" $0
SectionEnd

Section "Uninstall"
  SetShellVarContext all

  DetailPrint "Stopping and removing GameNetServer Windows Service..."
  nsExec::ExecToLog 'taskkill.exe /F /IM GameNet_Server.exe /T'
  Pop $0
  nsExec::ExecToLog '"$INSTDIR\GameNet_Service.exe" --uninstall'
  Pop $0
  nsExec::ExecToLog 'taskkill.exe /F /IM GameNet_Service.exe /T'
  Pop $0
  Sleep 800

  DetailPrint "Removing shortcuts..."
  Delete "$DESKTOP\بازی سرای رهرو - مدیریت سالن.lnk"
  Delete "$DESKTOP\بازی سرای رهرو (GameNet).lnk"
  Delete "$DESKTOP\مدیریت گیم‌نت (GameNet Server).lnk"
  RMDir /r "$SMPROGRAMS\${SM_FOLDER}"

  StrCpy $R9 "NO"
  ${Unless} ${Silent}
    MessageBox MB_YESNO|MB_ICONQUESTION "آیا مایلید دیتابیس محلی و تنظیمات سرور (backend\data و .env) نیز کاملاً پاک شوند؟$\r$\n(برای حفظ سوابق و بکاپ سالن گزینه No را بزنید)" IDYES del_data IDNO keep_data
    del_data:
      StrCpy $R9 "YES"
    keep_data:
  ${EndUnless}

  DetailPrint "Removing installed application files..."
  Delete "$INSTDIR\GameNet_Server.exe"
  Delete "$INSTDIR\GameNet_Service.exe"
  Delete "$INSTDIR\GameNet_Server.bat"
  Delete "$INSTDIR\Open_Admin_Panel.bat"
  Delete "$INSTDIR\Install_GameNet_Server.bat"
  Delete "$INSTDIR\change_admin_credentials.bat"
  Delete "$INSTDIR\Uninstall_GameNet_Server.bat"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR\deploy"
  RMDir /r "$INSTDIR\dev"
  RMDir /r "$INSTDIR\.artifacts\static"
  RMDir /r "$INSTDIR\backend\apps"
  RMDir /r "$INSTDIR\backend\gamenet"
  RMDir /r "$INSTDIR\backend\templates"
  RMDir /r "$INSTDIR\backend\static"
  Delete "$INSTDIR\backend\manage.py"

  ${If} $R9 == "YES"
    RMDir /r "$INSTDIR\backend\data"
    RMDir /r "$INSTDIR\backend\.runtime"
    RMDir /r "$INSTDIR\.artifacts"
    Delete "$INSTDIR\.env"
    RMDir "$INSTDIR\backend"
    RMDir "$INSTDIR"
  ${Else}
    RMDir "$INSTDIR\backend"
    RMDir "$INSTDIR"
  ${EndIf}

  DeleteRegKey HKLM "${UNINST_REG_KEY}"
SectionEnd

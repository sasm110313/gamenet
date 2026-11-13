; GameNet Client — standalone elevated updater (copies app.asar into Program Files)
Unicode True
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "0.2.4"
!endif

!ifndef ASAR_FILE
  !error "ASAR_FILE must be defined"
!endif

!ifndef OUT_FILE
  !error "OUT_FILE must be defined"
!endif

!define APP_SHORT_NAME "GameNet"
!define UPDATE_TEMP "$TEMP\gamenet_client_update"

Name "${APP_SHORT_NAME} Update ${PRODUCT_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$PROGRAMFILES\GameNet"
RequestExecutionLevel admin
ManifestSupportedOS all
ShowInstDetails show
BrandingText "GameNet Client Updater ${PRODUCT_VERSION}"

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "به‌روزرسانی کلاینت GameNet"
!define MUI_WELCOMEPAGE_TEXT "این برنامه فایل app.asar نسخه ${PRODUCT_VERSION} را روی نصب فعلی کلاینت جایگزین می‌کند.$\r$\n$\r$\nتنظیمات اتصال و پین گواهی دستگاه حفظ می‌شوند."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

Section "Update"
  ; Locate the existing installation (per-machine, 32-bit app).
  ${If} ${FileExists} "$PROGRAMFILES\GameNet\GameNet.exe"
    StrCpy $INSTDIR "$PROGRAMFILES\GameNet"
  ${ElseIf} ${FileExists} "$PROGRAMFILES64\GameNet\GameNet.exe"
    StrCpy $INSTDIR "$PROGRAMFILES64\GameNet"
  ${ElseIf} ${FileExists} "$PROGRAMFILES32\GameNet\GameNet.exe"
    StrCpy $INSTDIR "$PROGRAMFILES32\GameNet"
  ${Else}
    MessageBox MB_ICONSTOP "نصب GameNet روی این سیستم پیدا نشد.$\r$\nابتدا نصب‌کننده کامل GameNet را اجرا کنید."
    Abort
  ${EndIf}

  DetailPrint "Found installation at $INSTDIR"
  SetOutPath "${UPDATE_TEMP}"
  File "${ASAR_FILE}"

  DetailPrint "Stopping GameNet client..."
  nsExec::ExecToLog 'taskkill /F /IM GameNet.exe /T'
  Sleep 2500

  DetailPrint "Replacing app.asar..."
  CreateDirectory "$INSTDIR\resources"
  StrCpy $R0 0
  retry_copy:
    CopyFiles /SILENT "${UPDATE_TEMP}\app.asar" "$INSTDIR\resources"
    IfErrors 0 copy_ok
    Sleep 900
    IntOp $R0 $R0 + 1
    IntCmp $R0 6 copy_failed
    Goto retry_copy

  copy_failed:
    MessageBox MB_ICONSTOP "جایگزینی فایل برنامه ناموفق بود.$\r$\nکلاینت را ببندید و این برنامه را با دسترسی Administrator دوباره اجرا کنید."
    Abort

  copy_ok:
  ${IfNot} ${FileExists} "$INSTDIR\resources\app.asar"
    MessageBox MB_ICONSTOP "جایگزینی فایل برنامه ناموفق بود.$\r$\nکلاینت را ببندید و این برنامه را با دسترسی Administrator دوباره اجرا کنید."
    Abort
  ${EndIf}

  RMDir /r "${UPDATE_TEMP}"

  MessageBox MB_ICONINFORMATION|MB_OK "کلاینت با موفقیت به نسخه ${PRODUCT_VERSION} به‌روزرسانی شد.$\r$\nبرنامه در ورود بعدی کاربر به‌صورت خودکار اجرا می‌شود."
SectionEnd

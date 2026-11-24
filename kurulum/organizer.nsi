; Organizer — Windows kurulumu (GitHub Actions'ta üretilir; win-setup kanalı).
;   makensis -DVERSION=2.2.0 -DSRC=<PyInstaller klasörü dist\Organizer> -DOUT=<Organizer-Setup-2.2.0.exe> -DICON=<logo.ico> organizer.nsi
; Kullanıcı başına kurulur (yönetici izni gerekmez): %LOCALAPPDATA%\Programs\Organizer — fccore güncelleyicisi (win-app)
; bu klasörü yerinde yenileyebilsin diye. Tek tık (oneClick): soru sormadan kurar ve programı açar. Dil: Türkçe / English /
; العربية (Windows diline göre). Kayıtlar (%APPDATA%\Organizer) kurulumla ya da kaldırmayla DEĞİŞMEZ.
Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user
!define NAME "Organizer"
!define EXE "Organizer.exe"
!define REGKEY "Organizer"
!define UNKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${REGKEY}"

Name "${NAME}"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Programs\${REGKEY}"
InstallDirRegKey HKCU "Software\${REGKEY}" "InstallDir"
BrandingText "${NAME} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "${NAME}"
VIAddVersionKey /LANG=1033 "FileDescription" "${NAME} Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "departures-mil"
ShowInstDetails nevershow
AutoCloseWindow true

!include MUI2.nsh
!ifdef ICON
  !define MUI_ICON "${ICON}"
  !define MUI_UNICON "${ICON}"
!endif
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Turkish"
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Arabic"

LangString RUNNING ${LANG_TURKISH} "Organizer kuruluyor…"
LangString RUNNING ${LANG_ENGLISH} "Installing Organizer…"
LangString RUNNING ${LANG_ARABIC} "جارٍ تثبيت Organizer…"

Function .onInit
  ; Windows dili: Türkçe / Arapça, yoksa İngilizce
  System::Call 'kernel32::GetUserDefaultUILanguage() i .r0'
  IntOp $1 $0 & 0x3FF
  StrCpy $LANGUAGE ${LANG_ENGLISH}
  IntCmp $1 0x1F 0 +2 +2
    StrCpy $LANGUAGE ${LANG_TURKISH}
  IntCmp $1 0x01 0 +2 +2
    StrCpy $LANGUAGE ${LANG_ARABIC}
FunctionEnd

Section "Install"
  SetShellVarContext current
  DetailPrint "$(RUNNING)"
  ; Açık program varsa kapat ki üstüne yazılabilsin (güncelleme sırasında program kendisi kapanır)
  nsExec::Exec 'taskkill /F /IM "${EXE}"'
  Sleep 600
  ; Eski sürümün program dosyaları (kayıtlar başka yerde: %APPDATA%\Organizer)
  RMDir /r "$INSTDIR\_internal"
  SetOutPath "$INSTDIR"
  File /r "${SRC}\*.*"
  CreateShortCut "$DESKTOP\${NAME}.lnk" "$INSTDIR\${EXE}"
  CreateDirectory "$SMPROGRAMS\${NAME}"
  CreateShortCut "$SMPROGRAMS\${NAME}\${NAME}.lnk" "$INSTDIR\${EXE}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\${REGKEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "DisplayName" "${NAME}"
  WriteRegStr HKCU "${UNKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNKEY}" "Publisher" "departures-mil"
  WriteRegStr HKCU "${UNKEY}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${UNKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNKEY}" "NoRepair" 1
  ; Kurulumdan sonra programı aç (tek tık kurulum; güncellemede de program yeniden açılır)
  Exec '"$INSTDIR\${EXE}"'
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  ; Kayıtlar (%APPDATA%\Organizer) silinmez; yalnız program dosyaları kaldırılır
  nsExec::Exec 'taskkill /F /IM "${EXE}"'
  Delete "$DESKTOP\${NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${NAME}"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNKEY}"
  DeleteRegKey HKCU "Software\${REGKEY}"
SectionEnd

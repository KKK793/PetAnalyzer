@echo off
setlocal
cd /d "%~dp0"

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  set "ISCC=ISCC.exe"
)

if not exist "dist\PetAnalyzer\PetAnalyzer.exe" (
  call build_float_desktop.bat
)

if exist "dist\PetAnalyzer\_internal\data" (
  if not exist "dist\PetAnalyzer\data" (
    move "dist\PetAnalyzer\_internal\data" "dist\PetAnalyzer\data" >nul
  )
)
if exist "dist\PetAnalyzer\_internal\assets" (
  if not exist "dist\PetAnalyzer\assets" (
    move "dist\PetAnalyzer\_internal\assets" "dist\PetAnalyzer\assets" >nul
  )
)

"%ISCC%" installer_inno.iss

echo.
echo Installer output: dist\PetAnalyzerSetup.exe
pause

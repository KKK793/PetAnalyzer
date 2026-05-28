@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pyinstaller.exe" (
  set "PYINSTALLER=.venv\Scripts\pyinstaller.exe"
) else (
  set "PYINSTALLER=pyinstaller"
)

if not exist "dist\PocketBoleFloat.exe" (
  call build_float_desktop.bat
)

"%PYINSTALLER%" --clean --noconsole --onefile --name PocketBoleFloatSetup --icon "assets\app.ico" --add-data "dist\PocketBoleFloat.exe;payload" --add-data "assets;assets" --add-data "data\pet_plans.json;data" --hidden-import win32com.client --hidden-import pythoncom installer.py

echo.
echo Installer output: dist\PocketBoleFloatSetup.exe
pause

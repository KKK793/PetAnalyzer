@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pyinstaller.exe" (
  set "PYINSTALLER=.venv\Scripts\pyinstaller.exe"
) else (
  set "PYINSTALLER=pyinstaller"
)

"%PYINSTALLER%" -y --clean --noconsole --onedir --contents-directory "_internal" --name PetAnalyzer --icon "assets\app.ico" --add-data "data;data" --add-data "assets;assets" --collect-all rapidocr --collect-all windows_capture --hidden-import win32timezone --exclude-module tkinter --exclude-module _tkinter desktop_float.py

if exist "dist\PetAnalyzer\_internal\data" (
  if exist "dist\PetAnalyzer\data" rmdir /s /q "dist\PetAnalyzer\data"
  move "dist\PetAnalyzer\_internal\data" "dist\PetAnalyzer\data" >nul
)
if exist "dist\PetAnalyzer\_internal\assets" (
  if exist "dist\PetAnalyzer\assets" rmdir /s /q "dist\PetAnalyzer\assets"
  move "dist\PetAnalyzer\_internal\assets" "dist\PetAnalyzer\assets" >nul
)

echo.
echo Build output: dist\PetAnalyzer\PetAnalyzer.exe
pause

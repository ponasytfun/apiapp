@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Checking Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
  echo Python was not found in PATH.
  echo Install Python 3.11 or newer, then run this file again.
  pause
  exit /b 1
)

echo [2/4] Installing/updating PyInstaller...
python -m pip install --upgrade pip pyinstaller
if %errorlevel% neq 0 (
  echo Failed to install PyInstaller.
  pause
  exit /b 1
)

echo [3/4] Building API-App.exe...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name API-App ^
  desktop_app.py

if %errorlevel% neq 0 (
  echo Build failed.
  pause
  exit /b 1
)

echo [4/4] Done.
echo.
echo Executable created at:
echo %CD%\dist\API-App.exe
echo.
pause

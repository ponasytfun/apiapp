@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python app.py
  exit /b %errorlevel%
)
where py >nul 2>nul
if %errorlevel%==0 (
  py app.py
  exit /b %errorlevel%
)
echo Python 3 was not found. Install Python 3 and try again.
pause
exit /b 1

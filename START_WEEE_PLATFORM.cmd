@echo off
setlocal EnableExtensions
cd /d "%~dp0backend"

set "PYLAUNCH="
where py >nul 2>nul && set "PYLAUNCH=py -3"
if not defined PYLAUNCH (
  where python >nul 2>nul && set "PYLAUNCH=python"
)
if not defined PYLAUNCH (
  echo Python 3.12+ is required.
  echo Install Python from python.org and enable Add Python to PATH.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating local environment...
  %PYLAUNCH% -m venv .venv
  if errorlevel 1 goto :venv_error
)
if not exist ".venv\Scripts\python.exe" goto :venv_error

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo Failed to install required Python packages.
  pause
  exit /b 1
)

echo.
echo ==========================================================
echo WEEE PLATFORM - WINDOWS + ANDROID
echo Windows: http://127.0.0.1:8000/desktop
echo Android: use http://THIS-PC-IP:8000 in the Server button.
echo PC IPv4 addresses:
ipconfig | findstr /i "IPv4"
echo ==========================================================
start "" http://127.0.0.1:8000/desktop
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
exit /b %errorlevel%

:venv_error
echo.
echo Could not create the local Python environment (.venv).
echo Python detected with: %PYLAUNCH%
echo Please run: %PYLAUNCH% -m venv .venv
pause
exit /b 1

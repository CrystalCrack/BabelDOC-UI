@echo off
setlocal
cd /d "%~dp0"

echo BabelDOC UI installer
echo.
echo This will install the local Python environment and create desktop/Start Menu shortcuts.
echo The first run can take a while because dependencies and BabelDOC assets may be downloaded.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
if errorlevel 1 (
  echo.
  echo Installation failed. Please keep this window open and check the error above.
  pause
  exit /b 1
)

echo.
echo Installation complete. You can now launch BabelDOC UI from the desktop shortcut.
pause

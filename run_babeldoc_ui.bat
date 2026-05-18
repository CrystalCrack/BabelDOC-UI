@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Run scripts\setup_windows.ps1 first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m babeldoc.ui_app

@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Installing NOVA requirements...
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Installation failed. Check your internet connection and Python installation.
  pause
  exit /b 1
)
echo Starting NOVA Desktop 2.0...
py nova_desktop.py
if errorlevel 1 pause

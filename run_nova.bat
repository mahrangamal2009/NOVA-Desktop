@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ====================================
echo   NOVA Desktop 3.0 - Launcher
echo ====================================
echo.

:: Check Python
where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not found in PATH.
    echo Please install Python 3.10 or later from https://python.org
    echo.
    pause
    exit /b 1
)

:: Check Python version
echo Checking Python version...
py --version 2>nul
if errorlevel 1 (
    echo ERROR: Unable to run Python.
    echo.
    pause
    exit /b 1
)

:: Install dependencies
echo Installing/updating dependencies...
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies. Check your internet connection.
    echo.
    pause
    exit /b 1
)

echo.
echo Starting NOVA Desktop 3.0...
py nova_desktop.py
if errorlevel 1 (
    echo.
    echo ERROR: NOVA Desktop failed to start.
    echo.
    pause
    exit /b 1
)
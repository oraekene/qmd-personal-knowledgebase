@echo off
setlocal
title QMD Personal Knowledgebase
echo ======================================================================
echo   Launching QMD Personal Knowledgebase Desktop App...
echo ======================================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in your PATH.
    echo Please install Python 3.10+ from https://python.org or the Microsoft Store.
    pause
    exit /b 1
)

python "%~dp0scripts\run_desktop.py" %*
if %errorlevel% neq 0 (
    echo.
    echo [INFO] Desktop application closed.
)

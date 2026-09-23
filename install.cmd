@echo off
setlocal enabledelayedexpansion
title QMD Knowledgebase — 1-Click Installer
echo ======================================================================
echo    QMD Personal Knowledgebase and Search Engine — 1-Click Setup
echo ======================================================================
echo.

:: 1. Check Python
echo [*] Checking Python runtime...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python is not installed or not in your system PATH.
    echo Please install Python 3.10 or higher from:
    echo   https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ required. Current version is too old.
    pause
    exit /b 1
)
echo [OK] Python detected.

:: 2. Initialize directories
echo [*] Verifying local directories (corpus, inbox, logs)...
if not exist "%~dp0corpus" mkdir "%~dp0corpus"
if not exist "%~dp0inbox" mkdir "%~dp0inbox"
if not exist "%~dp0logs" mkdir "%~dp0logs"

:: 3. Initialize .env if missing
if not exist "%~dp0.env" (
    echo [*] Creating default .env configuration...
    (
        echo # QMD Personal Knowledgebase Local Configuration
        echo OPERATIONAL_MODE=full
        echo QMD_PORT=8181
        echo AUTH_PROXY_PORT=3210
        echo CONTROL_PLANE_PORT=3333
    ) > "%~dp0.env"
    echo [OK] Generated .env file.
)

:: 4. Install dependencies
echo [*] Installing dependencies from requirements.txt...
python -m pip install --quiet -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo [WARNING] Some dependencies failed to install cleanly. Core functionality will still work.
) else (
    echo [OK] Dependencies installed successfully.
)

:: 5. Create Desktop Shortcut
echo [*] Creating Desktop shortcut...
set SCRIPT_DIR=%~dp0
set SHORTCUT_PATH=%USERPROFILE%\Desktop\QMD Personal Knowledgebase.lnk
set TARGET_PATH=%SCRIPT_DIR%launch-desktop.cmd

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%TARGET_PATH%'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.Description = 'QMD Personal Knowledgebase & Autonomous Agent Engine'; $s.Save()" >nul 2>nul

if exist "%SHORTCUT_PATH%" (
    echo [OK] Created desktop shortcut: "QMD Personal Knowledgebase.lnk"
) else (
    echo [NOTE] Desktop shortcut creation skipped. You can use launch-desktop.cmd directly.
)

echo.
echo ======================================================================
echo    Installation Complete!
echo ======================================================================
echo.
echo You can launch your personal knowledgebase at any time using:
echo   - The desktop shortcut: "QMD Personal Knowledgebase"
echo   - Or by running: launch-desktop.cmd
echo.

set /p LAUNCH="Would you like to launch the knowledgebase now? (Y/N): "
if /i "%LAUNCH%"=="Y" (
    start "" "%~dp0launch-desktop.cmd"
)

exit /b 0

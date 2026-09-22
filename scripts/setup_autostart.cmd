@echo off
REM Registers silent startup shortcut in Windows User Startup folder
REM Launches QMD Control Plane silently on user login

set SCRIPT_DIR=%~dp0
set VBS_TARGET=%SCRIPT_DIR%start_control_plane.vbs
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT_PATH=%STARTUP_DIR%\QMD_Control_Plane.lnk

echo Setting up QMD Control Plane silent autostart on Windows login...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = 'wscript.exe'; $s.Arguments = '`\"%VBS_TARGET%`\"'; $s.WorkingDirectory = '%SCRIPT_DIR%..'; $s.Description = 'QMD Knowledgebase Control Plane'; $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo [OK] Autostart successfully configured at:
    echo      %SHORTCUT_PATH%
    echo QMD Control Plane will now run silently on startup without a PowerShell window!
) else (
    echo [ERROR] Failed to create shortcut in %STARTUP_DIR%
)
pause

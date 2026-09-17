@echo off
setlocal
echo =======================================================
echo   Starting QMD Personal Knowledgebase Control Plane...
echo =======================================================
start http://127.0.0.1:3333
where uv >nul 2>nul
if %errorlevel% equ 0 (
    uv run python -m control_plane.server --port 3333
) else (
    python -m control_plane.server --port 3333
)
pause

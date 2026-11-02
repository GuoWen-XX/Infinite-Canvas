@echo off
cd /d "%~dp0"

set "PYEXE=%~dp0python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

rem If another instance is already listening on port 3000, reuse it instead
rem of starting a second server (which causes WinError 10048).
powershell -NoProfile -Command "$listener = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue; if ($listener) { exit 2 }"
if errorlevel 2 (
    echo Infinite Canvas is already running at http://127.0.0.1:3000/
    start "" http://127.0.0.1:3000/
    exit /b 0
)

echo Starting ComfyUI-API-Modelscope...
echo Visit: http://127.0.0.1:3000/
echo Press Ctrl+C to stop.
echo.

start /b powershell -NoProfile -WindowStyle Hidden -Command "$url = 'http://127.0.0.1:3000/'; for ($i = 0; $i -lt 60; $i++) { Start-Sleep -Milliseconds 500; if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) { Start-Process $url; break } }"
"%PYEXE%" main.py

echo.
echo Server stopped.
pause

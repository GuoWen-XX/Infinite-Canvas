@echo off
cd /d "%~dp0"

set "PYEXE=%~dp0python\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"

rem Detect if local proxy is listening on 127.0.0.1:7897; inject proxy only if reachable
"%PYEXE%" -c "import socket; s = socket.socket(); s.settimeout(0.3); exit(0 if s.connect_ex(('127.0.0.1', 7897)) == 0 else 1)" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [Proxy] Detected active local proxy at 127.0.0.1:7897, proxy env enabled.
    set "HTTP_PROXY=http://127.0.0.1:7897"
    set "HTTPS_PROXY=http://127.0.0.1:7897"
    set "ALL_PROXY=http://127.0.0.1:7897"
    set "NO_PROXY=localhost,127.0.0.1,100.*,10.*,172.16.*,172.17.*,172.18.*,172.19.*,172.20.*,172.21.*,172.22.*,172.23.*,172.24.*,172.25.*,172.26.*,172.27.*,172.28.*,172.29.*,172.30.*,172.31.*,192.168.*"
    if "%IC_ENABLE_TAILSCALE_BYPASS_WATCHDOG%"=="1" (
        "%PYEXE%" scripts\ensure_tailscale_bypass.py >nul 2>&1
    )
) else (
    echo [Proxy] No proxy detected at 127.0.0.1:7897, connecting directly.
)

echo Starting MeansCanvas (开卷画布)...
echo Visit: http://127.0.0.1:3333/
echo Press Ctrl+C to stop.
echo.

start /b cmd /c "ping 127.0.0.1 -n 4 >nul & start http://127.0.0.1:3333/"
"%PYEXE%" main.py

echo.
echo Server stopped.
pause

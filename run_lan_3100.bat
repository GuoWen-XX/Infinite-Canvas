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
    set "NO_PROXY=localhost,127.0.0.1"
) else (
    echo [Proxy] No proxy detected at 127.0.0.1:7897, connecting directly.
)

rem Check IC_ACCESS_TOKEN configuration
"%PYEXE%" -c "from core.providers import get_configured_access_token; exit(0 if get_configured_access_token() else 1)" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [安全提示] 未检测到 IC_ACCESS_TOKEN 配置。
    echo           当前服务以 0.0.0.0 局域网模式启动，同网段任何设备均可无认证访问 /api/*。
    echo           建议在 API/.env 中设置 IC_ACCESS_TOKEN 保护你的 API 额度与凭据。
    echo.
) else (
    echo [安全认证] IC_ACCESS_TOKEN 已启用，API 请求已受访问令牌保护。
    echo.
)

echo.
echo ==================================================
echo   MeansCanvas LAN Server  (0.0.0.0:3100)
echo --------------------------------------------------
echo   Local  :  http://127.0.0.1:3100/
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { Write-Host ('   LAN   :  http://' + $_.IPAddress + ':3100/') }"
echo --------------------------------------------------
echo   If LAN devices cannot connect, run
echo   firewall_open_3100.bat as Administrator once.
echo ==================================================
echo Press Ctrl+C to stop.
echo.

start /b cmd /c "ping 127.0.0.1 -n 4 >nul & start http://127.0.0.1:3100/"
"%PYEXE%" main.py --host 0.0.0.0 --port 3100

echo.
echo Server stopped.
pause

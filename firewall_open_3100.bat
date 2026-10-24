@echo off
rem Opens inbound TCP port 3100 in Windows Firewall so LAN devices
rem can reach the Infinite-Canvas server. Run as Administrator.

net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Administrator privileges required.
    echo     Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

rem Remove stale rule with the same name, then add fresh ones.
netsh advfirewall firewall delete rule name="Infinite-Canvas 3100" >nul 2>&1
netsh advfirewall firewall add rule name="Infinite-Canvas 3100" dir=in action=allow protocol=TCP localport=3100 profile=any
if %ERRORLEVEL% equ 0 (
    echo [OK] Inbound TCP 3100 is now open for LAN access.
) else (
    echo [!] Failed to add firewall rule.
)

pause

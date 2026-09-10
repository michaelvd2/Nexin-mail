@echo off
setlocal
for %%I in ("%~dp0..") do set "DASHBOARD_ROOT=%%~fI"
for %%I in ("%DASHBOARD_ROOT%\..\imap-plugin") do set "BACKEND_ROOT=%%~fI"
if not exist "%DASHBOARD_ROOT%\src\imap_dashboard\server.py" exit /b 70
if not exist "%BACKEND_ROOT%\.codex-plugin\plugin.json" exit /b 70
if not exist "%BACKEND_ROOT%\src\imap_plugin\server.py" exit /b 70
if not exist "%BACKEND_ROOT%\runtime\python\python.exe" exit /b 70
set "PYTHONPATH=%DASHBOARD_ROOT%\src;%BACKEND_ROOT%\src"
set "PYTHONDONTWRITEBYTECODE=1"
"%BACKEND_ROOT%\runtime\python\python.exe" -m imap_dashboard.server
exit /b %ERRORLEVEL%

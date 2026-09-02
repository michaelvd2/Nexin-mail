@echo off
setlocal
for %%I in ("%~dp0..") do set "PLUGIN_ROOT=%%~fI"
set "PYTHONPATH=%PLUGIN_ROOT%\src"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%PLUGIN_ROOT%\runtime\python\python.exe" exit /b 70
"%PLUGIN_ROOT%\runtime\python\python.exe" -m imap_plugin.cli doctor
exit /b %ERRORLEVEL%

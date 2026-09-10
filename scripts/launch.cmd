@echo off
setlocal
for %%I in ("%~dp0..") do set "PLUGIN_ROOT=%%~fI"
set "PYTHONPATH=%PLUGIN_ROOT%\src"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHON=%NEXIN_MAIL_PYTHON%"
if not defined PYTHON set "PYTHON=python"
"%PYTHON%" -B -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 70)"
if errorlevel 1 exit /b 70
"%PYTHON%" -B -X utf8 -m nexin_mail.server
exit /b %ERRORLEVEL%

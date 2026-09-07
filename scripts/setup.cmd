@echo off
setlocal
set "PYTHONPATH=%~dp0..\src"
set "PYTHONDONTWRITEBYTECODE=1"
"%~dp0..\runtime\python\python.exe" -X utf8 "%~dp0configure.py" %*
exit /b %errorlevel%

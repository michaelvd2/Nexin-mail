@echo off
setlocal
powershell.exe -NoLogo -NoProfile -STA -File "%~dp0enroll_gui.ps1"
exit /b %ERRORLEVEL%

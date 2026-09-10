@echo off
setlocal
if not exist "%~dp0payload\runtime\python\python.exe" (
  echo Nexin Mail: de meegeleverde runtime ontbreekt. Gebruik het volledige geverifieerde pakket.
  exit /b 70
)
if not defined LOCALAPPDATA (
  echo Nexin Mail: Local AppData is niet beschikbaar; er is niets gewijzigd.
  exit /b 69
)
set "INSTALL_ROOT=%LOCALAPPDATA%\Nexin Mail"
"%~dp0payload\runtime\python\python.exe" -B -X utf8 -m nexin_mail.install rollback --install-root "%INSTALL_ROOT%" %*
exit /b %ERRORLEVEL%

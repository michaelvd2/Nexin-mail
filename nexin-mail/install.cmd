@echo off
setlocal
if not exist "%~dp0payload\runtime\python\python.exe" (
  echo Nexin Mail: de meegeleverde runtime ontbreekt. Gebruik het volledige geverifieerde installatiepakket.
  exit /b 70
)
"%~dp0payload\runtime\python\python.exe" -B -X utf8 -m nexin_mail.install --setup --package "%~dp0." %*
exit /b %ERRORLEVEL%

$ErrorActionPreference = 'Stop'
$PluginRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $PluginRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'The pinned local runtime is missing.' }
$env:PYTHONPATH = Join-Path $PluginRoot 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
& $Python -m imap_plugin.cli doctor
exit $LASTEXITCODE

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$packageRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
& (Join-Path $packageRoot 'verify.ps1') | Out-Null
$dashboardSource = if (Test-Path -LiteralPath (Join-Path $packageRoot 'plugins\imap-dashboard\.codex-plugin\plugin.json') -PathType Leaf) {
    Join-Path $packageRoot 'plugins\imap-dashboard'
} else {
    $packageRoot
}

$localAppData = [Environment]::GetFolderPath('LocalApplicationData')
if ([string]::IsNullOrWhiteSpace($localAppData)) { throw 'Windows Local AppData is unavailable.' }
$programRoot = [IO.Path]::GetFullPath((Join-Path $localAppData 'IMAP Plugin')).TrimEnd('\')
$distribution = Join-Path $programRoot 'distribution'
$backend = Join-Path $distribution 'plugins\imap-plugin'
$python = Join-Path $backend 'runtime\python\python.exe'
$doctor = Join-Path $backend 'scripts\doctor.cmd'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install and verify the IMAP Plugin first.' }
if (-not (Test-Path -LiteralPath $doctor -PathType Leaf)) { throw 'The IMAP Plugin doctor is missing.' }

$doctorOutput = (& $doctor 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw "The IMAP Plugin did not pass its read-only doctor: $doctorOutput" }
$health = $doctorOutput | ConvertFrom-Json
if ($health.connectivity -ne 'pass') { throw 'The IMAP Plugin did not report verified read-only connectivity.' }

$installer = Join-Path $dashboardSource 'scripts\install_dashboard.py'
$installOutput = (& $python $installer --source-root $dashboardSource 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw "Dashboard installation failed: $installOutput" }
$receipt = $installOutput | ConvertFrom-Json
if (-not $receipt.reused_existing_connection -or $receipt.credentials_changed -or $receipt.configuration_changed) {
    throw 'The dashboard installer did not preserve the existing IMAP Plugin connection.'
}

$codex = Get-Command codex -ErrorAction Stop
& $codex.Source plugin add 'imap-dashboard@imap-plugin-handoff' --json | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'The dashboard files were installed, but Codex registration failed.' }

[ordered]@{
    status = 'installed_and_verified'
    plugin = 'imap-dashboard@imap-plugin-handoff'
    reused_existing_connection = $true
    credentials_changed = $false
    configuration_changed = $false
    backend_connectivity = 'pass'
    next_step = 'Start a new Codex task and ask it to open the IMAP Dashboard.'
} | ConvertTo-Json

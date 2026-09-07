[CmdletBinding()]
param(
    [switch]$SkipSetup,
    [switch]$ForceSetup,
    [string]$InstallRoot
)

$ErrorActionPreference = 'Stop'
$packetRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path

& (Join-Path $packetRoot 'verify.ps1') -Root $packetRoot | Out-Null

$codex = Get-Command codex -ErrorAction Stop
$localAppData = [Environment]::GetFolderPath('LocalApplicationData')
if ([string]::IsNullOrWhiteSpace($localAppData)) { throw 'Windows Local AppData is unavailable.' }
$programBase = if ($InstallRoot) { [IO.Path]::GetFullPath($InstallRoot) } else { Join-Path $localAppData 'IMAP Plugin' }
$programBase = [IO.Path]::GetFullPath($programBase).TrimEnd('\')
$distribution = [IO.Path]::GetFullPath((Join-Path $programBase 'distribution'))
$requiredPrefix = $programBase + '\'
if (-not $distribution.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Resolved installation directory escaped its intended parent.'
}
[IO.Directory]::CreateDirectory($programBase) | Out-Null

function Test-ImapMarketplaceRoot([string]$Candidate) {
    try {
        $root = [IO.Path]::GetFullPath($Candidate)
        $releasePath = Join-Path $root 'release.json'
        $pluginPath = Join-Path $root 'plugins\imap-plugin\.codex-plugin\plugin.json'
        if (-not (Test-Path -LiteralPath $releasePath -PathType Leaf) -or -not (Test-Path -LiteralPath $pluginPath -PathType Leaf)) { return $false }
        $candidateRelease = Get-Content -LiteralPath $releasePath -Raw | ConvertFrom-Json
        $candidatePlugin = Get-Content -LiteralPath $pluginPath -Raw | ConvertFrom-Json
        return $candidateRelease.product -eq 'imap-plugin-windows-handoff' -and $candidatePlugin.name -eq 'imap-plugin'
    } catch {
        return $false
    }
}

$backupPath = $null
if (-not $packetRoot.Equals($distribution, [StringComparison]::OrdinalIgnoreCase)) {
    $staging = [IO.Path]::GetFullPath((Join-Path $programBase ('.distribution-new-' + [Guid]::NewGuid().ToString('N'))))
    if (-not $staging.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid staging directory.' }
    [IO.Directory]::CreateDirectory($staging) | Out-Null
    try {
        Get-ChildItem -LiteralPath $packetRoot -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $staging -Recurse -Force
        }
        & (Join-Path $staging 'verify.ps1') -Root $staging | Out-Null
        if (Test-Path -LiteralPath $distribution) {
            $backups = Join-Path $programBase 'backups'
            [IO.Directory]::CreateDirectory($backups) | Out-Null
            $backupPath = Join-Path $backups ((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
            Move-Item -LiteralPath $distribution -Destination $backupPath
        }
        Move-Item -LiteralPath $staging -Destination $distribution
    } catch {
        if (Test-Path -LiteralPath $staging) {
            $stagingFull = [IO.Path]::GetFullPath($staging)
            if ($stagingFull.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                Remove-Item -LiteralPath $stagingFull -Recurse -Force
            }
        }
        if ($backupPath -and -not (Test-Path -LiteralPath $distribution) -and (Test-Path -LiteralPath $backupPath)) {
            Move-Item -LiteralPath $backupPath -Destination $distribution
        }
        throw
    }
}

$marketplaces = (& $codex.Source plugin marketplace list --json | Out-String) | ConvertFrom-Json
$existingMarketplace = @($marketplaces.marketplaces | Where-Object { $_.name -eq 'imap-plugin-handoff' }) | Select-Object -First 1
if ($existingMarketplace) {
    $existingRoot = [IO.Path]::GetFullPath([string]$existingMarketplace.root).TrimEnd('\')
    if (-not $existingRoot.Equals($distribution, [StringComparison]::OrdinalIgnoreCase)) {
        if (-not (Test-ImapMarketplaceRoot $existingRoot)) {
            throw 'A marketplace with the reserved IMAP Plugin handoff name points to an unknown location; nothing was replaced.'
        }
    }
}
if (-not $existingMarketplace) {
    & $codex.Source plugin marketplace add $distribution --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not register the local IMAP Plugin marketplace.' }
}
& $codex.Source plugin add 'imap-plugin@imap-plugin-handoff' --json | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not install the IMAP Plugin into Codex.' }

$pluginRoot = Join-Path $distribution 'plugins\imap-plugin'
$doctorCommand = Join-Path $pluginRoot 'scripts\doctor.cmd'
$alreadyHealthy = $false
if (-not $ForceSetup) {
    & $doctorCommand *> $null
    $alreadyHealthy = $LASTEXITCODE -eq 0
}
if (-not $SkipSetup -and ($ForceSetup -or -not $alreadyHealthy)) {
    $previousHost = $env:IMAP_PLUGIN_POWERSHELL
    try {
        $env:IMAP_PLUGIN_POWERSHELL = (Get-Process -Id $PID).Path
        & (Join-Path $pluginRoot 'scripts\setup.cmd')
        $setupExitCode = $LASTEXITCODE
    } finally {
        $env:IMAP_PLUGIN_POWERSHELL = $previousHost
    }
    if ($setupExitCode -ne 0) { throw 'De plugin is geregistreerd, maar de mailsetup is niet afgerond. Gebruik de foutcode hierboven voor gericht herstel; verander geen sandbox- of Windows-beveiliging automatisch.' }
}

$doctor = $null
if (-not $SkipSetup -or $alreadyHealthy) {
    $doctorOutput = (& $doctorCommand 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "The plugin installed, but the read-only mailbox acceptance failed: $doctorOutput" }
    $doctor = $doctorOutput | ConvertFrom-Json
    if ($doctor.connectivity -ne 'pass' -or $doctor.credentials.imap.persist -ne 2) {
        throw 'The plugin installed, but verified IMAP connectivity or local credential persistence did not pass.'
    }
}

$release = Get-Content -LiteralPath (Join-Path $distribution 'release.json') -Raw | ConvertFrom-Json
$receipt = [ordered]@{
    installed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    product = 'imap-plugin'
    version = [string]$release.version
    marketplace = 'imap-plugin-handoff'
    distribution = $distribution
    backup = $backupPath
    setup_skipped = [bool]$SkipSetup
    connectivity = if ($doctor) { $doctor.connectivity } else { 'not_checked' }
    smtp_connectivity = if ($doctor) { $doctor.smtp_connectivity } else { 'not_checked' }
}
$receiptPath = Join-Path $programBase 'install-receipt.json'
$receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

[ordered]@{
    status = if ($SkipSetup -and -not $alreadyHealthy) { 'installed_setup_pending' } else { 'installed_and_verified' }
    plugin = 'imap-plugin@imap-plugin-handoff'
    version = [string]$release.version
    distribution = $distribution
    receipt = $receiptPath
    reused_existing_connector = $alreadyHealthy
    mailbox_actions_ready = if ($doctor) { [bool]$doctor.mailbox_actions_ready } else { $false }
    send_ready = if ($doctor) { [bool]$doctor.send_ready } else { $false }
    next_step = 'Start a new Codex task, then call setup_status and mail_health.'
} | ConvertTo-Json -Depth 4

# Native Windows bootstrap. No system Python or execution-policy changes.
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')][string]$Repository,
    [string]$Codex,
    [switch]$PrepareOnly,
    [switch]$SkipSetup
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Use install_from_release.sh on macOS.' }
$architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
if ($architecture -ne 'AMD64') { throw 'This release supports Windows x64. ARM64 needs its own verified package.' }
if (-not $PrepareOnly -and -not $Codex) {
    $candidates = @()
    $command = Get-Command codex.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    # Installed app packages expose their own installation root; no process guessing.
    foreach ($app in @(Get-AppxPackage -Name '*Codex*' -ErrorAction SilentlyContinue)) {
        foreach ($relative in @('app\resources\codex.exe', 'resources\codex.exe')) {
            $candidate = Join-Path $app.InstallLocation $relative
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidates += $candidate }
        }
    }
    $candidates = @($candidates | Select-Object -Unique)
    if ($candidates.Count -ne 1) { throw 'Codex must pass its exact native executable with -Codex; discovery was missing or ambiguous.' }
    $Codex = $candidates[0]
}
if (-not $PrepareOnly) {
    if (-not (Test-Path -LiteralPath $Codex -PathType Leaf) -or [IO.Path]::GetExtension($Codex) -ne '.exe') { throw 'Native Codex executable missing.' }
}
$work = Join-Path ([IO.Path]::GetTempPath()) ('nexin-mail-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
Write-Output "Preserving download and diagnostics in $work"
$asset = 'Nexin-Mail-0.2.0-windows-x64.zip'
$base = "https://github.com/$Repository/releases/download/v0.2.0-beta.3"
Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS-windows-x64.txt" -OutFile (Join-Path $work 'checksums.txt')
$rows = @(Get-Content -LiteralPath (Join-Path $work 'checksums.txt') | Where-Object { $_ -match ('^[a-f0-9]{64}  ' + [regex]::Escape($asset) + '$') })
if ($rows.Count -ne 1) { throw 'Invalid release checksum.' }
$expected = $rows[0].Substring(0, 64)
$archive = Join-Path $work $asset
Invoke-WebRequest -UseBasicParsing -Uri "$base/$asset" -OutFile $archive
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Release checksum mismatch; nothing installed.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    $seen = @{}
    foreach ($entry in $zip.Entries) {
        $name = $entry.FullName
        $mode = ($entry.ExternalAttributes -shr 16) -band 0xF000
        if (-not $name -or $name -match '(^/|\\|:|(^|/)\.{1,2}(/|$)|/$|//)' -or $mode -notin @(0, 0x8000)) { throw 'Unsafe release archive entry.' }
        if ($seen.ContainsKey($name)) { throw 'Duplicate release archive path.' }
        $seen[$name] = $true
    }
    if (-not $seen.ContainsKey('package-manifest.json')) { throw 'Release package manifest missing.' }
} finally { $zip.Dispose() }
$package = Join-Path $work 'package'
[IO.Compression.ZipFile]::ExtractToDirectory($archive, $package)
$runtime = Join-Path $package 'payload\runtime\python\python.exe'
$previousPythonPath = $env:PYTHONPATH
$previousBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONPATH = Join-Path $package 'payload\src'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $runtime -B -X utf8 -c 'import sys; from pathlib import Path; from nexin_mail.package import verify; verify(Path(sys.argv[1]))' $package
    if ($LASTEXITCODE -ne 0) { throw 'Package manifest verification failed.' }
    if ($PrepareOnly) { Write-Output "Verified package prepared: $package"; return }
    $setupOption = if ($SkipSetup) { "--skip-setup" } else { "--setup" }
    & $runtime -B -X utf8 -m nexin_mail.install install --package $package --codex $Codex $setupOption
    if ($LASTEXITCODE -ne 0) { throw 'Installation did not pass; preserve the structured diagnostics above.' }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $previousBytecode
}

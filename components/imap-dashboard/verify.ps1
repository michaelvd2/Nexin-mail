[CmdletBinding()]
param(
    [string]$ProgramRoot
)

$ErrorActionPreference = 'Stop'
$packageRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$manifestPath = Join-Path $packageRoot 'package-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'package-manifest.json is missing.' }

function Resolve-ContainedFile([string]$Base, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or [IO.Path]::IsPathRooted($Relative)) { throw "Invalid package path: $Relative" }
    $baseFull = [IO.Path]::GetFullPath($Base).TrimEnd('\') + '\'
    $candidate = [IO.Path]::GetFullPath((Join-Path $Base ($Relative.Replace('/', '\'))))
    if (-not $candidate.StartsWith($baseFull, [StringComparison]::OrdinalIgnoreCase)) { throw "Package path escaped the root: $Relative" }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Package file is missing: $Relative" }
    if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Package file is redirected: $Relative" }
    return $candidate
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or $manifest.product -ne 'imap-dashboard-handoff' -or [Version][string]$manifest.version -ne [Version]'0.1.2') {
    throw 'The Dashboard package identity or version is invalid.'
}
$expected = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$verified = 0
foreach ($entry in @($manifest.files)) {
    $relative = [string]$entry.path
    if (-not $expected.Add($relative)) { throw "Duplicate package path: $relative" }
    $target = Resolve-ContainedFile $packageRoot $relative
    if ([int64](Get-Item -LiteralPath $target).Length -ne [int64]$entry.bytes) { throw "Package size mismatch: $relative" }
    $actualHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualHash -ne ([string]$entry.sha256).ToUpperInvariant()) { throw "Package hash mismatch: $relative" }
    $verified++
}
$actual = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
Get-ChildItem -LiteralPath $packageRoot -File -Recurse -Force | Where-Object { $_.FullName -ne $manifestPath } | ForEach-Object {
    [void]$actual.Add($_.FullName.Substring($packageRoot.Length + 1).Replace('\', '/'))
}
if (-not $actual.SetEquals($expected)) { throw 'The Dashboard package contains an unlisted or missing file.' }

$pluginRoot = Join-Path $packageRoot 'plugins\imap-dashboard'
if (-not (Test-Path -LiteralPath (Join-Path $pluginRoot '.codex-plugin\plugin.json') -PathType Leaf)) { $pluginRoot = $packageRoot }
$plugin = Get-Content -LiteralPath (Join-Path $pluginRoot '.codex-plugin\plugin.json') -Raw | ConvertFrom-Json
if ($plugin.name -ne 'imap-dashboard' -or [Version][string]$plugin.version -ne [Version][string]$manifest.version) { throw 'The Dashboard plugin identity does not match the package.' }

if ([string]::IsNullOrWhiteSpace($ProgramRoot)) {
    $localAppData = [Environment]::GetFolderPath('LocalApplicationData')
    if ([string]::IsNullOrWhiteSpace($localAppData)) { throw 'Windows Local AppData is unavailable.' }
    $ProgramRoot = Join-Path $localAppData 'IMAP Plugin'
}
$backendOutput = (& (Join-Path $packageRoot 'scripts\verify_backend.ps1') -ProgramRoot $ProgramRoot 2>&1 | Out-String)
$backend = $backendOutput | ConvertFrom-Json
if ($backend.status -ne 'pass' -or $backend.backend_code_executed) { throw 'The installed IMAP Plugin integrity result is invalid.' }

[ordered]@{
    status = 'pass'
    product = $manifest.product
    version = [string]$manifest.version
    files_verified = $verified
    contains_runtime = $false
    contains_credentials = $false
    imap_plugin_version = [string]$backend.version
    imap_plugin_files_verified = [int]$backend.files_verified
    backend_code_executed_during_verification = $false
} | ConvertTo-Json

[CmdletBinding()]
param(
    [string]$Root,
    [switch]$RunDoctor
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Root)) { $Root = $PSScriptRoot }

function Resolve-ContainedFile([string]$Base, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or [IO.Path]::IsPathRooted($Relative)) {
        throw "Invalid manifest path: $Relative"
    }
    $baseFull = [IO.Path]::GetFullPath($Base).TrimEnd('\') + '\'
    $candidate = [IO.Path]::GetFullPath((Join-Path $Base ($Relative.Replace('/', '\'))))
    if (-not $candidate.StartsWith($baseFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Manifest path escapes the packet: $Relative"
    }
    return $candidate
}

$packetRoot = (Resolve-Path -LiteralPath $Root).Path
$manifestPath = Join-Path $packetRoot 'package-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'package-manifest.json is missing.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or $manifest.product -ne 'imap-plugin-windows-handoff') {
    throw 'The package manifest identity is invalid.'
}

$verified = 0
$manifestPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($entry in @($manifest.files)) {
    if (-not $manifestPaths.Add([string]$entry.path)) { throw "Duplicate manifest path: $($entry.path)" }
    $target = Resolve-ContainedFile $packetRoot ([string]$entry.path)
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "Package file is missing: $($entry.path)" }
    $item = Get-Item -LiteralPath $target
    if ([int64]$item.Length -ne [int64]$entry.bytes) { throw "Package size mismatch: $($entry.path)" }
    $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -ne ([string]$entry.sha256).ToUpperInvariant()) { throw "Package hash mismatch: $($entry.path)" }
    $verified++
}
$actualPaths = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
Get-ChildItem -LiteralPath $packetRoot -File -Recurse -Force | Where-Object { $_.FullName -ne $manifestPath } | ForEach-Object {
    [void]$actualPaths.Add($_.FullName.Substring($packetRoot.Length + 1).Replace('\', '/'))
}
if (-not $actualPaths.SetEquals($manifestPaths)) { throw 'The packet contains an unlisted or missing file.' }

$pluginRoot = Join-Path $packetRoot 'plugins\imap-plugin'
$pluginManifestPath = Join-Path $pluginRoot '.codex-plugin\plugin.json'
$marketplacePath = Join-Path $packetRoot '.agents\plugins\marketplace.json'
if (-not (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf)) { throw 'Plugin manifest is missing.' }
if (-not (Test-Path -LiteralPath $marketplacePath -PathType Leaf)) { throw 'Marketplace manifest is missing.' }
$pluginManifest = Get-Content -LiteralPath $pluginManifestPath -Raw | ConvertFrom-Json
$marketplace = Get-Content -LiteralPath $marketplacePath -Raw | ConvertFrom-Json
if ($pluginManifest.name -ne 'imap-plugin' -or $pluginManifest.version -ne [string]$manifest.version) {
    throw 'Plugin identity or version does not match the release manifest.'
}
if ($marketplace.name -ne 'imap-plugin-handoff' -or @($marketplace.plugins).Count -ne 1 -or $marketplace.plugins[0].name -ne 'imap-plugin') {
    throw 'Marketplace scope is not exactly the IMAP Plugin.'
}

$python = Join-Path $pluginRoot 'runtime\python\python.exe'
$runtimeCheck = Join-Path $pluginRoot 'scripts\verify_runtime.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Pinned runtime is missing.' }
$oldPythonPath = $env:PYTHONPATH
$oldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONPATH = Join-Path $pluginRoot 'src'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $runtimeOutput = (& $python $runtimeCheck 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Pinned runtime verification failed: $runtimeOutput" }
    $runtime = $runtimeOutput | ConvertFrom-Json
    if ($runtime.status -ne 'pass' -or @($runtime.forbidden_exposed).Count -ne 0) { throw 'MCP tool-surface verification failed.' }
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode
}

$doctor = $null
if ($RunDoctor) {
    $doctorOutput = (& (Join-Path $pluginRoot 'scripts\doctor.cmd') 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Read-only mailbox doctor failed: $doctorOutput" }
    $doctor = $doctorOutput | ConvertFrom-Json
    if ($doctor.connectivity -ne 'pass' -or $doctor.credentials.imap.persist -ne 2) {
        throw 'Read-only mailbox acceptance gates did not pass.'
    }
}

[ordered]@{
    status = 'pass'
    product = $manifest.product
    version = $manifest.version
    files_verified = $verified
    runtime_python = $runtime.python
    tools = @($runtime.tools)
    doctor = $doctor
} | ConvertTo-Json -Depth 8

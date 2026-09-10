[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProgramRoot
)

$ErrorActionPreference = 'Stop'
$programRootFull = [IO.Path]::GetFullPath($ProgramRoot).TrimEnd('\')
$distribution = Join-Path $programRootFull 'distribution'
$backend = Join-Path $distribution 'plugins\imap-plugin'
$manifestPath = Join-Path $distribution 'package-manifest.json'
if (-not (Test-Path -LiteralPath $backend -PathType Container)) { throw 'The installed IMAP Plugin directory is missing.' }
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'The installed IMAP Plugin integrity manifest is missing.' }
if ((Get-Item -LiteralPath $backend -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'The installed IMAP Plugin directory is redirected.' }

function Resolve-ContainedFile([string]$Base, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or [IO.Path]::IsPathRooted($Relative)) { throw "Invalid backend manifest path: $Relative" }
    $baseFull = [IO.Path]::GetFullPath($Base).TrimEnd('\') + '\'
    $candidate = [IO.Path]::GetFullPath((Join-Path $Base ($Relative.Replace('/', '\'))))
    if (-not $candidate.StartsWith($baseFull, [StringComparison]::OrdinalIgnoreCase)) { throw "Backend manifest path escaped the distribution: $Relative" }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Backend file is missing: $Relative" }
    if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Backend file is redirected: $Relative" }
    return $candidate
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or $manifest.product -ne 'imap-plugin-windows-handoff') { throw 'The installed IMAP Plugin integrity identity is invalid.' }
try { $version = [Version][string]$manifest.version } catch { throw 'The installed IMAP Plugin version is invalid.' }
if ($version -lt [Version]'0.1.3') { throw 'Update IMAP Plugin to version 0.1.3 or newer.' }

$prefix = 'plugins/imap-plugin/'
$expected = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$verified = 0
foreach ($entry in @($manifest.files)) {
    $relative = [string]$entry.path
    if (-not $relative.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { continue }
    if (-not $expected.Add($relative)) { throw "Duplicate backend manifest path: $relative" }
    $target = Resolve-ContainedFile $distribution $relative
    if ([int64](Get-Item -LiteralPath $target).Length -ne [int64]$entry.bytes) { throw "Backend size mismatch: $relative" }
    $actualHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualHash -ne ([string]$entry.sha256).ToUpperInvariant()) { throw "Backend hash mismatch: $relative" }
    $verified++
}
if ($verified -eq 0) { throw 'The integrity manifest contains no IMAP Plugin files.' }

$actual = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
Get-ChildItem -LiteralPath $backend -File -Recurse -Force | ForEach-Object {
    [void]$actual.Add($_.FullName.Substring($distribution.Length + 1).Replace('\', '/'))
}
if (-not $actual.SetEquals($expected)) { throw 'The installed IMAP Plugin file set differs from its integrity manifest.' }

$pluginManifest = Get-Content -LiteralPath (Join-Path $backend '.codex-plugin\plugin.json') -Raw | ConvertFrom-Json
if ($pluginManifest.name -ne 'imap-plugin' -or [Version][string]$pluginManifest.version -ne $version) { throw 'The installed IMAP Plugin name or version does not match its integrity manifest.' }

[ordered]@{
    status = 'pass'
    product = $manifest.product
    version = $version.ToString()
    files_verified = $verified
    backend_code_executed = $false
} | ConvertTo-Json

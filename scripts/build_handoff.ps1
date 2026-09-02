[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$pluginRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$handoffSource = Join-Path $pluginRoot 'handoff'
$dist = Join-Path $pluginRoot 'dist'
$version = [string](Get-Content -LiteralPath (Join-Path $pluginRoot '.codex-plugin\plugin.json') -Raw | ConvertFrom-Json).version
$stage = Join-Path $dist 'imap-plugin-windows-x64'
$zip = Join-Path $dist 'imap-plugin-windows-x64.zip'
$checksums = Join-Path $dist 'SHA256SUMS.txt'

[IO.Directory]::CreateDirectory($dist) | Out-Null
$distFull = [IO.Path]::GetFullPath($dist).TrimEnd('\') + '\'
foreach ($target in @($stage, $zip, $checksums)) {
    $targetFull = [IO.Path]::GetFullPath($target)
    if (-not $targetFull.StartsWith($distFull, [StringComparison]::OrdinalIgnoreCase)) { throw 'Build output escaped dist.' }
    if (Test-Path -LiteralPath $targetFull) { Remove-Item -LiteralPath $targetFull -Recurse -Force }
}

[IO.Directory]::CreateDirectory($stage) | Out-Null
foreach ($name in @('SKILL.md', 'HANDOFF.md', 'install.ps1', 'verify.ps1', 'uninstall.ps1')) {
    Copy-Item -LiteralPath (Join-Path $handoffSource $name) -Destination (Join-Path $stage $name)
}
foreach ($name in @('AGENTS.md', 'CODEX_INSTALL.md')) {
    Copy-Item -LiteralPath (Join-Path $pluginRoot $name) -Destination (Join-Path $stage $name)
}
$marketplaceDirectory = Join-Path $stage '.agents\plugins'
[IO.Directory]::CreateDirectory($marketplaceDirectory) | Out-Null
Copy-Item -LiteralPath (Join-Path $handoffSource 'marketplace.json') -Destination (Join-Path $marketplaceDirectory 'marketplace.json')

$payload = Join-Path $stage 'plugins\imap-plugin'
[IO.Directory]::CreateDirectory($payload) | Out-Null
foreach ($name in @('.codex-plugin', 'skills', 'src')) {
    Copy-Item -LiteralPath (Join-Path $pluginRoot $name) -Destination (Join-Path $payload $name) -Recurse
}
foreach ($name in @('.mcp.json', 'AGENTS.md', 'CHANGELOG.md', 'CODEX_INSTALL.md', 'LICENSE', 'PRIVACY.md', 'README.md', 'pyproject.toml', 'requirements-runtime.lock')) {
    Copy-Item -LiteralPath (Join-Path $pluginRoot $name) -Destination (Join-Path $payload $name)
}
Copy-Item -LiteralPath (Join-Path $pluginRoot 'docs') -Destination (Join-Path $payload 'docs') -Recurse
[IO.Directory]::CreateDirectory((Join-Path $payload 'runtime')) | Out-Null
Copy-Item -LiteralPath (Join-Path $pluginRoot 'runtime\python') -Destination (Join-Path $payload 'runtime\python') -Recurse
[IO.Directory]::CreateDirectory((Join-Path $payload 'scripts')) | Out-Null
foreach ($name in @('autoconfigure.py', 'configure.py', 'doctor.cmd', 'doctor.ps1', 'enroll_gui.ps1', 'launch.cmd', 'review.ps1', 'setup.cmd', 'verify_runtime.py')) {
    Copy-Item -LiteralPath (Join-Path $pluginRoot "scripts\$name") -Destination (Join-Path $payload "scripts\$name")
}
Get-ChildItem -LiteralPath $payload -Directory -Recurse -Force | Where-Object { $_.Name -eq '__pycache__' } | Sort-Object FullName -Descending | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force
}
Get-ChildItem -LiteralPath $payload -File -Recurse -Force -Filter '*.pyc' | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Force
}

$runtimeReceipt = Get-Content -LiteralPath (Join-Path $pluginRoot 'receipts\runtime.json') -Raw | ConvertFrom-Json
$release = [ordered]@{
    product = 'imap-plugin-windows-handoff'
    version = $version
    platform = 'windows-x86_64'
    python = [string]$runtimeReceipt.python_version
    python_source = [string]$runtimeReceipt.python_source
    python_source_sha256 = [string]$runtimeReceipt.python_archive_sha256
    dependency_lock_sha256 = [string]$runtimeReceipt.dependencies_lock_sha256
    marketplace = 'imap-plugin-handoff'
}
$release | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stage 'release.json') -Encoding UTF8

$entries = @()
Get-ChildItem -LiteralPath $stage -File -Recurse -Force | Where-Object { $_.Name -ne 'package-manifest.json' } | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($stage.Length + 1).Replace('\', '/')
    $entries += [ordered]@{
        path = $relative
        bytes = [int64]$_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
    }
}
$packageManifest = [ordered]@{
    schema = 1
    product = 'imap-plugin-windows-handoff'
    version = $version
    files = $entries
}
$packageManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stage 'package-manifest.json') -Encoding UTF8

Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToUpperInvariant()
[IO.File]::WriteAllText($checksums, "$zipHash  imap-plugin-windows-x64.zip`n", (New-Object Text.UTF8Encoding($false)))
[ordered]@{
    zip = $zip
    sha256 = $zipHash
    bytes = (Get-Item -LiteralPath $zip).Length
    package_files = $entries.Count
    checksums = $checksums
} | ConvertTo-Json -Depth 3

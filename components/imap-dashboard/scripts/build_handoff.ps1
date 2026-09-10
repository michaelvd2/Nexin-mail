[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist 'imap-dashboard'
$zip = Join-Path $dist 'imap-dashboard.zip'
$checksums = Join-Path $dist 'SHA256SUMS.txt'
$distPrefix = [IO.Path]::GetFullPath($dist).TrimEnd('\') + '\'
[IO.Directory]::CreateDirectory($dist) | Out-Null
foreach ($target in @($stage, $zip, $checksums)) {
    $full = [IO.Path]::GetFullPath($target)
    if (-not $full.StartsWith($distPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Build target escaped dist.' }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}
[IO.Directory]::CreateDirectory($stage) | Out-Null
$payload = Join-Path $stage 'plugins\imap-dashboard'
[IO.Directory]::CreateDirectory($payload) | Out-Null
foreach ($name in @('.codex-plugin', 'docs', 'skills', 'src')) {
    Copy-Item -LiteralPath (Join-Path $root $name) -Destination (Join-Path $payload $name) -Recurse
}
foreach ($name in @('.mcp.json', 'AGENTS.md', 'CHANGELOG.md', 'CODEX_INSTALL.md', 'LICENSE', 'PRIVACY.md', 'README.md', 'pyproject.toml')) {
    Copy-Item -LiteralPath (Join-Path $root $name) -Destination (Join-Path $payload $name)
}
[IO.Directory]::CreateDirectory((Join-Path $payload 'scripts')) | Out-Null
foreach ($name in @('install_dashboard.py', 'install_macos.sh', 'launch.cmd', 'launch_macos.sh', 'privacy_scan.py', 'validate_structure.py', 'verify_backend.py', 'verify_package.py')) {
    Copy-Item -LiteralPath (Join-Path $root "scripts\$name") -Destination (Join-Path $payload "scripts\$name")
}
foreach ($name in @('AGENTS.md', 'CHANGELOG.md', 'CODEX_INSTALL.md', 'README.md', 'install.ps1', 'verify.ps1')) {
    Copy-Item -LiteralPath (Join-Path $root $name) -Destination (Join-Path $stage $name)
}
[IO.Directory]::CreateDirectory((Join-Path $stage 'scripts')) | Out-Null
foreach ($name in @('verify_backend.ps1', 'verify_package.py')) {
    Copy-Item -LiteralPath (Join-Path $root "scripts\$name") -Destination (Join-Path $stage "scripts\$name")
}
[IO.Directory]::CreateDirectory((Join-Path $stage '.agents\plugins')) | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'handoff\marketplace.json') -Destination (Join-Path $stage '.agents\plugins\marketplace.json')
Copy-Item -LiteralPath (Join-Path $root 'skills\imap-dashboard\SKILL.md') -Destination (Join-Path $stage 'SKILL.md')
[ordered]@{ product='imap-dashboard-handoff'; version='0.1.2'; uses_existing_connection='imap-plugin'; contains_runtime=$false } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage 'release.json') -Encoding UTF8

Get-ChildItem -LiteralPath $stage -Directory -Recurse -Force | Where-Object { $_.Name -eq '__pycache__' } | Sort-Object FullName -Descending | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force
}
Get-ChildItem -LiteralPath $stage -File -Recurse -Force -Filter '*.pyc' | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Force
}
$scanPython = (Get-Command python.exe -ErrorAction Stop).Source
$previousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONDONTWRITEBYTECODE = '1'
    & $scanPython (Join-Path $root 'scripts\privacy_scan.py') $stage
    if ($LASTEXITCODE -ne 0) { throw 'Staged package privacy check failed.' }
    & $scanPython (Join-Path $root 'scripts\package_owner_path_scan.py') $stage
    if ($LASTEXITCODE -ne 0) { throw 'Staged package contains a build-machine user-profile path.' }
} finally {
    if ($null -eq $previousNoBytecode) {
        Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONDONTWRITEBYTECODE = $previousNoBytecode
    }
}

$entries = @()
Get-ChildItem -LiteralPath $stage -File -Recurse -Force | Where-Object { $_.Name -ne 'package-manifest.json' } | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($stage.Length + 1).Replace('\', '/')
    $entries += [ordered]@{ path=$relative; bytes=[int64]$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToUpperInvariant() }
}
[ordered]@{ schema=1; product='imap-dashboard-handoff'; version='0.1.2'; files=$entries } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stage 'package-manifest.json') -Encoding UTF8
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToUpperInvariant()
[IO.File]::WriteAllText($checksums, "$hash  imap-dashboard.zip`n", [Text.UTF8Encoding]::new($false))
[ordered]@{ zip=$zip; sha256=$hash; bytes=(Get-Item -LiteralPath $zip).Length; package_files=$entries.Count } | ConvertTo-Json

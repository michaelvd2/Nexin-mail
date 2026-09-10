param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $pluginRoot 'runtime'
$archiveName = 'cpython-3.12.14+20260901-x86_64-pc-windows-msvc-install_only.tar.gz'
$archive = Join-Path $runtimeRoot $archiveName
$pythonRoot = Join-Path $runtimeRoot 'python'
$expectedArchiveSha256 = 'E90C1B6419DA3BD812DD73BB3DE40287A21ABF153438147639EC5E20375EA93F'
$archiveUrl = 'https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14%2B20260901-x86_64-pc-windows-msvc-install_only.tar.gz'
$archiveChecksumUrl = 'https://github.com/astral-sh/python-build-standalone/releases/download/20260901/SHA256SUMS'
$pythonVersion = '3.12.14'
$wheelhouse = Join-Path $runtimeRoot 'wheelhouse'
$requirements = Join-Path $pluginRoot 'requirements-runtime.lock'
[IO.Directory]::CreateDirectory($runtimeRoot) | Out-Null

function Assert-PlainPath([string]$PathValue, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) { throw "$Label path is empty." }
    $resolvedPath = [IO.Path]::GetFullPath($PathValue)
    $item = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.LinkType -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint))) {
        throw "$Label may not be a link or reparse point: $resolvedPath"
    }
}

function Assert-PlainTree([string]$PathValue, [string]$Label) {
    Assert-PlainPath $PathValue $Label
    foreach ($item in Get-ChildItem -LiteralPath $PathValue -Recurse -Force -ErrorAction Stop) {
        if ($item.LinkType -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "$Label contains a link or reparse point: $($item.FullName)"
        }
    }
}

Assert-PlainPath $runtimeRoot 'Runtime root'
Assert-PlainPath $archive 'Python archive'

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    $partialArchive = Join-Path $runtimeRoot ('.python-download-' + $PID + '.tmp')
    if (Test-Path -LiteralPath $partialArchive) { Remove-Item -LiteralPath $partialArchive -Force }
    Invoke-WebRequest -Uri $archiveUrl -OutFile $partialArchive
    $partialHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $partialArchive).Hash
    if ($partialHash -ne $expectedArchiveSha256) {
        Remove-Item -LiteralPath $partialArchive -Force
        throw "Embedded Python archive hash mismatch: $partialHash"
    }
    Move-Item -LiteralPath $partialArchive -Destination $archive
}
$actualArchiveSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
if ($actualArchiveSha256 -ne $expectedArchiveSha256) {
    throw "Embedded Python archive hash mismatch: $actualArchiveSha256"
}

if (Test-Path -LiteralPath $pythonRoot) {
    Assert-PlainPath $pythonRoot 'Portable runtime'
    $resolved = (Resolve-Path -LiteralPath $pythonRoot).Path
    $expected = [IO.Path]::GetFullPath((Join-Path $pluginRoot 'runtime\python'))
    if ($resolved -ne $expected) { throw "Unexpected runtime target: $resolved" }
    if (-not $Force) { throw 'Portable runtime already exists. Use -Force only for an intentional rebuild.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

if (-not (Get-Command tar.exe -ErrorAction SilentlyContinue)) {
    throw 'Windows tar.exe is required to unpack the pinned standalone runtime.'
}
$extractRoot = Join-Path $runtimeRoot ('.python-extract-' + $PID)
if (Test-Path -LiteralPath $extractRoot) {
    throw "Refusing to reuse an existing runtime extraction path: $extractRoot"
}
New-Item -ItemType Directory -Path $extractRoot | Out-Null
$entries = & tar.exe -tzf $archive
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the pinned standalone runtime archive.' }
foreach ($entry in $entries) {
    $name = ([string]$entry).Trim()
    if ([string]::IsNullOrWhiteSpace($name) -or $name.StartsWith('/') -or $name.Contains('\') -or $name -match '(^|/)\.\.(/|$)') {
        throw "Unsafe standalone runtime archive path: $name"
    }
}
& tar.exe -xzf $archive -C $extractRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not unpack the pinned standalone runtime archive.' }
$extractedPython = Join-Path $extractRoot 'python'
if (-not (Test-Path -LiteralPath $extractedPython -PathType Container)) {
    throw 'Standalone runtime archive has no expected python root.'
}
Assert-PlainTree $extractRoot 'Standalone runtime extraction'
New-Item -ItemType Directory -Path $pythonRoot | Out-Null
Get-ChildItem -LiteralPath $extractedPython -Force | Move-Item -Destination $pythonRoot
Remove-Item -LiteralPath $extractRoot -Recurse -Force
$sitePackages = Join-Path $pythonRoot 'Lib\site-packages'
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

$buildPython = Join-Path $pythonRoot 'python.exe'
if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) { throw 'Standalone runtime executable is missing.' }
if (-not (Test-Path -LiteralPath $wheelhouse -PathType Container) -or -not (Get-ChildItem -LiteralPath $wheelhouse -File -Filter '*.whl' -ErrorAction SilentlyContinue)) {
    [IO.Directory]::CreateDirectory($wheelhouse) | Out-Null
    & $buildPython -m pip download --disable-pip-version-check --only-binary=:all: --require-hashes --requirement $requirements --dest $wheelhouse
    if ($LASTEXITCODE -ne 0) { throw 'Could not download the pinned Windows runtime dependencies.' }
}
$wheelEntries = Get-ChildItem -LiteralPath $wheelhouse -Recurse -Force -ErrorAction Stop
if ($wheelEntries | Where-Object { $_.LinkType -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }) {
    throw 'Wheelhouse contains a link or reparse point.'
}
& $buildPython -m pip install --disable-pip-version-check --no-compile --no-index --no-deps --find-links $wheelhouse --require-hashes --requirement $requirements --target $sitePackages
if ($LASTEXITCODE -ne 0) { throw 'Pinned runtime dependency installation failed.' }

# Console launchers generated by pip embed the build machine's absolute Python path.
# The plugin starts modules through python.exe and does not use these launchers.
$generatedLaunchers = Join-Path $sitePackages 'bin'
if (Test-Path -LiteralPath $generatedLaunchers -PathType Container) {
    $resolvedLaunchers = (Resolve-Path -LiteralPath $generatedLaunchers).Path
    $sitePackagesRoot = [IO.Path]::GetFullPath($sitePackages).TrimEnd('\') + '\'
    if (-not $resolvedLaunchers.StartsWith($sitePackagesRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Generated launcher path escaped site-packages: $resolvedLaunchers"
    }
    Remove-Item -LiteralPath $resolvedLaunchers -Recurse -Force
}
$generatedWindowsLaunchers = Join-Path $sitePackages 'Scripts'
if (Test-Path -LiteralPath $generatedWindowsLaunchers -PathType Container) {
    Remove-Item -LiteralPath $generatedWindowsLaunchers -Recurse -Force
}
Assert-PlainTree $pythonRoot 'Portable runtime'

$portablePython = Join-Path $pythonRoot 'python.exe'
$portableItem = Get-Item -LiteralPath $portablePython -Force -ErrorAction Stop
if ($portableItem.LinkType -or ($portableItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Portable runtime executable is a link or reparse point.'
}
$identity = (& $portablePython -c 'import platform,sys; print(sys.version.split()[0]); print(platform.machine())')
if ($LASTEXITCODE -ne 0 -or $identity.Count -lt 2) { throw 'Portable Python identity verification failed.' }
$version = ([string]$identity[0]).Trim()
$machine = ([string]$identity[1]).Trim()
if ($version -ne $pythonVersion -or $machine -notin @('AMD64', 'x86_64')) { throw "Portable Python verification failed: $version / $machine" }

$receipt = [ordered]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString('o')
    python_version = $version
    python_source = $archiveUrl
    python_archive_sha256 = $actualArchiveSha256
    python_checksum_source = $archiveChecksumUrl
    runtime_provider = 'astral-sh/python-build-standalone'
    architecture = 'windows-amd64'
    dependencies_lock_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
    wheels = @(Get-ChildItem -LiteralPath $wheelhouse -File -Filter '*.whl' | Sort-Object Name | ForEach-Object {
        [ordered]@{ name = $_.Name; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash }
    })
}
[IO.Directory]::CreateDirectory((Join-Path $pluginRoot 'receipts')) | Out-Null
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $pluginRoot 'receipts\runtime.json') -Encoding utf8
Write-Output "Portable runtime ready: $portablePython"

param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $pluginRoot 'runtime'
$archive = Join-Path $runtimeRoot 'python-3.12.10-embeddable-amd64.zip'
$pythonRoot = Join-Path $runtimeRoot 'python'
$expectedArchiveSha256 = '156C7EEA90D58CD7E91A23F28A0056616B13E9F4CF4901B7B99B837B7848C6DA'
$archiveUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embeddable-amd64.zip'
$wheelhouse = Join-Path $runtimeRoot 'wheelhouse'
$requirements = Join-Path $pluginRoot 'requirements-runtime.lock'

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archive
}
$actualArchiveSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
if ($actualArchiveSha256 -ne $expectedArchiveSha256) {
    throw "Embedded Python archive hash mismatch: $actualArchiveSha256"
}

if (Test-Path -LiteralPath $pythonRoot) {
    $resolved = (Resolve-Path -LiteralPath $pythonRoot).Path
    $expected = [IO.Path]::GetFullPath((Join-Path $pluginRoot 'runtime\python'))
    if ($resolved -ne $expected) { throw "Unexpected runtime target: $resolved" }
    if (-not $Force) { throw 'Portable runtime already exists. Use -Force only for an intentional rebuild.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

New-Item -ItemType Directory -Path $pythonRoot | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $pythonRoot
$sitePackages = Join-Path $pythonRoot 'Lib\site-packages'
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null

$pthPath = Join-Path $pythonRoot 'python312._pth'
$pth = @(
    'python312.zip'
    '.'
    'Lib\site-packages'
    '..\..\src'
    'import site'
) -join "`r`n"
[IO.File]::WriteAllText($pthPath, $pth + "`r`n", (New-Object Text.UTF8Encoding($false)))

$buildPython = Join-Path $pluginRoot 'runtime\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) {
    $buildPython = (Get-Command python.exe -ErrorAction Stop).Source
}
if (-not (Test-Path -LiteralPath $wheelhouse -PathType Container) -or -not (Get-ChildItem -LiteralPath $wheelhouse -File -Filter '*.whl' -ErrorAction SilentlyContinue)) {
    [IO.Directory]::CreateDirectory($wheelhouse) | Out-Null
    & $buildPython -m pip download --disable-pip-version-check --only-binary=:all: --requirement $requirements --dest $wheelhouse
    if ($LASTEXITCODE -ne 0) { throw 'Could not download the pinned Windows runtime dependencies.' }
}
& $buildPython -m pip install --disable-pip-version-check --no-index --no-deps --find-links $wheelhouse --requirement $requirements --target $sitePackages
if ($LASTEXITCODE -ne 0) { throw 'Pinned runtime dependency installation failed.' }

$portablePython = Join-Path $pythonRoot 'python.exe'
$version = (& $portablePython -c 'import sys; print(sys.version.split()[0])').Trim()
if ($LASTEXITCODE -ne 0 -or $version -ne '3.12.10') { throw "Portable Python verification failed: $version" }

$receipt = [ordered]@{
    generated_at = [DateTimeOffset]::UtcNow.ToString('o')
    python_version = $version
    python_source = $archiveUrl
    python_archive_sha256 = $actualArchiveSha256
    architecture = 'windows-amd64'
    dependencies_lock_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
    wheels = @(Get-ChildItem -LiteralPath $wheelhouse -File -Filter '*.whl' | Sort-Object Name | ForEach-Object {
        [ordered]@{ name = $_.Name; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash }
    })
}
[IO.Directory]::CreateDirectory((Join-Path $pluginRoot 'receipts')) | Out-Null
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $pluginRoot 'receipts\runtime.json') -Encoding utf8
Write-Output "Portable runtime ready: $portablePython"

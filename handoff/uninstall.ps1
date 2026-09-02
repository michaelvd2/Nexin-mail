[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$codex = Get-Command codex -ErrorAction Stop
$localAppData = [Environment]::GetFolderPath('LocalApplicationData')
$expectedDistribution = [IO.Path]::GetFullPath((Join-Path $localAppData 'IMAP Plugin\distribution')).TrimEnd('\')

$marketplaces = (& $codex.Source plugin marketplace list --json | Out-String) | ConvertFrom-Json
$marketplace = @($marketplaces.marketplaces | Where-Object { $_.name -eq 'imap-plugin-handoff' }) | Select-Object -First 1
if ($marketplace) {
    $actualRoot = [IO.Path]::GetFullPath([string]$marketplace.root).TrimEnd('\')
    $releasePath = Join-Path $actualRoot 'release.json'
    $pluginPath = Join-Path $actualRoot 'plugins\imap-plugin\.codex-plugin\plugin.json'
    if (-not (Test-Path -LiteralPath $releasePath -PathType Leaf) -or -not (Test-Path -LiteralPath $pluginPath -PathType Leaf)) {
        throw 'The matching marketplace does not contain the expected handoff identity; nothing was removed.'
    }
    $release = Get-Content -LiteralPath $releasePath -Raw | ConvertFrom-Json
    $plugin = Get-Content -LiteralPath $pluginPath -Raw | ConvertFrom-Json
    if ($release.product -ne 'imap-plugin-windows-handoff' -or $plugin.name -ne 'imap-plugin') {
        throw 'The matching marketplace identity is unexpected; nothing was removed.'
    }
    & $codex.Source plugin remove 'imap-plugin@imap-plugin-handoff' --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not deregister the IMAP Plugin.' }
    & $codex.Source plugin marketplace remove 'imap-plugin-handoff' --json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The plugin was removed, but its marketplace registration could not be removed.' }
}

[ordered]@{
    status = 'unregistered'
    program_copy_preserved = $expectedDistribution
    marketplace_copy_preserved = if ($marketplace) { $actualRoot } else { $null }
    mailbox_data_preserved = (Join-Path $localAppData 'imap-plugin')
    credentials_preserved = @('imap-plugin/imap', 'imap-plugin/smtp')
    note = 'No local mailbox data, credential, download, or backup was deleted.'
} | ConvertTo-Json -Depth 4

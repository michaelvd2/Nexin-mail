[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
if (-not [OperatingSystem]::IsWindows()) { throw 'POLICY_PLATFORM_UNSUPPORTED' }
$language = [string]$ExecutionContext.SessionState.LanguageMode
$effective = [string](Get-ExecutionPolicy)
if ($language -in @('ConstrainedLanguage', 'RestrictedLanguage', 'NoLanguage')) {
    [ordered]@{ status = 'blocked'; code = 'language_mode_restricted'; bypass = $false } | ConvertTo-Json -Compress
    exit 20
}
[ordered]@{
    status = 'ready_to_run'
    language = $language
    effective_policy = $effective
    bypass = $false
    policy_mutated = $false
} | ConvertTo-Json -Compress

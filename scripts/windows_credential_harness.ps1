[CmdletBinding()]
param(
    [string]$Runtime = ''
)

$ErrorActionPreference = 'Stop'
if (-not [OperatingSystem]::IsWindows()) { throw 'CREDENTIAL_PLATFORM_UNSUPPORTED' }
if ([string]::IsNullOrWhiteSpace($Runtime)) { $Runtime = Join-Path $PSScriptRoot '..\runtime\python\python.exe' }
if (-not (Test-Path -LiteralPath $Runtime -PathType Leaf)) { throw 'CREDENTIAL_RUNTIME_MISSING' }

# The actual CredWrite/CredRead round trip must run in an isolated native test
# profile with a synthetic target.  This readiness check never receives a
# password, never exports a credential blob, and does not alter the store.
[ordered]@{
    status = 'ready_to_run'
    store = 'Windows Credential Manager'
    target = 'synthetic-only'
    persistence = 'native_round_trip_required'
    secret = 'not_supplied'
    cleanup = 'required_after_native_run'
} | ConvertTo-Json -Compress

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SetupExe,
    [Parameter(Mandatory = $true)]
    [string]$CertificateThumbprint,
    [string]$TimestampServer
)

$ErrorActionPreference = 'Stop'
if (-not [OperatingSystem]::IsWindows()) { throw 'SIGNING_PLATFORM_UNSUPPORTED' }
if ([string]::IsNullOrWhiteSpace($CertificateThumbprint)) { throw 'SIGNING_NOT_CONFIGURED' }
$path = [IO.Path]::GetFullPath($SetupExe)
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'SIGNING_ARTIFACT_MISSING' }

# The certificate and timestamp service are intentionally caller supplied.
# This hook never purchases a certificate, uploads an artifact, or modifies
# MotW/SmartScreen metadata.  Set-AuthenticodeSignature is only reached after
# an operator has explicitly selected an existing local certificate.
$certificate = Get-ChildItem -LiteralPath ("Cert:\CurrentUser\My\" + $CertificateThumbprint) -ErrorAction SilentlyContinue
if (-not $certificate) { throw 'SIGNING_CERTIFICATE_NOT_FOUND' }
$params = @{ FilePath = $path; Certificate = $certificate }
if (-not [string]::IsNullOrWhiteSpace($TimestampServer)) { $params['TimestampServer'] = $TimestampServer }
$result = Set-AuthenticodeSignature @params
if ($result.Status -ne 'Valid') { throw ('SIGNING_FAILED_' + [string]$result.Status) }
[ordered]@{
    artifact = $path
    status = 'signed_locally'
    publisher_authenticity = 'certificate_attested'
    enterprise_policy = 'not_checked'
    upload = 'not_performed'
} | ConvertTo-Json -Depth 3

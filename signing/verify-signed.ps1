param(
    [Parameter(Mandatory=$true)][string]$Executable,
    [Parameter(Mandatory=$true)][string]$UnsignedExecutable,
    [Parameter(Mandatory=$true)][string]$ExpectedSignerSubject,
    [string]$OutputPath = 'signed/verification.json'
)
$ErrorActionPreference = 'Stop'
$signedPath = (Resolve-Path -LiteralPath $Executable).Path
$unsignedPath = (Resolve-Path -LiteralPath $UnsignedExecutable).Path
$signature = Get-AuthenticodeSignature -LiteralPath $signedPath
if ($signature.Status -ne 'Valid') { throw "Authenticode verification failed: $($signature.Status)" }
if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Subject -ne $ExpectedSignerSubject) {
    throw 'Signer identity differs from the explicitly configured approved signer'
}
if (-not $signature.TimeStamperCertificate) { throw 'A valid timestamp is required' }
$version = (Get-Item -LiteralPath $signedPath).VersionInfo
if ($version.ProductName -ne 'DiskInventory' -or $version.ProductVersion -ne '0.1.0.0' -or $version.FileVersion -ne '0.1.0.0') {
    throw 'Unexpected product or version metadata'
}
$unsignedHash = (Get-FileHash -LiteralPath $unsignedPath -Algorithm SHA256).Hash.ToLowerInvariant()
$signedHash = (Get-FileHash -LiteralPath $signedPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($signedHash -eq $unsignedHash) { throw 'Signed and unsigned files are identical' }
$result = [ordered]@{
    status = 'AUTHENTICODE_VALID'
    source_commit = $env:GITHUB_SHA
    unsigned_sha256 = $unsignedHash
    signed_sha256 = $signedHash
    signer_subject = $signature.SignerCertificate.Subject
    signer_thumbprint = $signature.SignerCertificate.Thumbprint
    timestamp_subject = $signature.TimeStamperCertificate.Subject
    product_name = $version.ProductName
    product_version = $version.ProductVersion
    file_version = $version.FileVersion
}
$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$result | ConvertTo-Json | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Output 'Authenticode, timestamp, publisher and version checks passed. Runtime testing remains a separate step.'

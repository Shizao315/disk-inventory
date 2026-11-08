$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$toolRoot = Join-Path $taskRoot '.tools'
New-Item -ItemType Directory -Force -Path $toolRoot | Out-Null
$index = Invoke-RestMethod -Uri 'https://ziglang.org/download/index.json'
$release = $index.'0.13.0'.'x86_64-windows'
if (-not $release -or -not $release.tarball.StartsWith('https://ziglang.org/')) { throw 'Official toolchain metadata unavailable' }
$archive = Join-Path $toolRoot 'zig-0.13.0.zip'
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -Uri $release.tarball -OutFile $archive -UseBasicParsing
}
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $release.shasum) { throw 'Toolchain SHA256 mismatch; archive retained for diagnosis' }
$compiler = Join-Path $toolRoot 'zig-windows-x86_64-0.13.0\zig.exe'
if (-not (Test-Path -LiteralPath $compiler)) { Expand-Archive -LiteralPath $archive -DestinationPath $toolRoot }
@{version='0.13.0';url=$release.tarball;sha256=$actual} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $toolRoot 'toolchain.json') -Encoding UTF8
& $compiler version

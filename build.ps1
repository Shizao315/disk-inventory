param([string]$ZigPath = '', [string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $ZigPath) { $ZigPath = Join-Path $PSScriptRoot '.tools\zig-windows-x86_64-0.13.0\zig.exe' }
if (-not (Test-Path -LiteralPath $ZigPath)) { throw 'Run setup-toolchain.ps1 first, or pass -ZigPath' }
New-Item -ItemType Directory -Force -Path '.build',$OutputDirectory | Out-Null
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $PSScriptRoot '.build\zig-global'
$env:ZIG_LOCAL_CACHE_DIR = Join-Path $PSScriptRoot '.build\zig-local'
$template = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'src\report-template.html'))
$parts = $template.Split(@('<!--DISK_DATA-->'), [StringSplitOptions]::None)
if ($parts.Count -ne 2) { throw 'Report template must contain exactly one data marker' }
$header = '#pragma once' + "`n" + 'static const char REPORT_HEAD[]=R"DISKREPORT(' + $parts[0] + ')DISKREPORT";' + "`n" + 'static const char REPORT_TAIL[]=R"DISKREPORT(' + $parts[1] + ')DISKREPORT";' + "`n"
[IO.File]::WriteAllText((Join-Path $PSScriptRoot '.build\report_template.h'), $header, (New-Object Text.UTF8Encoding($false)))
& $ZigPath rc /fo .build/app.res src/app.rc
if ($LASTEXITCODE -ne 0) { throw "Version resource compilation failed: $LASTEXITCODE" }
$outputExe = Join-Path $OutputDirectory 'DiskInventory.exe'
& $ZigPath c++ -std=c++17 -Os -s -static -target x86_64-windows-gnu -municode '-Wl,--subsystem,windows' -I .build src/main.cpp .build/app.res -o $outputExe -lshell32 -lole32 -lcomdlg32 -ladvapi32 -luser32 -lgdi32
if ($LASTEXITCODE -ne 0) { throw "C++ compilation failed: $LASTEXITCODE" }
$metadata = (Get-Item -LiteralPath $outputExe).VersionInfo
if ($metadata.ProductName -ne 'DiskInventory' -or $metadata.ProductVersion -ne '0.1.0.0' -or $metadata.FileVersion -ne '0.1.0.0') {
    throw 'Executable product/version metadata does not match the signing configuration'
}
Write-Output "Product metadata verified: $($metadata.ProductName) $($metadata.ProductVersion)"
Get-Item -LiteralPath $outputExe | Select-Object Name,Length | Format-Table -AutoSize
Get-FileHash -LiteralPath $outputExe -Algorithm SHA256 | Format-List Hash,Path

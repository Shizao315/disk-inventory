param([string]$ZigPath = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $ZigPath) { $ZigPath = Join-Path $PSScriptRoot '.tools\zig-windows-x86_64-0.13.0\zig.exe' }
if (-not (Test-Path -LiteralPath $ZigPath)) { throw 'Run setup-toolchain.ps1 first, or pass -ZigPath' }
New-Item -ItemType Directory -Force -Path '.build','dist' | Out-Null
$env:ZIG_GLOBAL_CACHE_DIR = Join-Path $PSScriptRoot '.build\zig-global'
$env:ZIG_LOCAL_CACHE_DIR = Join-Path $PSScriptRoot '.build\zig-local'
$template = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'src\report-template.html'))
$parts = $template.Split(@('<!--DISK_DATA-->'), [StringSplitOptions]::None)
if ($parts.Count -ne 2) { throw 'Report template must contain exactly one data marker' }
$header = '#pragma once' + "`n" + 'static const char REPORT_HEAD[]=R"DISKREPORT(' + $parts[0] + ')DISKREPORT";' + "`n" + 'static const char REPORT_TAIL[]=R"DISKREPORT(' + $parts[1] + ')DISKREPORT";' + "`n"
[IO.File]::WriteAllText((Join-Path $PSScriptRoot '.build\report_template.h'), $header, (New-Object Text.UTF8Encoding($false)))
& $ZigPath c++ -std=c++17 -Os -s -static -target x86_64-windows-gnu -municode '-Wl,--subsystem,windows' -I .build src/main.cpp -o dist/DiskInventory.exe -lshell32 -lole32 -lcomdlg32 -ladvapi32 -luser32 -lgdi32
if ($LASTEXITCODE -ne 0) { throw "C++ compilation failed: $LASTEXITCODE" }
Get-Item -LiteralPath 'dist\DiskInventory.exe' | Select-Object Name,Length
Get-FileHash -LiteralPath 'dist\DiskInventory.exe' -Algorithm SHA256

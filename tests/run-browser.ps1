param([switch]$TemplateReplay, [string]$NodeModulesPath = '', [string]$ReportDirectory = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if ($NodeModulesPath) {
    if (-not (Test-Path -LiteralPath $NodeModulesPath)) { throw 'NodeModulesPath does not exist' }
    $env:NODE_PATH = (Resolve-Path -LiteralPath $NodeModulesPath).Path
}
$nodeArgs = @('tests/report-browser.cjs')
if ($TemplateReplay) { $nodeArgs += '--template-replay' }
if ($ReportDirectory) { $nodeArgs += @('--report-dir', $ReportDirectory) }
node @nodeArgs
if ($LASTEXITCODE -ne 0) { throw 'Browser integration checks failed' }

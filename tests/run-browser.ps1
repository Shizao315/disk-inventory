param([switch]$TemplateReplay, [string]$NodeModulesPath = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if ($NodeModulesPath) {
    if (-not (Test-Path -LiteralPath $NodeModulesPath)) { throw 'NodeModulesPath does not exist' }
    $env:NODE_PATH = (Resolve-Path -LiteralPath $NodeModulesPath).Path
}
if ($TemplateReplay) { node tests/report-browser.cjs --template-replay } else { node tests/report-browser.cjs }
if ($LASTEXITCODE -ne 0) { throw 'Browser integration checks failed' }

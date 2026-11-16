param([int]$EndYear = 2026, [switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Failed: $Executable $($Arguments -join ' ')" }
}
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    Invoke-Checked 'python' @('-m','venv','.venv')
}
$TaskPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
Invoke-Checked $TaskPython @('-m','pip','install','-r','requirements.lock','--disable-pip-version-check','--quiet')
if (-not (Test-Path -LiteralPath '.env')) {
    Invoke-Checked $TaskPython @('-c', 'from pathlib import Path; import secrets; Path(".env").write_text("\n".join(k+"="+secrets.token_urlsafe(24) for k in ["CLICKHOUSE_PASSWORD","DASHBOARD_PASSWORD","SUPERSET_SECRET_KEY","SUPERSET_ADMIN_PASSWORD"])+"\n",encoding="utf-8")')
}
Invoke-Checked 'docker' @('image','inspect','clickhouse/clickhouse-server:26.8','--format','{{.Id}}')
Invoke-Checked 'docker' @('compose','up','-d','--build','--wait')
if (-not $SkipDownload) {
    Invoke-Checked $TaskPython @('-m','etl.download','--start-year','2023','--end-year',"$EndYear")
}
Invoke-Checked $TaskPython @('-m','etl.parse')
Invoke-Checked $TaskPython @('-m','pytest','-q')
Invoke-Checked $TaskPython @('-m','etl.load')
Invoke-Checked 'docker' @('compose','exec','-T','superset','superset','db','upgrade')
Invoke-Checked 'docker' @('compose','exec','-T','superset','superset','init')
Invoke-Checked 'docker' @('compose','exec','-T','superset','python','/app/project/bootstrap.py')
New-Item -ItemType Directory -Path 'outputs' -Force | Out-Null
Invoke-Checked 'docker' @('compose','cp','superset:/app/superset_home/chart_specs.json','outputs/chart_specs.json')
Invoke-Checked $TaskPython @('scripts/verify_dashboard.py')
Write-Host 'Ready: http://localhost:18088/superset/dashboard/food-price-observatory/?standalone=2'
Write-Host 'Login: admin. Password: SUPERSET_ADMIN_PASSWORD in .env'


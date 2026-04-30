param(
    [string]$OutputDir = "final_exe_rc",
    [string]$ValidationReportPath = "",
    [switch]$SkipVerification
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$OutputPath = Join-Path $RepoRoot $OutputDir
$DataPath = Join-Path $OutputPath "data"
$ReportPath = if ($ValidationReportPath) {
    $ValidationReportPath
} else {
    Join-Path $DataPath "packaged-gui-verification-report.json"
}

New-Item -ItemType Directory -Force -Path $DataPath | Out-Null

if ($SkipVerification) {
    $skippedReport = [ordered]@{
        package = [ordered]@{
            name = "Orangelink Browser"
            version = "0.0.0-local"
            build_date = (Get-Date -Format "yyyy-MM-dd")
            portable_path = $OutputPath
        }
        browser_engine = [ordered]@{
            actual_family = "unknown"
            actual_major_version = 0
            claimed_family = "unknown"
            claimed_major_version = 0
        }
        network = [ordered]@{
            proxy_mode = "unknown"
        }
        verification_skipped = $true
        results = [ordered]@{}
    }

    foreach ($id in "A1","A2","A3","A4","A5","A6","A7","A8","A9","A10","A11","A12","A13","A14","A15","A16","A17","A18") {
        $skippedReport.results[$id] = [ordered]@{
            ok = $false
            detail = "Verification skipped during local packaging."
            duration_ms = 0
            failure_class = "verification_skipped"
        }
    }

    $skippedReport | ConvertTo-Json -Depth 8 | Set-Content -Path $ReportPath -Encoding UTF8
    Write-Host "Packaged output written with verification_skipped=true: $ReportPath"
    exit 0
}

if (-not (Test-Path $ReportPath)) {
    throw "Packaged validation report not found: $ReportPath"
}

$Validator = Join-Path $RepoRoot "scripts\validate_packaged_release.py"
python $Validator $ReportPath
if ($LASTEXITCODE -ne 0) {
    throw "Packaged validation gate failed with exit code $LASTEXITCODE."
}

Write-Host "Packaged validation gate passed: $ReportPath"

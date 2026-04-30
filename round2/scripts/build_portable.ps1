param(
    [string]$OutputDir = "final_exe_rc",
    [string]$ValidationReportPath = "",
    [string]$VerifyProxyServer = "",
    [switch]$SkipVerification
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$OutputPath = Join-Path $RepoRoot $OutputDir
$DataPath = Join-Path $OutputPath "data"
$RuntimePath = Join-Path $OutputPath "runtime"
$ChromiumSource = Join-Path $RepoRoot "runtime\chromium"
$ChromiumExecutable = Join-Path $ChromiumSource "chrome.exe"
$ReportPath = if ($ValidationReportPath) {
    $ValidationReportPath
} else {
    Join-Path $DataPath "packaged-gui-verification-report.json"
}

New-Item -ItemType Directory -Force -Path $DataPath | Out-Null
New-Item -ItemType Directory -Force -Path $RuntimePath | Out-Null

if (-not (Test-Path $ChromiumExecutable)) {
    throw "Chromium runtime not found: $ChromiumSource. Place a compatible Chromium build under runtime\chromium before packaging."
}

Copy-Item -Recurse -Force -Path $ChromiumSource -Destination $RuntimePath

$RelayManifest = Join-Path $RepoRoot "relay\Cargo.toml"
$RelayOutput = Join-Path $RepoRoot "relay\target\release\proxy-relay.exe"
$PackagedRelay = Join-Path $OutputPath "proxy-relay.exe"
if (Test-Path $RelayManifest) {
    cargo build --release --manifest-path $RelayManifest
    if ($LASTEXITCODE -ne 0) {
        throw "proxy relay build failed with exit code $LASTEXITCODE."
    }
    Copy-Item -Force -Path $RelayOutput -Destination $PackagedRelay
}

$ReadmePath = Join-Path $OutputPath "README_PORTABLE.txt"
@"
Orangelink Browser Portable Package

How to run
Start Start-脐橙浏览器.bat or 脐橙浏览器.exe from this portable folder.

Data storage
Runtime data is stored under the local data directory.

Local data warning
Portable profile data is not encrypted. Copying or losing this folder may expose local browser data.

Cleanup
Use the desktop GUI to delete saved configs and clear product-created data.

Browser engine
Bundled engine files are under runtime\chromium.

Validation
Release review requires data\packaged-gui-verification-report.json.
"@ | Set-Content -Path $ReadmePath -Encoding UTF8

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

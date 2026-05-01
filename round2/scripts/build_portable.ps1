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
$AppDisplayName = -join ([char[]](0x8110, 0x6A59, 0x6D4F, 0x89C8, 0x5668))
$ChromiumSource = Join-Path $RepoRoot "runtime\chromium"
$ChromiumExecutable = Join-Path $ChromiumSource "chrome.exe"
$ReportPath = if ($ValidationReportPath) {
    $ValidationReportPath
} else {
    Join-Path $DataPath "packaged-gui-verification-report.json"
}

New-Item -ItemType Directory -Force -Path $DataPath | Out-Null
New-Item -ItemType Directory -Force -Path $RuntimePath | Out-Null
Remove-Item -Recurse -Force -LiteralPath (Join-Path $OutputPath "_internal") -ErrorAction SilentlyContinue
Remove-Item -Force -LiteralPath (Join-Path $OutputPath "orangelink-browser.exe") -ErrorAction SilentlyContinue
Remove-Item -Force -LiteralPath (Join-Path $OutputPath "$AppDisplayName.exe") -ErrorAction SilentlyContinue

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

$DesktopEntry = Join-Path $RepoRoot "scripts\desktop_gui.py"
$IconPath = Join-Path $RepoRoot "app\assets\favicon.ico"
$PyInstallerWorkPath = Join-Path $RepoRoot "build\pyinstaller"
$PyInstallerSpecPath = Join-Path $RepoRoot "build\pyinstaller-spec"
$PyInstallerDistPath = Join-Path $RepoRoot "build\pyinstaller-dist"
$PyInstallerAppPath = Join-Path $PyInstallerDistPath "orangelink-browser"
$PyInstallerExePath = Join-Path $OutputPath "orangelink-browser.exe"
$GuiExePath = Join-Path $OutputPath "$AppDisplayName.exe"
$LauncherBatPath = Join-Path $OutputPath "Start-$AppDisplayName.bat"

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Run: python -m pip install pyinstaller"
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --icon $IconPath `
    --name orangelink-browser `
    --contents-directory _internal `
    --distpath $PyInstallerDistPath `
    --workpath $PyInstallerWorkPath `
    --specpath $PyInstallerSpecPath `
    $DesktopEntry
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller GUI build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path $PyInstallerAppPath)) {
    throw "PyInstaller did not produce expected app directory: $PyInstallerAppPath"
}
Copy-Item -Recurse -Force -Path (Join-Path $PyInstallerAppPath "*") -Destination $OutputPath
if (-not (Test-Path $PyInstallerExePath)) {
    throw "PyInstaller did not produce expected executable: $PyInstallerExePath"
}
Move-Item -Force -Path $PyInstallerExePath -Destination $GuiExePath
if (-not (Test-Path $GuiExePath)) {
    throw "PyInstaller did not produce expected executable: $GuiExePath"
}

@'
@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$n=-join([char[]](0x8110,0x6A59,0x6D4F,0x89C8,0x5668)); Start-Process -FilePath (Join-Path '%~dp0' ($n + '.exe'))"
'@ | Set-Content -Path $LauncherBatPath -Encoding ASCII

$ReadmePath = Join-Path $OutputPath "README_PORTABLE.txt"
@"
Orangelink Browser Portable Package

How to run
Start Start-$AppDisplayName.bat or $AppDisplayName.exe from this portable folder.

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

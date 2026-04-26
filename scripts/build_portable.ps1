param(
    [string]$OutputDir = "final_exe"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distRoot = Join-Path $root "dist"
$buildRoot = Join-Path $root "build"
$distApp = Join-Path $distRoot "PrivacyBrowserFramework"
$outputPath = Join-Path $root $OutputDir

Write-Host "[1/6] Build portable executable with PyInstaller..."
Set-Location $root
uv run pyinstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name PrivacyBrowserFramework `
    --paths $root `
    --collect-submodules app `
    --collect-submodules playwright_stealth `
    --collect-data playwright_stealth `
    --hidden-import playwright.sync_api `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtWidgets `
    --add-data "$root\.env.local;." `
    --add-data "$root\.env.example;." `
    "$root\scripts\desktop_gui.py"

if (!(Test-Path $distApp)) {
    throw "PyInstaller output folder not found: $distApp"
}

Write-Host "[2/6] Reset output folder: $outputPath"
if (Test-Path $outputPath) {
    Remove-Item -LiteralPath $outputPath -Recurse -Force
}
New-Item -ItemType Directory -Path $outputPath | Out-Null

Write-Host "[3/6] Copy executable runtime files..."
Copy-Item -Path (Join-Path $distApp "*") -Destination $outputPath -Recurse -Force

Write-Host "[4/6] Bundle Chromium kernel..."
$chromeSrc = Join-Path $root ".playwright\chrome-win64"
$chromeDst = Join-Path $outputPath ".playwright\chrome-win64"
if (!(Test-Path $chromeSrc)) {
    throw "Chrome kernel not found: $chromeSrc"
}
New-Item -ItemType Directory -Path (Split-Path $chromeDst -Parent) -Force | Out-Null
Copy-Item -LiteralPath $chromeSrc -Destination $chromeDst -Recurse -Force

Write-Host "[5/6] Prepare runtime folders and launcher scripts..."
New-Item -ItemType Directory -Path (Join-Path $outputPath "data") -Force | Out-Null

$launcherBat = @"
@echo off
setlocal
cd /d "%~dp0"
"%~dp0PrivacyBrowserFramework.exe"
"@
Set-Content -LiteralPath (Join-Path $outputPath "Start-PrivacyBrowserFramework.bat") -Value $launcherBat -Encoding ASCII

$readme = @"
Privacy Browser Framework - Portable Package

How to run:
1. Double-click Start-PrivacyBrowserFramework.bat
2. Or run PrivacyBrowserFramework.exe directly

Notes:
- This is a portable green build. No installer is required.
- Data is stored under .\data in this folder.
- Bundled Chromium kernel path: .\.playwright\chrome-win64\chrome.exe
- The EXE is a native desktop GUI panel.
- Click "Launch Browser" to open a new browser window based on bundled Chromium kernel.
- If auto fingerprint is enabled, locale/timezone is detected automatically from current network or proxy.
"@
Set-Content -LiteralPath (Join-Path $outputPath "README_PORTABLE.txt") -Value $readme -Encoding UTF8

Write-Host "[6/6] Done."
Write-Host "Portable app output: $outputPath"

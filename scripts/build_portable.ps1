param(
    [string]$OutputDir = "final_exe",
    [string]$AppName = "脐橙浏览器",
    [string]$IconRelativePath = "app/assets/favicon.ico"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distRoot = Join-Path $root "dist"
$buildRoot = Join-Path $root "build"
$iconPath = Join-Path $root $IconRelativePath
$distApp = Join-Path $distRoot $AppName
$outputPath = Join-Path $root $OutputDir

if (!(Test-Path $iconPath)) {
    throw "Icon file not found: $iconPath"
}

Write-Host "[1/6] Build portable executable with PyInstaller..."
Set-Location $root

$pyinstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", $AppName,
    "--icon", $iconPath,
    "--specpath", $buildRoot,
    "--paths", $root,
    "--collect-submodules", "app",
    "--collect-submodules", "playwright_stealth",
    "--collect-data", "playwright_stealth",
    "--hidden-import", "playwright.sync_api",
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",
    "--add-data", "$root\.env.example;."
)

$envLocalPath = Join-Path $root ".env.local"
if (Test-Path $envLocalPath) {
    $pyinstallerArgs += @("--add-data", "$envLocalPath;.")
}

$pyinstallerArgs += (Join-Path $root "scripts\desktop_gui.py")
uv run pyinstaller @pyinstallerArgs

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
    throw "Chrome kernel not found: $chromeSrc. Run 'uv run playwright install chromium' first."
}
New-Item -ItemType Directory -Path (Split-Path $chromeDst -Parent) -Force | Out-Null
Copy-Item -LiteralPath $chromeSrc -Destination $chromeDst -Recurse -Force

Write-Host "[5/6] Prepare runtime folders and launcher scripts..."
New-Item -ItemType Directory -Path (Join-Path $outputPath "data") -Force | Out-Null

$launcherBat = @"
@echo off
setlocal
cd /d "%~dp0"
"%~dp0$AppName.exe"
"@
Set-Content -LiteralPath (Join-Path $outputPath "Start-$AppName.bat") -Value $launcherBat -Encoding ASCII

$readme = @"
$AppName - Portable Build

How to run:
1. Double-click Start-$AppName.bat
2. Or run $AppName.exe directly

Notes:
- Portable build, no installer required.
- Runtime data is saved under .\\data.
- Bundled Chromium kernel path: .\\.playwright\\chrome-win64\\chrome.exe
"@
Set-Content -LiteralPath (Join-Path $outputPath "README_PORTABLE.txt") -Value $readme -Encoding UTF8

Write-Host "[6/6] Done."
Write-Host "Portable app output: $outputPath"

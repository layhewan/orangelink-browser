param(
    [string]$AllGroups = "true"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not installed. Install uv first, then rerun this script."
}

Write-Host "[1/3] Sync Python interpreter from .python-version..."
uv python install

Write-Host "[2/3] Create venv and sync lockfile..."
$mode = "$AllGroups".Trim().ToLowerInvariant()
$useAllGroups = $true
if ($mode -in @("0", "false", "no", "off")) {
    $useAllGroups = $false
} elseif ($mode -in @("1", "true", "yes", "on", "")) {
    $useAllGroups = $true
} else {
    throw "Invalid -AllGroups value: '$AllGroups'. Use true/false or 1/0."
}

if ($useAllGroups) {
    uv sync --frozen --all-groups
} else {
    uv sync --frozen
}

Write-Host "[3/3] Verify runtime..."
uv run python -V
Write-Host "Environment clone complete."

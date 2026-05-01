from __future__ import annotations

from pathlib import Path


REQUIRED_PORTABLE_PATHS = (
    "脐橙浏览器.exe",
    "Start-脐橙浏览器.bat",
    "_internal",
    "proxy-relay.exe",
    "runtime/chromium/chrome.exe",
    "data",
    "README_PORTABLE.txt",
    "data/packaged-gui-verification-report.json",
)


def validate_portable_folder(portable_path: Path) -> list[str]:
    errors: list[str] = []
    for relative_path in REQUIRED_PORTABLE_PATHS:
        if not (portable_path / Path(relative_path)).exists():
            errors.append(f"missing portable path: {relative_path}")
    return errors


def render_portable_readme(*, engine_family: str, engine_version: str) -> str:
    return f"""# Orangelink Browser Portable Package

## How to run

Start `Start-脐橙浏览器.bat` or `脐橙浏览器.exe` from this portable folder.

## Data storage

Runtime data is stored under the local `data` directory, including configs,
profiles, logs, reports, homepage files, cache, cookies, and extension data.

## Local data warning

Portable profile data is not encrypted. Copying or losing this folder may expose
local browser data.

## Cleanup

Use the desktop GUI to delete saved configs and clear product-created data.
Temporary session data is removed only when it has an Orangelink owner marker.

## Browser engine

Bundled engine: {engine_family} {engine_version}

## Validation

Release review requires `data/packaged-gui-verification-report.json`. A package
without that report is not a release candidate.
"""

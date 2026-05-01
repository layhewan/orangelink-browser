from __future__ import annotations

import shutil
from pathlib import Path


def test_required_portable_paths_match_release_contract() -> None:
    from scripts.packaging_contract import REQUIRED_PORTABLE_PATHS

    assert REQUIRED_PORTABLE_PATHS == (
        "脐橙浏览器.exe",
        "Start-脐橙浏览器.bat",
        "_internal",
        "proxy-relay.exe",
        "runtime/chromium/chrome.exe",
        "data",
        "README_PORTABLE.txt",
        "data/packaged-gui-verification-report.json",
    )


def test_validate_portable_folder_reports_missing_required_paths() -> None:
    from scripts.packaging_contract import validate_portable_folder

    portable = Path("tests/acceptance/_tmp_portable_contract")
    shutil.rmtree(portable, ignore_errors=True)
    portable.mkdir(parents=True)
    (portable / "data").mkdir()

    try:
        errors = validate_portable_folder(portable)

        assert "missing portable path: 脐橙浏览器.exe" in errors
        assert "missing portable path: runtime/chromium/chrome.exe" in errors
    finally:
        shutil.rmtree(portable, ignore_errors=True)


def test_portable_readme_mentions_data_storage_encryption_and_validation() -> None:
    from scripts.packaging_contract import render_portable_readme

    readme = render_portable_readme(
        engine_family="Chromium",
        engine_version="123.0.0.0",
    )

    assert "How to run" in readme
    assert "data" in readme
    assert "not encrypted" in readme
    assert "delete saved configs" in readme
    assert "Chromium 123.0.0.0" in readme
    assert "packaged-gui-verification-report.json" in readme


def test_build_script_has_chromium_missing_message_and_readme_generation() -> None:
    script = Path("scripts/build_portable.ps1").read_text(encoding="utf-8")

    assert "Chromium runtime not found:" in script
    assert "runtime\\chromium" in script
    assert "README_PORTABLE.txt" in script


def test_build_script_creates_gui_exe_and_launcher_bat() -> None:
    script = Path("scripts/build_portable.ps1").read_text(encoding="utf-8")

    assert "python -m PyInstaller" in script
    assert "--onedir" in script
    assert "--contents-directory _internal" in script
    assert "--icon" in script
    assert "app\\assets\\favicon.ico" in script
    assert 'Remove-Item -Recurse -Force -LiteralPath (Join-Path $OutputPath "_internal")' in script
    assert "--name orangelink-browser" in script
    assert "orangelink-browser.exe" in script
    assert "[char[]](0x8110, 0x6A59, 0x6D4F, 0x89C8, 0x5668)" in script
    assert "Start-$AppDisplayName.bat" in script
    assert "$AppDisplayName.exe" in script
    assert "Start-Process -FilePath" in script
    assert "Encoding ASCII" in script


def test_release_runbook_exists_with_final_acceptance_sequence() -> None:
    runbook = Path("docs/release/RELEASE_RUNBOOK.md").read_text(encoding="utf-8")

    assert "python -m pytest tests -q" in runbook
    assert "cargo test --manifest-path relay\\Cargo.toml" in runbook
    assert "build_portable.ps1" in runbook
    assert "release-final-report.json" in runbook

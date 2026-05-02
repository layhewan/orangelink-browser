from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ACCEPTANCE_IDS = tuple(f"A{i}" for i in range(1, 19))
P0_IDS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A13")


def _valid_report() -> dict:
    return {
        "package": {
            "name": "Orangelink Browser",
            "version": "0.1.0",
            "build_date": "2026-04-30",
            "portable_path": "D:/portable/orangelink",
        },
        "browser_engine": {
            "actual_family": "Chromium",
            "actual_major_version": 123,
            "claimed_family": "Chrome",
            "claimed_major_version": 123,
        },
        "network": {
            "proxy_mode": "direct",
        },
        "verification_skipped": False,
        "results": {
            acceptance_id: {
                "ok": True,
                "detail": f"{acceptance_id} passed",
                "duration_ms": 1,
            }
            for acceptance_id in ACCEPTANCE_IDS
        },
    }


def test_acceptance_constants_cover_product_spec_ids() -> None:
    from scripts.validate_packaged_release import ACCEPTANCE_IDS as actual_ids
    from scripts.validate_packaged_release import P0_IDS as actual_p0_ids

    assert actual_ids == ACCEPTANCE_IDS
    assert actual_p0_ids == P0_IDS


def test_validate_report_accepts_complete_report() -> None:
    from scripts.validate_packaged_release import validate_report

    assert validate_report(_valid_report()) == []


@pytest.mark.parametrize("missing_id", ACCEPTANCE_IDS)
def test_validate_report_requires_every_acceptance_result(missing_id: str) -> None:
    from scripts.validate_packaged_release import validate_report

    report = _valid_report()
    del report["results"][missing_id]

    assert f"missing result for {missing_id}" in validate_report(report)


@pytest.mark.parametrize(
    ("section", "field", "expected_error"),
    [
        ("package", "version", "missing package.version"),
        ("package", "build_date", "missing package.build_date"),
        ("browser_engine", "actual_family", "missing browser_engine.actual_family"),
        (
            "browser_engine",
            "actual_major_version",
            "missing browser_engine.actual_major_version",
        ),
        ("browser_engine", "claimed_family", "missing browser_engine.claimed_family"),
        (
            "browser_engine",
            "claimed_major_version",
            "missing browser_engine.claimed_major_version",
        ),
        ("network", "proxy_mode", "missing network.proxy_mode"),
    ],
)
def test_validate_report_requires_release_metadata(
    section: str, field: str, expected_error: str
) -> None:
    from scripts.validate_packaged_release import validate_report

    report = _valid_report()
    del report[section][field]

    assert expected_error in validate_report(report)


def test_validate_report_requires_failure_details_for_failed_checks() -> None:
    from scripts.validate_packaged_release import validate_report

    report = _valid_report()
    report["results"]["A2"] = {"ok": False}

    errors = validate_report(report)

    assert "A2 failed result missing detail" in errors
    assert "A2 failed result missing failure_class" in errors


def test_release_ready_requires_all_p0_items_to_pass() -> None:
    from scripts.validate_packaged_release import release_ready

    report = _valid_report()
    report["results"]["A13"] = {
        "ok": False,
        "detail": "proxy loss loaded through local network",
        "failure_class": "proxy_bypass",
        "duration_ms": 10,
    }

    assert release_ready(report) is False


def test_release_ready_allows_p1_failure_only_with_user_impact() -> None:
    from scripts.validate_packaged_release import release_ready

    report = _valid_report()
    report["results"]["A10"] = {
        "ok": False,
        "detail": "small-height resize clips optional diagnostics",
        "failure_class": "responsive_layout",
        "duration_ms": 10,
    }
    assert release_ready(report) is False

    report["results"]["A10"]["user_impact"] = "Diagnostic panel requires scrolling."
    assert release_ready(report) is True


def test_cli_fails_non_ready_report() -> None:
    report = _valid_report()
    report["results"]["A1"] = {
        "ok": False,
        "detail": "packaged executable did not launch",
        "failure_class": "launch_failure",
        "duration_ms": 100,
    }
    report_path = Path(__file__).with_name("_tmp_non_ready_report.json")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    try:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/validate_packaged_release.py",
                str(report_path),
            ],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    finally:
        report_path.unlink(missing_ok=True)

    assert result.returncode == 1
    assert "release_ready=false" in result.stdout


def test_acceptance_matrix_doc_lists_all_ids() -> None:
    doc_path = Path("docs/release/ACCEPTANCE_MATRIX.md")
    content = doc_path.read_text(encoding="utf-8")

    for acceptance_id in ACCEPTANCE_IDS:
        assert f"| {acceptance_id} |" in content


def test_build_script_skip_verification_is_never_release_ready_text() -> None:
    script = Path("scripts/build_portable.ps1").read_text(encoding="utf-8")

    assert "verification_skipped" in script
    assert "Release ready" not in script
    assert "release-ready" not in script

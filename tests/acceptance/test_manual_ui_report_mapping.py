from __future__ import annotations

import json
from pathlib import Path


def test_manual_ui_check_ids_cover_acceptance_matrix() -> None:
    from scripts.manual_ui_acceptance import MANUAL_UI_CHECK_IDS
    from scripts.validate_packaged_release import ACCEPTANCE_IDS

    assert MANUAL_UI_CHECK_IDS == ACCEPTANCE_IDS


def test_manual_ui_report_maps_all_results_to_validation_schema() -> None:
    from scripts.manual_ui_acceptance import ManualCheckResult, build_manual_ui_report
    from scripts.validate_packaged_release import ACCEPTANCE_IDS, validate_report

    report = build_manual_ui_report(
        checks={
            acceptance_id: ManualCheckResult(
                acceptance_id=acceptance_id,
                ok=True,
                detail=f"{acceptance_id} passed",
                duration_ms=1,
            )
            for acceptance_id in ACCEPTANCE_IDS
        },
        package={
            "version": "0.1.0",
            "build_date": "2026-04-30",
            "portable_path": "final_exe_rc",
        },
        browser_engine={
            "actual_family": "Chromium",
            "actual_major_version": 123,
            "claimed_family": "Chrome",
            "claimed_major_version": 123,
        },
        network={"proxy_mode": "direct"},
    )

    assert sorted(report["results"]) == sorted(ACCEPTANCE_IDS)
    assert validate_report(report) == []


def test_failed_p1_manual_check_includes_user_impact() -> None:
    from scripts.manual_ui_acceptance import ManualCheckResult, build_manual_ui_report

    report = build_manual_ui_report(
        checks={
            "A9": ManualCheckResult(
                acceptance_id="A9",
                ok=False,
                detail="BrowserScan did not finish loading",
                failure_class="site_load_failure",
                duration_ms=2500,
                user_impact="用户无法查看 BrowserScan 环境结果。",
            )
        },
        package={"version": "0.1.0", "build_date": "2026-04-30"},
        browser_engine={
            "actual_family": "Chromium",
            "actual_major_version": 123,
            "claimed_family": "Chrome",
            "claimed_major_version": 123,
        },
        network={"proxy_mode": "direct"},
        fill_missing=True,
    )

    assert report["results"]["A9"]["user_impact"] == "用户无法查看 BrowserScan 环境结果。"


def test_write_manual_ui_report_creates_packaged_report_file() -> None:
    from scripts.manual_ui_acceptance import ManualCheckResult, write_manual_ui_report

    output = Path("tests/acceptance/_tmp_manual_report.json")
    output.unlink(missing_ok=True)

    try:
        write_manual_ui_report(
            output,
            checks={
                "A1": ManualCheckResult(
                    acceptance_id="A1",
                    ok=False,
                    detail="Packaged GUI did not open",
                    failure_class="launch_failure",
                    duration_ms=100,
                )
            },
            package={"version": "0.1.0", "build_date": "2026-04-30"},
            browser_engine={
                "actual_family": "Chromium",
                "actual_major_version": 123,
                "claimed_family": "Chrome",
                "claimed_major_version": 123,
            },
            network={"proxy_mode": "direct"},
            fill_missing=True,
        )

        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["results"]["A1"]["failure_class"] == "launch_failure"
    finally:
        output.unlink(missing_ok=True)

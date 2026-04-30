from __future__ import annotations

import pytest


def test_claimed_chrome_major_cannot_exceed_actual_engine_major() -> None:
    from app.runtime.engine_version import (
        BrowserEngineVersion,
        EngineVersionError,
        ensure_claim_compatible,
    )

    actual = BrowserEngineVersion(family="Chromium", major=123, full_version="123.0.0.0")

    ensure_claim_compatible(actual, claimed_family="Chrome", claimed_major=123)
    with pytest.raises(EngineVersionError) as exc_info:
        ensure_claim_compatible(actual, claimed_family="Chrome", claimed_major=124)

    assert "浏览器版本声明不能高于实际内核版本" in str(exc_info.value)


def test_parse_chromium_version_output_extracts_family_and_major() -> None:
    from app.runtime.engine_version import parse_chromium_version_output

    version = parse_chromium_version_output("Chromium 123.0.6312.86")

    assert version.family == "Chromium"
    assert version.major == 123
    assert version.full_version == "123.0.6312.86"


def test_engine_metadata_contains_validation_report_fields() -> None:
    from app.runtime.engine_version import BrowserEngineVersion, build_engine_report_metadata

    metadata = build_engine_report_metadata(
        actual=BrowserEngineVersion(family="Chromium", major=123, full_version="123.0.6312.86"),
        claimed_family="Chrome",
        claimed_major=123,
        package_version="0.1.0",
        package_build_date="2026-04-30",
    )

    assert metadata["browser_engine"] == {
        "actual_family": "Chromium",
        "actual_major_version": 123,
        "actual_version": "123.0.6312.86",
        "claimed_family": "Chrome",
        "claimed_major_version": 123,
    }
    assert metadata["package"]["version"] == "0.1.0"
    assert metadata["package"]["build_date"] == "2026-04-30"

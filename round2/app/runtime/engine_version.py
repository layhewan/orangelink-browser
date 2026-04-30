from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


VERSION_RE = re.compile(r"(?P<family>Chromium|Google Chrome|Chrome)\s+(?P<version>\d+(?:\.\d+)+)")


class EngineVersionError(ValueError):
    pass


@dataclass(frozen=True)
class BrowserEngineVersion:
    family: str
    major: int
    full_version: str


def parse_chromium_version_output(output: str) -> BrowserEngineVersion:
    match = VERSION_RE.search(output.strip())
    if match is None:
        raise EngineVersionError(f"无法识别浏览器内核版本: {output}")

    family = match.group("family")
    if family == "Google Chrome":
        family = "Chrome"
    full_version = match.group("version")
    return BrowserEngineVersion(
        family=family,
        major=int(full_version.split(".", 1)[0]),
        full_version=full_version,
    )


def read_chromium_version(chrome_executable: Path) -> BrowserEngineVersion:
    result = subprocess.run(
        [str(chrome_executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_chromium_version_output(result.stdout or result.stderr)


def ensure_claim_compatible(
    actual: BrowserEngineVersion,
    *,
    claimed_family: str,
    claimed_major: int,
) -> None:
    if claimed_major > actual.major:
        raise EngineVersionError(
            "浏览器版本声明不能高于实际内核版本: "
            f"claimed={claimed_family} {claimed_major}, actual={actual.family} {actual.major}"
        )


def build_engine_report_metadata(
    *,
    actual: BrowserEngineVersion,
    claimed_family: str,
    claimed_major: int,
    package_version: str,
    package_build_date: str,
) -> dict:
    ensure_claim_compatible(
        actual,
        claimed_family=claimed_family,
        claimed_major=claimed_major,
    )
    return {
        "browser_engine": {
            "actual_family": actual.family,
            "actual_major_version": actual.major,
            "actual_version": actual.full_version,
            "claimed_family": claimed_family,
            "claimed_major_version": claimed_major,
        },
        "package": {
            "version": package_version,
            "build_date": package_build_date,
        },
    }

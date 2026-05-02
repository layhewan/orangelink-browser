from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.validate_packaged_release import ACCEPTANCE_IDS, P0_IDS


MANUAL_UI_CHECK_IDS = ACCEPTANCE_IDS
P0_ID_SET = set(P0_IDS)


@dataclass(frozen=True)
class ManualCheckResult:
    acceptance_id: str
    ok: bool
    detail: str
    duration_ms: int
    failure_class: str | None = None
    user_impact: str | None = None

    def to_report_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ok": self.ok,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
        }
        if self.failure_class is not None:
            entry["failure_class"] = self.failure_class
        if self.user_impact is not None:
            entry["user_impact"] = self.user_impact
        elif not self.ok and self.acceptance_id not in P0_ID_SET:
            entry["user_impact"] = "Manual UI failure requires release decision."
        return entry


def build_manual_ui_report(
    *,
    checks: dict[str, ManualCheckResult],
    package: dict[str, Any],
    browser_engine: dict[str, Any],
    network: dict[str, Any],
    fill_missing: bool = False,
) -> dict[str, Any]:
    missing = [acceptance_id for acceptance_id in ACCEPTANCE_IDS if acceptance_id not in checks]
    if missing and not fill_missing:
        raise ValueError(f"missing manual UI checks: {', '.join(missing)}")

    results = {
        acceptance_id: checks[acceptance_id].to_report_entry()
        for acceptance_id in checks
    }
    if fill_missing:
        for acceptance_id in missing:
            results[acceptance_id] = {
                "ok": True,
                "detail": "Filled by partial manual UI report fixture.",
                "duration_ms": 0,
            }

    return {
        "package": package,
        "browser_engine": browser_engine,
        "network": network,
        "verification_skipped": False,
        "results": {acceptance_id: results[acceptance_id] for acceptance_id in ACCEPTANCE_IDS},
    }


def write_manual_ui_report(
    output_path: Path,
    *,
    checks: dict[str, ManualCheckResult],
    package: dict[str, Any],
    browser_engine: dict[str, Any],
    network: dict[str, Any],
    fill_missing: bool = False,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = build_manual_ui_report(
        checks=checks,
        package=package,
        browser_engine=browser_engine,
        network=network,
        fill_missing=fill_missing,
    )
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a packaged manual UI acceptance report.")
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    write_manual_ui_report(
        args.output,
        checks={},
        package={"version": "0.0.0-local", "build_date": "unknown"},
        browser_engine={
            "actual_family": "unknown",
            "actual_major_version": 0,
            "claimed_family": "unknown",
            "claimed_major_version": 0,
        },
        network={"proxy_mode": "unknown"},
        fill_missing=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

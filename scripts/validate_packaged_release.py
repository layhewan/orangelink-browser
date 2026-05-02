from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ACCEPTANCE_IDS = (
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
    "A7",
    "A8",
    "A9",
    "A10",
    "A11",
    "A12",
    "A13",
    "A14",
    "A15",
    "A16",
    "A17",
    "A18",
)

P0_IDS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A13")
P1_IDS = tuple(acceptance_id for acceptance_id in ACCEPTANCE_IDS if acceptance_id not in P0_IDS)

REQUIRED_METADATA_FIELDS = (
    ("package", "version"),
    ("package", "build_date"),
    ("browser_engine", "actual_family"),
    ("browser_engine", "actual_major_version"),
    ("browser_engine", "claimed_family"),
    ("browser_engine", "claimed_major_version"),
    ("network", "proxy_mode"),
)


def validate_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for section, field in REQUIRED_METADATA_FIELDS:
        section_value = report.get(section)
        if not isinstance(section_value, dict) or _is_blank(section_value.get(field)):
            errors.append(f"missing {section}.{field}")

    results = report.get("results")
    if not isinstance(results, dict):
        errors.append("missing results")
        return errors

    for acceptance_id in ACCEPTANCE_IDS:
        result = results.get(acceptance_id)
        if not isinstance(result, dict):
            errors.append(f"missing result for {acceptance_id}")
            continue

        ok = result.get("ok")
        if not isinstance(ok, bool):
            errors.append(f"{acceptance_id} result missing ok")

        if _is_blank(result.get("detail")):
            if ok is False:
                errors.append(f"{acceptance_id} failed result missing detail")
            else:
                errors.append(f"{acceptance_id} result missing detail")

        if "duration_ms" not in result:
            errors.append(f"{acceptance_id} result missing duration_ms")

        if ok is False and _is_blank(result.get("failure_class")):
            errors.append(f"{acceptance_id} failed result missing failure_class")

    return errors


def release_ready(report: dict[str, Any]) -> bool:
    if report.get("verification_skipped") is True:
        return False

    if validate_report(report):
        return False

    results = report["results"]
    for acceptance_id in P0_IDS:
        if results[acceptance_id].get("ok") is not True:
            return False

    for acceptance_id in P1_IDS:
        result = results[acceptance_id]
        if result.get("ok") is False and _is_blank(result.get("user_impact")):
            return False

    return True


def health_result_to_report_entry(result: Any) -> dict[str, Any]:
    entry = {
        "ok": bool(result.ok),
        "detail": str(result.detail),
        "duration_ms": int(result.duration_ms),
    }
    if result.failure_class is not None:
        entry["failure_class"] = str(result.failure_class)
    return entry


def load_report(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise ValueError("validation report root must be a JSON object")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate packaged Orangelink release report.")
    parser.add_argument("report", type=Path, help="Path to packaged validation report JSON.")
    args = parser.parse_args(argv)

    try:
        report = load_report(args.report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"report_load_error={exc}")
        return 2

    errors = validate_report(report)
    for error in errors:
        print(f"schema_error={error}")

    ready = release_ready(report)
    print(f"release_ready={str(ready).lower()}")

    if errors:
        return 2
    return 0 if ready else 1


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


if __name__ == "__main__":
    raise SystemExit(main())

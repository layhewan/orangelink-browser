from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.runtime.config import PortablePaths


REQUIRED_DIAGNOSTIC_EVENTS = (
    "session_start_requested",
    "relay_ready",
    "browser_launch_started",
    "session_ready",
    "page_load_failure",
    "google_validation",
    "browserscan_validation",
    "proxy_loss_detected",
    "session_stop_requested",
    "session_stopped",
    "cleanup_completed",
)

SENSITIVE_KEY_PARTS = (
    "password",
    "cookie",
    "token",
    "page_content",
)

CREDENTIAL_URL_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/@]+:[^/@]+)@")


class DiagnosticLogger:
    def __init__(self, paths: PortablePaths, *, date_stamp: str | None = None) -> None:
        self.paths = paths
        self.date_stamp = date_stamp or datetime.now().strftime("%Y%m%d")
        self.paths.logs.mkdir(parents=True, exist_ok=True)

    def log_event(self, event: str, data: dict[str, Any]) -> Path:
        log_path = self.paths.logs / f"runtime-{self.date_stamp}.jsonl"
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "data": redact_sensitive(data),
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return log_path


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted

    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]

    if isinstance(value, str):
        return CREDENTIAL_URL_RE.sub(r"\g<scheme>***:***@", value)

    return value

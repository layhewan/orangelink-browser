from __future__ import annotations

import json
import shutil
from pathlib import Path


def test_redacts_proxy_passwords_cookies_tokens_and_page_content() -> None:
    from app.runtime.diagnostics import redact_sensitive

    redacted = redact_sensitive(
        {
            "proxy_url": "http://user:secret@127.0.0.1:7890",
            "account_password": "hunter2",
            "cookies": "session=abc",
            "extension_token": "ext-secret",
            "page_content": "<html>private</html>",
            "nested": {"token": "nested-secret"},
        }
    )

    serialized = json.dumps(redacted)
    for secret in ("secret", "hunter2", "session=abc", "ext-secret", "private", "nested-secret"):
        assert secret not in serialized
    assert redacted["proxy_url"] == "http://***:***@127.0.0.1:7890"


def test_diagnostic_logger_writes_redacted_jsonl_event() -> None:
    from app.runtime.config import resolve_portable_paths
    from app.runtime.diagnostics import DiagnosticLogger

    base = Path(__file__).resolve().parent / "_tmp_diagnostics_base"
    shutil.rmtree(base, ignore_errors=True)
    paths = resolve_portable_paths(base=base, create=True)

    try:
        logger = DiagnosticLogger(paths, date_stamp="20260430")
        log_path = logger.log_event(
            "session_start_requested",
            {"proxy_url": "http://user:secret@127.0.0.1:7890"},
        )

        line = log_path.read_text(encoding="utf-8").strip()
        event = json.loads(line)
        assert event["event"] == "session_start_requested"
        assert event["data"]["proxy_url"] == "http://***:***@127.0.0.1:7890"
        assert "secret" not in line
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_required_diagnostic_event_names_are_declared() -> None:
    from app.runtime.diagnostics import REQUIRED_DIAGNOSTIC_EVENTS

    assert REQUIRED_DIAGNOSTIC_EVENTS == (
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

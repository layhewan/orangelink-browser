from __future__ import annotations

from pathlib import Path


class FakeLauncher:
    def __init__(self) -> None:
        self.stopped = False

    def launch(self, *, config, session_id: str, start_url: str, **kwargs):
        from app.runtime.chromium_launcher import ChromiumLaunchResult

        return ChromiumLaunchResult(
            process=object(),
            args=["chrome.exe"],
            cdp_port=9222,
            profile_dir=Path(f"data/profiles/{session_id}"),
            relay=None,
        )

    def stop(self, launch_result) -> None:
        self.stopped = True


class FakeDiagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def log_event(self, event: str, data: dict):
        self.events.append((event, data))


def test_proxy_loss_after_two_failed_probes_marks_failed_closed_without_stopping_tabs() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    launcher = FakeLauncher()
    diagnostics = FakeDiagnostics()
    manager = SessionManager(
        launcher=launcher,
        readiness_probe=lambda launch: True,
        diagnostics=diagnostics,
    )
    session = manager.launch(
        LaunchConfig(
            name="Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7890,
        ),
        start_url="https://example.test/",
    )

    manager.record_proxy_probe(session.session_id, ok=False, detail="upstream unavailable")
    assert manager.sessions[session.session_id].status == "running"

    manager.record_proxy_probe(session.session_id, ok=False, detail="upstream unavailable")

    assert manager.sessions[session.session_id].status == "network_failed_closed"
    assert launcher.stopped is False
    assert diagnostics.events[-1] == (
        "proxy_loss_detected",
        {"session_id": session.session_id, "detail": "upstream unavailable"},
    )


def test_successful_proxy_probe_resets_failure_count() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    manager = SessionManager(
        launcher=FakeLauncher(),
        readiness_probe=lambda launch: True,
    )
    session = manager.launch(
        LaunchConfig(
            name="Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=7890,
        ),
        start_url="https://example.test/",
    )

    manager.record_proxy_probe(session.session_id, ok=False, detail="first miss")
    manager.record_proxy_probe(session.session_id, ok=True, detail="recovered")
    manager.record_proxy_probe(session.session_id, ok=False, detail="second miss")

    assert manager.sessions[session.session_id].status == "running"

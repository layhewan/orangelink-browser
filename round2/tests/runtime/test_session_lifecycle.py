from __future__ import annotations

from pathlib import Path


class FakeLauncher:
    def __init__(self) -> None:
        self.launched: list[tuple[str, str]] = []
        self.stopped: list[str] = []

    def launch(self, *, config, session_id: str, start_url: str):
        from app.runtime.chromium_launcher import ChromiumLaunchResult

        self.launched.append((session_id, config.name))
        return ChromiumLaunchResult(
            process=object(),
            args=["chrome.exe", f"--user-data-dir=data/profiles/{session_id}"],
            cdp_port=9222,
            profile_dir=Path(f"data/profiles/{session_id}"),
            relay=None,
        )

    def stop(self, launch_result) -> None:
        self.stopped.append(str(launch_result.profile_dir))


def test_session_manager_marks_running_only_after_readiness_succeeds() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    manager = SessionManager(
        launcher=FakeLauncher(),
        readiness_probe=lambda launch: True,
    )

    session = manager.launch(LaunchConfig(name="Direct"), start_url="https://example.test/")

    assert session.status == "running"
    assert session.failure_reason is None


def test_session_manager_marks_failed_when_readiness_fails() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    manager = SessionManager(
        launcher=FakeLauncher(),
        readiness_probe=lambda launch: False,
    )

    session = manager.launch(LaunchConfig(name="Direct"), start_url="https://example.test/")

    assert session.status == "failed"
    assert session.failure_reason == "first page readiness failed"


def test_stop_one_session_does_not_stop_unrelated_sessions() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    launcher = FakeLauncher()
    manager = SessionManager(launcher=launcher, readiness_probe=lambda launch: True)
    first = manager.launch(LaunchConfig(name="One"), start_url="https://one.test/")
    second = manager.launch(LaunchConfig(name="Two"), start_url="https://two.test/")

    manager.stop(first.session_id)

    assert manager.sessions[first.session_id].status == "stopped"
    assert manager.sessions[second.session_id].status == "running"
    assert len(launcher.stopped) == 1

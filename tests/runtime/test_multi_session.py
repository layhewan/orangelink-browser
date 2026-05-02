from __future__ import annotations

from pathlib import Path


class FakeLauncher:
    def __init__(self) -> None:
        self.stopped: list[str] = []

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
        self.stopped.append(str(launch_result.profile_dir))


def test_five_sessions_allowed_and_sixth_rejected_with_chinese_message() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    manager = SessionManager(
        launcher=FakeLauncher(),
        readiness_probe=lambda launch: True,
        max_sessions=5,
    )

    sessions = [
        manager.launch(LaunchConfig(name=f"S{i}"), start_url="https://example.test/")
        for i in range(5)
    ]
    rejected = manager.launch(LaunchConfig(name="S6"), start_url="https://example.test/")

    assert [session.status for session in sessions] == ["running"] * 5
    assert rejected.status == "failed"
    assert rejected.failure_reason == "最多只能同时运行 5 个会话"


def test_same_proxy_reuse_is_rejected_by_default() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    manager = SessionManager(launcher=FakeLauncher(), readiness_probe=lambda launch: True)
    config = LaunchConfig(
        name="Proxy",
        proxy_enabled=True,
        proxy_host="127.0.0.1",
        proxy_port=7890,
    )

    first = manager.launch(config, start_url="https://example.test/")
    second = manager.launch(config, start_url="https://example.test/")

    assert first.status == "running"
    assert second.status == "failed"
    assert second.failure_reason == "同一代理已被运行中的会话使用"


def test_same_proxy_reuse_can_be_enabled_per_config() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    manager = SessionManager(launcher=FakeLauncher(), readiness_probe=lambda launch: True)
    config = LaunchConfig(
        name="Proxy",
        proxy_enabled=True,
        proxy_host="127.0.0.1",
        proxy_port=7890,
        proxy_reuse_allowed=True,
    )

    first = manager.launch(config, start_url="https://example.test/")
    second = manager.launch(config, start_url="https://example.test/")

    assert first.status == "running"
    assert second.status == "running"


def test_failed_session_does_not_corrupt_running_session() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.session_manager import SessionManager

    readiness_results = iter([True, False])
    manager = SessionManager(
        launcher=FakeLauncher(),
        readiness_probe=lambda launch: next(readiness_results),
    )

    running = manager.launch(LaunchConfig(name="Running"), start_url="https://example.test/")
    failed = manager.launch(LaunchConfig(name="Failed"), start_url="https://example.test/")

    assert running.status == "running"
    assert failed.status == "failed"
    assert manager.sessions[running.session_id].status == "running"


def test_stop_one_session_does_not_stop_all_sessions() -> None:
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

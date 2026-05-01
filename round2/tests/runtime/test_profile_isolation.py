from __future__ import annotations

import shutil
from pathlib import Path

import pytest


class RecordingLauncher:
    def __init__(self) -> None:
        self.profile_dirs: list[Path] = []
        self.stopped: list[Path] = []

    def launch(self, *, config, session_id: str, start_url: str, profile_dir: Path | None = None):
        from app.runtime.chromium_launcher import ChromiumLaunchResult

        assert profile_dir is not None
        self.profile_dirs.append(profile_dir)
        return ChromiumLaunchResult(
            process=object(),
            args=["chrome.exe", f"--user-data-dir={profile_dir}"],
            cdp_port=9222,
            profile_dir=profile_dir,
            relay=None,
        )

    def stop(self, launch_result) -> None:
        self.stopped.append(launch_result.profile_dir)


def test_temporary_current_form_profile_is_removed_on_stop() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.profiles import ProfileManager
    from app.runtime.session_manager import SessionManager

    manager, launcher, profile_manager = _manager()

    session = manager.launch(LaunchConfig(name="Temp"), start_url="https://example.test/")
    profile_dir = launcher.profile_dirs[0]

    assert profile_dir == profile_manager.paths.profiles / f"temp-{session.session_id}"
    assert (profile_dir / "owner.json").is_file()

    manager.stop(session.session_id)

    assert not profile_dir.exists()


def test_saved_config_profile_survives_session_stop() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.profiles import RUNTIME_LOCK_FILENAME

    manager, launcher, profile_manager = _manager()

    session = manager.launch(
        LaunchConfig(name="Saved"),
        start_url="https://example.test/",
        saved_config_id="42",
    )
    profile_dir = launcher.profile_dirs[0]

    assert profile_dir == profile_manager.paths.profiles / "cfg-42"
    assert (profile_dir / RUNTIME_LOCK_FILENAME).is_file()

    manager.stop(session.session_id)

    assert profile_dir.exists()
    assert not (profile_dir / RUNTIME_LOCK_FILENAME).exists()


def test_saved_config_cannot_launch_twice_at_same_time() -> None:
    from app.runtime.config import LaunchConfig

    manager, launcher, profile_manager = _manager()

    first = manager.launch(
        LaunchConfig(name="Saved A"),
        start_url="https://example.test/",
        saved_config_id="42",
    )
    second = manager.launch(
        LaunchConfig(name="Saved A"),
        start_url="https://example.test/",
        saved_config_id="42",
    )

    assert first.status == "running"
    assert second.status == "failed"
    assert second.failure_reason == "该配置已在运行中"
    assert launcher.profile_dirs == [profile_manager.paths.profiles / "cfg-42"]


def test_failed_readiness_releases_profile_runtime_lock_and_stops_browser() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.profiles import RUNTIME_LOCK_FILENAME, ProfileManager
    from app.runtime.session_manager import SessionManager

    profile_manager = ProfileManager(_paths())
    launcher = RecordingLauncher()
    manager = SessionManager(
        launcher=launcher,
        readiness_probe=lambda launch: False,
        profile_manager=profile_manager,
    )

    session = manager.launch(
        LaunchConfig(name="Saved"),
        start_url="https://example.test/",
        saved_config_id="42",
    )
    profile_dir = profile_manager.paths.profiles / "cfg-42"

    assert session.status == "failed"
    assert session.failure_reason == "first page readiness failed"
    assert launcher.stopped == [profile_dir]
    assert not (profile_dir / RUNTIME_LOCK_FILENAME).exists()


def test_readiness_exception_releases_profile_runtime_lock_and_stops_browser() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.profiles import RUNTIME_LOCK_FILENAME, ProfileManager
    from app.runtime.session_manager import SessionManager

    def failing_probe(launch) -> bool:
        raise RuntimeError("probe failed")

    profile_manager = ProfileManager(_paths())
    launcher = RecordingLauncher()
    manager = SessionManager(
        launcher=launcher,
        readiness_probe=failing_probe,
        profile_manager=profile_manager,
    )

    session = manager.launch(
        LaunchConfig(name="Saved"),
        start_url="https://example.test/",
        saved_config_id="42",
    )
    profile_dir = profile_manager.paths.profiles / "cfg-42"

    assert session.status == "failed"
    assert session.failure_reason == "probe failed"
    assert launcher.stopped == [profile_dir]
    assert not (profile_dir / RUNTIME_LOCK_FILENAME).exists()


def test_cleanup_only_removes_profiles_with_matching_owner_marker() -> None:
    from app.runtime.profiles import ProfileManager

    profile_manager = ProfileManager(_paths())
    profile = profile_manager.saved_config_profile("42")
    (profile.path / "owner.json").write_text("{}", encoding="utf-8")

    assert profile_manager.cleanup_owned_profile("saved_config", "42") is False
    assert profile.path.exists()


def test_cleanup_retries_when_windows_temporarily_locks_profile(monkeypatch) -> None:
    from app.runtime.profiles import ProfileManager

    profile_manager = ProfileManager(_paths(), remove_retries=1, remove_delay_s=0)
    profile = profile_manager.temporary_profile("locked")
    calls = 0
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("profile file is still closing")
        real_rmtree(path)

    monkeypatch.setattr("app.runtime.profiles.shutil.rmtree", flaky_rmtree)

    assert profile_manager.cleanup_temporary(profile) is True
    assert calls == 2
    assert not profile.path.exists()


def test_cleanup_returns_false_instead_of_raising_when_profile_stays_locked(monkeypatch) -> None:
    from app.runtime.profiles import ProfileManager

    profile_manager = ProfileManager(_paths(), remove_retries=1, remove_delay_s=0)
    profile = profile_manager.temporary_profile("still-locked")

    def locked_rmtree(path: Path) -> None:
        raise PermissionError("profile file is still closing")

    monkeypatch.setattr("app.runtime.profiles.shutil.rmtree", locked_rmtree)

    assert profile_manager.cleanup_temporary(profile) is False
    assert profile.path.exists()


def test_profile_runtime_lock_blocks_live_profile_owner() -> None:
    from app.runtime.profiles import ProfileInUseError, ProfileManager

    profile_manager = ProfileManager(_paths())
    profile = profile_manager.saved_config_profile("42")
    lock = profile_manager.acquire_runtime_lock(profile, session_id="session-a")

    try:
        with pytest.raises(ProfileInUseError) as exc:
            profile_manager.acquire_runtime_lock(profile, session_id="session-b")
    finally:
        lock.release()

    assert "已在运行" in str(exc.value)


def test_profile_runtime_lock_replaces_dead_owner(monkeypatch) -> None:
    from app.runtime.profiles import RUNTIME_LOCK_FILENAME, ProfileManager

    profile_manager = ProfileManager(_paths())
    profile = profile_manager.saved_config_profile("42")
    lock_path = profile.path / RUNTIME_LOCK_FILENAME
    lock_path.write_text(
        '{"created_by":"orangelink-browser","pid":999999,"session_id":"dead"}',
        encoding="utf-8",
    )
    monkeypatch.setattr("app.runtime.profiles._is_pid_alive", lambda pid: False)

    lock = profile_manager.acquire_runtime_lock(profile, session_id="fresh")

    try:
        assert '"session_id": "fresh"' in lock_path.read_text(encoding="utf-8")
    finally:
        lock.release()


def test_profile_runtime_lock_does_not_delete_fresh_unreadable_lock() -> None:
    from app.runtime.profiles import RUNTIME_LOCK_FILENAME, ProfileInUseError, ProfileManager

    profile_manager = ProfileManager(_paths())
    profile = profile_manager.saved_config_profile("42")
    lock_path = profile.path / RUNTIME_LOCK_FILENAME
    lock_path.write_text("{", encoding="utf-8")

    with pytest.raises(ProfileInUseError) as exc:
        profile_manager.acquire_runtime_lock(profile, session_id="fresh")

    assert "正在启动" in str(exc.value)
    assert lock_path.read_text(encoding="utf-8") == "{"


def test_profile_runtime_lock_replaces_stale_unreadable_lock() -> None:
    import os

    from app.runtime.profiles import RUNTIME_LOCK_FILENAME, ProfileManager

    profile_manager = ProfileManager(_paths())
    profile = profile_manager.saved_config_profile("42")
    lock_path = profile.path / RUNTIME_LOCK_FILENAME
    lock_path.write_text("{", encoding="utf-8")
    os.utime(lock_path, (0, 0))

    lock = profile_manager.acquire_runtime_lock(profile, session_id="fresh")

    try:
        assert '"session_id": "fresh"' in lock_path.read_text(encoding="utf-8")
    finally:
        lock.release()


def test_profile_runtime_lock_refuses_active_chromium_singleton() -> None:
    from app.runtime.profiles import ProfileInUseError, ProfileManager

    profile_manager = ProfileManager(_paths())
    profile = profile_manager.saved_config_profile("42")
    (profile.path / "SingletonLock").write_text("", encoding="utf-8")

    with pytest.raises(ProfileInUseError) as exc:
        profile_manager.acquire_runtime_lock(profile, session_id="fresh")

    assert "Chromium 占用" in str(exc.value)


def test_session_stop_releases_profile_lock_when_launcher_stop_fails() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.profiles import RUNTIME_LOCK_FILENAME, ProfileManager
    from app.runtime.session_manager import SessionManager

    class FailingStopLauncher(RecordingLauncher):
        def stop(self, launch_result) -> None:
            super().stop(launch_result)
            raise RuntimeError("stop failed")

    profile_manager = ProfileManager(_paths())
    launcher = FailingStopLauncher()
    manager = SessionManager(
        launcher=launcher,
        readiness_probe=lambda launch: True,
        profile_manager=profile_manager,
    )
    session = manager.launch(
        LaunchConfig(name="Saved"),
        start_url="https://example.test/",
        saved_config_id="42",
    )
    profile_dir = profile_manager.paths.profiles / "cfg-42"

    with pytest.raises(RuntimeError):
        manager.stop(session.session_id)

    assert not (profile_dir / RUNTIME_LOCK_FILENAME).exists()


def _manager():
    from app.runtime.config import resolve_portable_paths
    from app.runtime.profiles import ProfileManager
    from app.runtime.session_manager import SessionManager

    profile_manager = ProfileManager(_paths())
    launcher = RecordingLauncher()
    manager = SessionManager(
        launcher=launcher,
        readiness_probe=lambda launch: True,
        profile_manager=profile_manager,
    )
    return manager, launcher, profile_manager


def _paths():
    from app.runtime.config import resolve_portable_paths

    base = Path(__file__).resolve().parent / "_tmp_profiles_base"
    shutil.rmtree(base, ignore_errors=True)
    return resolve_portable_paths(base=base, create=True)

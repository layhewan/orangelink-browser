from __future__ import annotations

import shutil
from pathlib import Path


class RecordingLauncher:
    def __init__(self) -> None:
        self.profile_dirs: list[Path] = []

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
        return None


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

    manager, launcher, profile_manager = _manager()

    session = manager.launch(
        LaunchConfig(name="Saved"),
        start_url="https://example.test/",
        saved_config_id="42",
    )
    profile_dir = launcher.profile_dirs[0]

    assert profile_dir == profile_manager.paths.profiles / "cfg-42"

    manager.stop(session.session_id)

    assert profile_dir.exists()


def test_cleanup_only_removes_profiles_with_matching_owner_marker() -> None:
    from app.runtime.profiles import ProfileManager

    profile_manager = ProfileManager(_paths())
    profile = profile_manager.saved_config_profile("42")
    (profile.path / "owner.json").write_text("{}", encoding="utf-8")

    assert profile_manager.cleanup_owned_profile("saved_config", "42") is False
    assert profile.path.exists()


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

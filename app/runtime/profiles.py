from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from app.runtime.config import PortablePaths


CREATED_BY = "orangelink-browser"
RUNTIME_LOCK_FILENAME = "orangelink-runtime.lock"
CHROMIUM_SINGLETON_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")
STALE_RUNTIME_LOCK_SECONDS = 60.0


class ProfileInUseError(RuntimeError):
    """Raised when a profile directory is already owned by a live browser session."""


@dataclass(frozen=True)
class ProfileHandle:
    path: Path
    owner_type: str
    owner_id: str
    persistent: bool


@dataclass(frozen=True)
class ProfileRuntimeLock:
    profile: ProfileHandle
    path: Path
    token: str

    def release(self) -> None:
        _release_runtime_lock(self.path, self.token)


class ProfileManager:
    def __init__(
        self,
        paths: PortablePaths,
        *,
        remove_retries: int = 5,
        remove_delay_s: float = 0.15,
    ) -> None:
        self.paths = paths
        self._remove_retries = remove_retries
        self._remove_delay_s = remove_delay_s
        self.paths.profiles.mkdir(parents=True, exist_ok=True)

    def temporary_profile(self, session_id: str) -> ProfileHandle:
        return self._ensure_profile(
            path=self.paths.profiles / f"temp-{session_id}",
            owner_type="temporary",
            owner_id=session_id,
            persistent=False,
        )

    def saved_config_profile(self, config_id: str) -> ProfileHandle:
        return self._ensure_profile(
            path=self.paths.profiles / f"cfg-{config_id}",
            owner_type="saved_config",
            owner_id=config_id,
            persistent=True,
        )

    def extension_dir(self, profile: ProfileHandle) -> Path:
        return profile.path / "Default" / "Extensions"

    def acquire_runtime_lock(
        self,
        profile: ProfileHandle,
        *,
        session_id: str,
    ) -> ProfileRuntimeLock:
        profile.path.mkdir(parents=True, exist_ok=True)
        lock_path = profile.path / RUNTIME_LOCK_FILENAME
        token = f"{os.getpid()}:{session_id}:{time.monotonic_ns()}"

        for _ in range(2):
            if lock_path.exists():
                marker = _read_runtime_lock(lock_path)
                if _runtime_lock_blocks_acquisition(lock_path, marker):
                    raise ProfileInUseError(_runtime_lock_block_message(marker))
                _unlink_if_exists(lock_path)
                continue

            _raise_if_chromium_owns_profile(profile.path)
            marker = {
                "created_by": CREATED_BY,
                "pid": os.getpid(),
                "session_id": session_id,
                "token": token,
            }
            try:
                with lock_path.open("x", encoding="utf-8") as handle:
                    json.dump(marker, handle, ensure_ascii=False, indent=2)
                return ProfileRuntimeLock(profile=profile, path=lock_path, token=token)
            except FileExistsError:
                continue

        raise ProfileInUseError("该浏览器环境已在运行中，请先关闭旧窗口")

    def cleanup_temporary(self, profile: ProfileHandle) -> bool:
        if profile.owner_type != "temporary":
            return False
        return self.cleanup_owned_profile(profile.owner_type, profile.owner_id)

    def cleanup_owned_profile(self, owner_type: str, owner_id: str) -> bool:
        profile_dir = self.paths.profiles / (
            f"temp-{owner_id}" if owner_type == "temporary" else f"cfg-{owner_id}"
        )
        marker_path = profile_dir / "owner.json"
        if not marker_path.exists():
            return False

        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False

        if marker != _owner_marker(owner_type, owner_id):
            return False

        return remove_tree_with_retries(
            profile_dir,
            retries=self._remove_retries,
            delay_s=self._remove_delay_s,
        )

    def _ensure_profile(
        self,
        *,
        path: Path,
        owner_type: str,
        owner_id: str,
        persistent: bool,
    ) -> ProfileHandle:
        path.mkdir(parents=True, exist_ok=True)
        (path / "owner.json").write_text(
            json.dumps(_owner_marker(owner_type, owner_id), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return ProfileHandle(
            path=path,
            owner_type=owner_type,
            owner_id=owner_id,
            persistent=persistent,
        )


def _owner_marker(owner_type: str, owner_id: str) -> dict[str, str]:
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "created_by": CREATED_BY,
    }


def _read_runtime_lock(path: Path) -> dict[str, object] | None:
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return marker if isinstance(marker, dict) else None


def _runtime_lock_blocks_acquisition(path: Path, marker: dict[str, object] | None) -> bool:
    if marker is None or marker.get("created_by") != CREATED_BY:
        return not _is_runtime_lock_stale(path)
    pid = marker.get("pid")
    if not isinstance(pid, int):
        return not _is_runtime_lock_stale(path)
    return _is_pid_alive(pid)


def _runtime_lock_block_message(marker: dict[str, object] | None) -> str:
    if _runtime_lock_has_process_owner(marker):
        return "该浏览器环境已在运行中，请先关闭旧窗口"
    return "该浏览器环境正在启动中，请稍后重试"


def _runtime_lock_has_process_owner(marker: dict[str, object] | None) -> bool:
    if marker is None or marker.get("created_by") != CREATED_BY:
        return False
    pid = marker.get("pid")
    return isinstance(pid, int)


def _is_runtime_lock_stale(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age > STALE_RUNTIME_LOCK_SECONDS


def _release_runtime_lock(path: Path, token: str) -> None:
    marker = _read_runtime_lock(path)
    if marker is None or marker.get("token") != token:
        return
    _unlink_if_exists(path)


def _raise_if_chromium_owns_profile(profile_path: Path) -> None:
    for name in CHROMIUM_SINGLETON_FILES:
        candidate = profile_path / name
        if candidate.exists() or candidate.is_symlink():
            raise ProfileInUseError("浏览器数据目录正在被 Chromium 占用，请先关闭旧窗口")


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    if os.name == "nt":
        return _is_windows_pid_alive(pid)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_windows_pid_alive(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == 5


def remove_tree_with_retries(path: Path, *, retries: int = 5, delay_s: float = 0.15) -> bool:
    attempts = max(1, retries + 1)
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            if attempt == attempts - 1:
                return False
            time.sleep(delay_s)
    return False

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from app.runtime.config import PortablePaths


CREATED_BY = "orangelink-browser"


@dataclass(frozen=True)
class ProfileHandle:
    path: Path
    owner_type: str
    owner_id: str
    persistent: bool


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

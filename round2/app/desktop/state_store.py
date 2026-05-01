from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.runtime.config import LaunchConfig, PortablePaths
from app.runtime.profiles import remove_tree_with_retries


@dataclass(frozen=True)
class SavedConfig:
    config_id: str
    config: LaunchConfig


class StateStore:
    def __init__(self, paths: PortablePaths) -> None:
        self.paths = paths
        self.state_path = self.paths.configs / "desktop-state.json"
        self.paths.configs.mkdir(parents=True, exist_ok=True)

    def save_config(self, config: LaunchConfig) -> SavedConfig:
        state = self._read_state()
        config_id = str(state["next_config_number"])
        state["next_config_number"] += 1
        state["configs"][config_id] = _config_to_dict(config)
        self._write_state(state)
        return SavedConfig(config_id=config_id, config=config)

    def list_configs(self) -> list[SavedConfig]:
        state = self._read_state()
        return [
            SavedConfig(config_id=config_id, config=LaunchConfig(**data))
            for config_id, data in sorted(
                state["configs"].items(),
                key=lambda item: int(item[0]),
            )
        ]

    def load_config(self, config_id: str) -> LaunchConfig:
        state = self._read_state()
        return LaunchConfig(**state["configs"][config_id])

    def update_config(self, config_id: str, config: LaunchConfig) -> None:
        state = self._read_state()
        if config_id not in state["configs"]:
            raise KeyError(config_id)
        state["configs"][config_id] = _config_to_dict(config)
        self._write_state(state)

    def delete_config(self, config_id: str, *, remove_profile: bool = False) -> bool:
        state = self._read_state()
        state["configs"].pop(config_id, None)
        self._write_state(state)
        if remove_profile:
            return self._remove_profile_if_owned(config_id)
        return True

    def save_last_form(self, config: LaunchConfig) -> None:
        state = self._read_state()
        state["last_form"] = _config_to_dict(config)
        self._write_state(state)

    def load_last_form(self) -> LaunchConfig:
        state = self._read_state()
        if state["last_form"] is None:
            return LaunchConfig(name="默认配置")
        return LaunchConfig(**state["last_form"])

    def profile_dir_for(self, config_id: str) -> Path:
        return self.paths.profiles / f"cfg-{config_id}"

    def _remove_profile_if_owned(self, config_id: str) -> bool:
        profile_dir = self.profile_dir_for(config_id)
        marker_path = profile_dir / "owner.json"
        if not marker_path.exists():
            return False

        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False

        if marker == {
            "owner_type": "saved_config",
            "owner_id": config_id,
            "created_by": "orangelink-browser",
        }:
            return remove_tree_with_retries(profile_dir)
        return False

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "next_config_number": 1,
                "configs": {},
                "last_form": None,
                "warnings": {},
            }
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _config_to_dict(config: LaunchConfig) -> dict[str, Any]:
    return asdict(config)

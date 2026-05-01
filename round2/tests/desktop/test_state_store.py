from __future__ import annotations

import json
import shutil
from pathlib import Path


def test_state_store_saves_loads_updates_and_deletes_configs() -> None:
    from app.desktop.state_store import StateStore
    from app.runtime.config import LaunchConfig, resolve_portable_paths

    store = _store()
    saved = store.save_config(LaunchConfig(name="默认配置"))

    assert store.load_config(saved.config_id).name == "默认配置"

    store.update_config(saved.config_id, LaunchConfig(name="更新配置", start_page="https://example.test"))
    assert store.load_config(saved.config_id).name == "更新配置"
    assert store.load_config(saved.config_id).start_page == "https://example.test"

    store.delete_config(saved.config_id)
    assert store.list_configs() == []


def test_last_form_state_persists_across_store_instances() -> None:
    from app.desktop.state_store import StateStore
    from app.runtime.config import LaunchConfig

    store = _store()
    store.save_last_form(
        LaunchConfig(
            name="Last",
            automatic_language=False,
            manual_language="zh-CN",
        )
    )

    reloaded = StateStore(store.paths)

    assert reloaded.load_last_form().manual_language == "zh-CN"


def test_delete_saved_config_can_remove_owned_profile_data() -> None:
    from app.runtime.config import LaunchConfig

    store = _store()
    saved = store.save_config(LaunchConfig(name="Persistent"))
    profile_dir = store.profile_dir_for(saved.config_id)
    profile_dir.mkdir(parents=True)
    (profile_dir / "owner.json").write_text(
        json.dumps(
            {
                "owner_type": "saved_config",
                "owner_id": saved.config_id,
                "created_by": "orangelink-browser",
            }
        ),
        encoding="utf-8",
    )
    (profile_dir / "Extension State").mkdir()

    assert store.delete_config(saved.config_id, remove_profile=True) is True

    assert not profile_dir.exists()


def test_delete_saved_config_does_not_remove_unmarked_profile_data() -> None:
    from app.runtime.config import LaunchConfig

    store = _store()
    saved = store.save_config(LaunchConfig(name="Persistent"))
    profile_dir = store.profile_dir_for(saved.config_id)
    profile_dir.mkdir(parents=True)
    (profile_dir / "unowned.txt").write_text("keep", encoding="utf-8")

    assert store.delete_config(saved.config_id, remove_profile=True) is False

    assert profile_dir.exists()


def test_delete_saved_config_does_not_remove_profile_with_runtime_lock() -> None:
    from app.runtime.config import LaunchConfig
    from app.runtime.profiles import RUNTIME_LOCK_FILENAME

    store = _store()
    saved = store.save_config(LaunchConfig(name="Persistent"))
    profile_dir = store.profile_dir_for(saved.config_id)
    profile_dir.mkdir(parents=True)
    (profile_dir / "owner.json").write_text(
        json.dumps(
            {
                "owner_type": "saved_config",
                "owner_id": saved.config_id,
                "created_by": "orangelink-browser",
            }
        ),
        encoding="utf-8",
    )
    (profile_dir / RUNTIME_LOCK_FILENAME).write_text("{}", encoding="utf-8")

    assert store.delete_config(saved.config_id, remove_profile=True) is False

    assert profile_dir.exists()
    assert (profile_dir / RUNTIME_LOCK_FILENAME).exists()


def test_delete_saved_config_keeps_state_when_owned_profile_is_locked(monkeypatch) -> None:
    from app.runtime.config import LaunchConfig

    store = _store()
    saved = store.save_config(LaunchConfig(name="Persistent"))
    profile_dir = store.profile_dir_for(saved.config_id)
    profile_dir.mkdir(parents=True)
    (profile_dir / "owner.json").write_text(
        json.dumps(
            {
                "owner_type": "saved_config",
                "owner_id": saved.config_id,
                "created_by": "orangelink-browser",
            }
        ),
        encoding="utf-8",
    )

    def locked_rmtree(path: Path) -> None:
        raise PermissionError("profile file is still closing")

    monkeypatch.setattr("app.runtime.profiles.shutil.rmtree", locked_rmtree)

    assert store.delete_config(saved.config_id, remove_profile=True) is False

    assert store.list_configs() == []
    assert profile_dir.exists()


def _store():
    from app.desktop.state_store import StateStore
    from app.runtime.config import resolve_portable_paths

    base = Path(__file__).resolve().parent / "_tmp_desktop_base"
    shutil.rmtree(base, ignore_errors=True)
    paths = resolve_portable_paths(base=base, create=True)
    return StateStore(paths)

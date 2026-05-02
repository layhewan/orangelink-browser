from __future__ import annotations

import shutil
from pathlib import Path


def test_saved_configs_have_distinct_extension_directories() -> None:
    from app.runtime.profiles import ProfileManager

    profile_manager = ProfileManager(_paths())
    first = profile_manager.saved_config_profile("1")
    second = profile_manager.saved_config_profile("2")

    assert profile_manager.extension_dir(first) == first.path / "Default" / "Extensions"
    assert profile_manager.extension_dir(second) == second.path / "Default" / "Extensions"
    assert profile_manager.extension_dir(first) != profile_manager.extension_dir(second)


def test_owner_marker_records_saved_config_profile_ownership() -> None:
    import json

    from app.runtime.profiles import ProfileManager

    profile_manager = ProfileManager(_paths())
    profile = profile_manager.saved_config_profile("99")

    marker = json.loads((profile.path / "owner.json").read_text(encoding="utf-8"))

    assert marker == {
        "owner_type": "saved_config",
        "owner_id": "99",
        "created_by": "orangelink-browser",
    }


def _paths():
    from app.runtime.config import resolve_portable_paths

    base = Path(__file__).resolve().parent / "_tmp_extensions_base"
    shutil.rmtree(base, ignore_errors=True)
    return resolve_portable_paths(base=base, create=True)

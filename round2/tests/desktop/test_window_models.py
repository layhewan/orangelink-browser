from __future__ import annotations

from pathlib import Path


def test_chinese_ui_strings_exist_for_every_visible_control() -> None:
    from app.desktop.window import VISIBLE_CONTROL_KEYS, ZH_UI_STRINGS

    missing = [key for key in VISIBLE_CONTROL_KEYS if not ZH_UI_STRINGS.get(key)]

    assert missing == []
    assert all(any(ord(char) > 127 for char in ZH_UI_STRINGS[key]) for key in VISIBLE_CONTROL_KEYS)


def test_invalid_config_returns_user_facing_chinese_error() -> None:
    from app.desktop.models import LaunchConfigForm

    result = LaunchConfigForm(name=" ").validate()

    assert result.ok is False
    assert result.error == "配置名称不能为空"


def test_window_model_exposes_primary_user_path_sections() -> None:
    from app.desktop.window import MAIN_WINDOW_SECTIONS, MINIMUM_WINDOW_SIZE, USES_SCROLL_AREA

    assert MINIMUM_WINDOW_SIZE == (980, 680)
    assert USES_SCROLL_AREA is True
    assert MAIN_WINDOW_SECTIONS == (
        "configuration_editor",
        "launch_current_form",
        "saved_configurations",
        "running_sessions",
        "session_controls",
        "diagnostic_log",
        "portable_data_warning",
    )


def test_desktop_gui_script_is_thin_entry_point() -> None:
    script = Path("scripts/desktop_gui.py").read_text(encoding="utf-8")

    assert "from app.desktop.main import run_desktop_gui" in script
    assert "raise SystemExit(run_desktop_gui())" in script


def test_pyproject_declares_pyside_gui_dependency() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8").lower()

    assert "pyside6" in pyproject

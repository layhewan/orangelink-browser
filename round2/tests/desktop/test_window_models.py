from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import os
import json
import socket
import threading
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer


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

    assert MINIMUM_WINDOW_SIZE == (1320, 760)
    assert USES_SCROLL_AREA is False
    assert MAIN_WINDOW_SECTIONS == (
        "configuration_editor",
        "launch_current_form",
        "saved_configurations",
        "running_sessions",
        "session_controls",
        "diagnostic_log",
        "portable_data_warning",
    )


def test_create_main_window_uses_strings_for_all_sections() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QScrollArea

    from app.desktop.window import create_main_window

    app = QApplication.instance() or QApplication([])
    window = create_main_window()

    assert window.windowTitle() == "脐橙浏览器"
    assert window.minimumWidth() == 1320
    assert window.minimumHeight() == 760
    assert window.windowIcon().isNull() is False
    assert not isinstance(window.centralWidget(), QScrollArea)
    window.close()
    app.quit()


def test_launch_button_passes_form_values_to_launch_handler() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton

    from app.desktop.window import create_main_window

    captured = {}

    def launch_handler(*, config, start_url):
        captured["config"] = config
        captured["start_url"] = start_url
        return "session-1"

    app = QApplication.instance() or QApplication([])
    window = create_main_window(launch_handler=launch_handler)

    window.findChild(QLineEdit, "config_name").setText("Proxy Test")
    window.findChild(QLineEdit, "start_page").setText("https://example.com/")
    window.findChild(QCheckBox, "proxy_enabled").setCheckState(Qt.Checked)
    window.findChild(QLineEdit, "proxy_host").setText("127.0.0.1")
    window.findChild(QComboBox, "proxy_port").setCurrentText("7897")
    window.findChild(QPushButton, "launch_current_form").click()

    assert captured["config"].name == "Proxy Test"
    assert captured["config"].proxy_enabled is True
    assert captured["config"].proxy_host == "127.0.0.1"
    assert captured["config"].proxy_port == 7897
    assert captured["start_url"] == "https://example.com/"
    window.close()
    app.quit()


def test_gui_exposes_recommended_proxy_protocols_and_ports() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit

    from app.desktop.window import create_main_window

    app = QApplication.instance() or QApplication([])
    window = create_main_window(launch_handler=lambda **kwargs: object())
    proxy_protocol = window.findChild(QComboBox, "proxy_protocol")
    proxy_port = window.findChild(QComboBox, "proxy_port")
    automatic_language = window.findChild(QCheckBox, "language_mode")
    manual_language = window.findChild(QLineEdit, "manual_language")
    os_fingerprint = window.findChild(QComboBox, "os_fingerprint")
    extension_support = window.findChild(QCheckBox, "extension_support")

    assert [proxy_protocol.itemText(index) for index in range(proxy_protocol.count())] == [
        "http",
        "https",
        "socks5",
    ]
    assert [proxy_port.itemText(index) for index in range(proxy_port.count())] == [
        "7897",
        "7890",
        "10808",
    ]
    assert proxy_port.isEditable() is True
    assert automatic_language.isChecked() is True
    assert manual_language.text() == "en-US"
    assert [os_fingerprint.itemText(index) for index in range(os_fingerprint.count())] == [
        "windows",
        "macos",
        "linux",
    ]
    assert extension_support.isChecked() is True
    window.close()
    app.quit()


def test_gui_lists_saved_environments_with_proxy_and_fingerprint_summary() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QListWidget, QLabel

    from app.desktop.state_store import StateStore
    from app.desktop.window import create_main_window
    from app.runtime.config import LaunchConfig

    app = QApplication.instance() or QApplication([])
    store = StateStore(_desktop_paths())
    store.save_config(
        LaunchConfig(
            name="美国环境",
            proxy_enabled=True,
            proxy_protocol="socks5",
            proxy_host="127.0.0.1",
            proxy_port=10808,
            cached_language="en-US",
            cached_timezone="America/Los_Angeles",
        )
    )

    window = create_main_window(
        launch_handler=lambda **kwargs: object(),
        state_store=store,
        geo_probe=lambda _: None,
    )
    config_list = window.findChild(QListWidget, "saved_configurations")
    environment_count = window.findChild(QLabel, "environment_count")

    assert config_list.item(0).text() == (
        "美国环境\n"
        "socks5://127.0.0.1:10808 · en-US · America/Los_Angeles"
    )
    assert environment_count.text() == "1 个环境"
    window.close()
    app.quit()


def test_gui_stylesheet_defines_workbench_sections() -> None:
    from app.desktop.window import _desktop_stylesheet

    stylesheet = _desktop_stylesheet()

    assert "QFrame#workspace_header" in stylesheet
    assert "QFrame#network_section" in stylesheet
    assert "QFrame#fingerprint_section" in stylesheet
    assert "QFrame#session_section" in stylesheet
    assert "QListWidget::item" in stylesheet


def test_gui_can_save_and_launch_selected_persistent_config() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QListWidget, QPushButton

    from app.desktop.state_store import StateStore
    from app.desktop.window import create_main_window

    captured = {}

    def launch_handler(*, config, start_url, saved_config_id=None):
        captured["config"] = config
        captured["start_url"] = start_url
        captured["saved_config_id"] = saved_config_id
        return object()

    app = QApplication.instance() or QApplication([])
    store = StateStore(_desktop_paths())
    window = create_main_window(
        launch_handler=launch_handler,
        state_store=store,
        geo_probe=lambda _: None,
    )

    window.findChild(QLineEdit, "config_name").setText("环境 A")
    window.findChild(QLineEdit, "start_page").setText("https://www.baidu.com/")
    window.findChild(QCheckBox, "proxy_enabled").setCheckState(Qt.Checked)
    window.findChild(QComboBox, "proxy_protocol").setCurrentText("socks5")
    window.findChild(QComboBox, "proxy_port").setCurrentText("10808")
    window.findChild(QCheckBox, "language_mode").setCheckState(Qt.Unchecked)
    window.findChild(QLineEdit, "manual_language").setText("zh-CN")
    window.findChild(QComboBox, "os_fingerprint").setCurrentText("macos")
    window.findChild(QCheckBox, "extension_support").setCheckState(Qt.Unchecked)
    window.findChild(QPushButton, "save_config").click()
    config_list = window.findChild(QListWidget, "saved_configurations")

    assert config_list.count() == 1

    config_list.setCurrentRow(0)
    window.findChild(QPushButton, "launch_current_form").click()

    assert captured["config"].name == "环境 A"
    assert captured["config"].proxy_protocol == "socks5"
    assert captured["config"].proxy_port == 10808
    assert captured["config"].automatic_language is False
    assert captured["config"].manual_language == "zh-CN"
    assert captured["config"].os_fingerprint == "macos"
    assert captured["config"].extension_support is False
    assert captured["start_url"] == "https://www.baidu.com/"
    assert captured["saved_config_id"] == "1"
    window.close()
    app.quit()


def test_gui_save_button_creates_new_environment_instead_of_overwriting_selection() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QPushButton

    from app.desktop.state_store import StateStore
    from app.desktop.window import create_main_window

    app = QApplication.instance() or QApplication([])
    store = StateStore(_desktop_paths())
    window = create_main_window(
        launch_handler=lambda **kwargs: object(),
        state_store=store,
        geo_probe=lambda _: None,
    )

    name_input = window.findChild(QLineEdit, "config_name")
    save_button = window.findChild(QPushButton, "save_config")
    config_list = window.findChild(QListWidget, "saved_configurations")

    name_input.setText("环境 A")
    save_button.click()
    config_list.setCurrentRow(0)
    name_input.setText("环境 B")
    save_button.click()

    saved = store.list_configs()
    assert [item.config.name for item in saved] == ["环境 A", "环境 B"]
    assert config_list.count() == 2
    assert config_list.currentRow() == 1
    window.close()
    app.quit()


def test_gui_launch_dirty_selected_environment_saves_new_profile_id() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QPushButton

    from app.desktop.state_store import StateStore
    from app.desktop.window import create_main_window
    from app.runtime.config import LaunchConfig

    captured = {}

    def launch_handler(*, config, start_url, saved_config_id=None):
        captured["config"] = config
        captured["saved_config_id"] = saved_config_id
        return object()

    app = QApplication.instance() or QApplication([])
    store = StateStore(_desktop_paths())
    store.save_config(LaunchConfig(name="环境 A"))
    window = create_main_window(
        launch_handler=launch_handler,
        state_store=store,
        geo_probe=lambda _: None,
    )

    config_list = window.findChild(QListWidget, "saved_configurations")
    config_list.setCurrentRow(0)
    window.findChild(QLineEdit, "config_name").setText("环境 B")
    window.findChild(QPushButton, "launch_current_form").click()

    assert captured["config"].name == "环境 B"
    assert captured["saved_config_id"] == "2"
    assert [item.config.name for item in store.list_configs()] == ["环境 A", "环境 B"]
    assert config_list.currentRow() == 1
    window.close()
    app.quit()


def test_gui_blocks_deleting_running_saved_environment() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton

    from app.desktop.state_store import StateStore
    from app.desktop.window import create_main_window
    from app.runtime.config import LaunchConfig

    class FakeSession:
        def stop(self) -> None:
            return None

    app = QApplication.instance() or QApplication([])
    store = StateStore(_desktop_paths())
    saved = store.save_config(LaunchConfig(name="运行环境"))
    window = create_main_window(
        launch_handler=lambda **kwargs: FakeSession(),
        state_store=store,
        geo_probe=lambda _: None,
    )
    config_list = window.findChild(QListWidget, "saved_configurations")
    config_list.setCurrentRow(0)

    window.findChild(QPushButton, "launch_current_form").click()
    window.findChild(QPushButton, "delete_profile_data").click()

    assert store.load_config(saved.config_id).name == "运行环境"
    window.close()
    app.quit()


def test_desktop_gui_script_is_thin_entry_point() -> None:
    script = Path("scripts/desktop_gui.py").read_text(encoding="utf-8")

    assert "from app.desktop.main import run_desktop_gui" in script
    assert "raise SystemExit(" in script
    assert "run_desktop_gui(" in script
    assert "--launch-smoke" in script
    assert "desktop-gui.log" in script


def test_desktop_gui_script_runs_from_scripts_path_without_import_error() -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "scripts/desktop_gui.py", "--smoke"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=10,
    )

    assert "ModuleNotFoundError" not in result.stderr
    assert result.returncode == 0
    assert "GUI smoke ok" in result.stdout


def test_desktop_launch_smoke_clicks_launch_button_and_stops_session() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from app.desktop.main import run_desktop_gui

    class FakeSession:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    session = FakeSession()

    def launch_handler(*, config, start_url):
        return session

    result = run_desktop_gui(launch_smoke=True, launch_handler=launch_handler)

    assert result == 0
    assert session.stopped is True


def test_closing_desktop_window_stops_running_sessions() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QPushButton

    from app.desktop.window import create_main_window

    class FakeSession:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    session = FakeSession()

    app = QApplication.instance() or QApplication([])
    window = create_main_window(launch_handler=lambda **kwargs: session)
    window.findChild(QPushButton, "launch_current_form").click()

    window.close()

    assert session.stopped is True
    app.quit()


def test_desktop_session_stop_releases_lock_after_launcher_failure() -> None:
    import pytest

    from app.desktop.window import DesktopLaunchedSession

    class FailingLauncher:
        def stop(self, launch_result) -> None:
            raise RuntimeError("stop failed")

    class FakeLock:
        released = False

        def release(self) -> None:
            self.released = True

    lock = FakeLock()
    session = DesktopLaunchedSession(
        session_id="desktop-1",
        launcher=FailingLauncher(),
        launch_result=object(),
        profile_lock=lock,
    )

    with pytest.raises(RuntimeError):
        session.stop()

    assert lock.released is True


def test_desktop_launch_failure_releases_lock_when_stop_fails(monkeypatch) -> None:
    import pytest

    import app.desktop.window as desktop_window
    from app.runtime.chromium_launcher import ChromiumLaunchResult
    from app.runtime.config import LaunchConfig
    from app.runtime.profiles import RUNTIME_LOCK_FILENAME

    class FailingStopLauncher:
        profile_dirs: list[Path] = []

        def __init__(self, *, chrome_executable, relay_executable, paths) -> None:
            self.chrome_executable = chrome_executable

        def launch(self, *, config, session_id: str, start_url: str, profile_dir: Path):
            self.profile_dirs.append(profile_dir)
            return ChromiumLaunchResult(
                process=object(),
                args=["chrome.exe"],
                cdp_port=9222,
                profile_dir=profile_dir,
                relay=None,
            )

        def stop(self, launch_result) -> None:
            raise RuntimeError("stop failed")

    def failing_controller(**kwargs):
        raise RuntimeError("controller failed")

    monkeypatch.setattr(desktop_window, "resolve_portable_paths", lambda create=False: _desktop_paths())
    monkeypatch.setattr(desktop_window, "ChromiumLauncher", FailingStopLauncher)
    monkeypatch.setattr(desktop_window, "_start_fingerprint_controller", failing_controller)

    with pytest.raises(RuntimeError):
        desktop_window._launch_browser_session(
            config=LaunchConfig(name="Launch"),
            start_url="https://example.test/",
        )

    profile_dir = FailingStopLauncher.profile_dirs[0]
    assert not (profile_dir / RUNTIME_LOCK_FILENAME).exists()
    assert not profile_dir.exists()


def test_desktop_launch_smoke_can_enable_default_proxy() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from app.desktop.main import run_desktop_gui

    captured = {}

    class FakeSession:
        def stop(self) -> None:
            return None

    def launch_handler(*, config, start_url):
        captured["config"] = config
        return FakeSession()

    result = run_desktop_gui(
        launch_smoke=True,
        launch_smoke_proxy=True,
        launch_handler=launch_handler,
    )

    assert result == 0
    assert captured["config"].proxy_enabled is True
    assert captured["config"].proxy_host == "127.0.0.1"
    assert captured["config"].proxy_port == 7897


def test_http_proxy_probe_checks_connect_response() -> None:
    from app.desktop.window import _probe_proxy_connect
    from app.runtime.config import LaunchConfig

    server = HTTPServer(("127.0.0.1", 0), ConnectProxyHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    try:
        result = _probe_proxy_connect(
            LaunchConfig(
                name="Proxy",
                proxy_enabled=True,
                proxy_host="127.0.0.1",
                proxy_port=server.server_port,
            )
        )
    finally:
        server.server_close()
        thread.join(timeout=2)

    assert result == "代理可连接: HTTP CONNECT 成功"


def test_proxy_probe_reports_unreachable_port() -> None:
    from app.desktop.window import _probe_proxy_connect
    from app.runtime.config import LaunchConfig

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        unused_port = sock.getsockname()[1]

    result = _probe_proxy_connect(
        LaunchConfig(
            name="Proxy",
            proxy_enabled=True,
            proxy_host="127.0.0.1",
            proxy_port=unused_port,
        )
    )

    assert result.startswith("代理不可连接:")


def test_socks5_proxy_probe_checks_connect_response() -> None:
    from app.desktop.window import _probe_proxy_connect
    from app.runtime.config import LaunchConfig

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def handle_once() -> None:
        conn, _ = server.accept()
        with conn:
            assert conn.recv(3) == bytes([0x05, 0x01, 0x00])
            conn.sendall(bytes([0x05, 0x00]))
            head = conn.recv(5)
            assert head[:4] == bytes([0x05, 0x01, 0x00, 0x03])
            domain = conn.recv(head[4])
            target_port = conn.recv(2)
            assert domain == b"www.google.com"
            assert int.from_bytes(target_port, "big") == 443
            conn.sendall(bytes([0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0]))

    thread = threading.Thread(target=handle_once)
    thread.start()
    try:
        result = _probe_proxy_connect(
            LaunchConfig(
                name="Proxy",
                proxy_enabled=True,
                proxy_protocol="socks5",
                proxy_host="127.0.0.1",
                proxy_port=port,
            )
        )
    finally:
        server.close()
        thread.join(timeout=2)

    assert result == "代理可连接: SOCKS5 CONNECT 成功"


def test_desktop_cdp_wait_uses_version_endpoint_without_websocket_dependency() -> None:
    from app.desktop.main import _wait_for_cdp_version

    server = HTTPServer(("127.0.0.1", 0), DesktopVersionHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    try:
        assert _wait_for_cdp_version(server.server_port, timeout_s=1) is True
    finally:
        server.server_close()
        thread.join(timeout=2)


def test_desktop_status_output_tolerates_windowed_exe_stdout(monkeypatch) -> None:
    from app.desktop.main import _emit_status

    monkeypatch.setattr(sys, "stdout", None)

    _emit_status("hidden")


def test_pyproject_declares_pyside_gui_dependency() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8").lower()

    assert "pyside6" in pyproject


class DesktopVersionHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        assert self.path == "/json/version"
        body = json.dumps({"Browser": "Chrome/123.0.0.0"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


class ConnectProxyHandler(BaseHTTPRequestHandler):
    def do_CONNECT(self) -> None:
        self.send_response(200, "Connection Established")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return None


def _desktop_paths():
    from app.runtime.config import resolve_portable_paths

    base = Path(__file__).resolve().parent / "_tmp_window_base"
    shutil.rmtree(base, ignore_errors=True)
    return resolve_portable_paths(base=base, create=True)

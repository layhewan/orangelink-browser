from __future__ import annotations

import time
import socket
import inspect
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from app.desktop.models import LaunchConfigForm
from app.desktop.state_store import StateStore
from app.runtime.chromium_launcher import ChromiumLauncher, ChromiumLaunchResult
from app.runtime.cdp_client import connect_browser, wait_for_version
from app.runtime.config import LaunchConfig, resolve_portable_paths
from app.runtime.engine_version import read_chromium_version
from app.runtime.fingerprint import build_fingerprint_profile
from app.runtime.fingerprint_controller import BrowserFingerprintController
from app.runtime.profiles import ProfileHandle, ProfileManager
from app.runtime.proxy_geo import ProxyGeoResult, enrich_config_with_proxy_geo, probe_proxy_geo


MINIMUM_WINDOW_SIZE = (980, 680)
USES_SCROLL_AREA = True

MAIN_WINDOW_SECTIONS = (
    "configuration_editor",
    "launch_current_form",
    "saved_configurations",
    "running_sessions",
    "session_controls",
    "diagnostic_log",
    "portable_data_warning",
)

VISIBLE_CONTROL_KEYS = (
    "window_title",
    "configuration_editor",
    "config_name",
    "proxy_enabled",
    "proxy_protocol",
    "proxy_host",
    "proxy_port",
    "start_page",
    "language_mode",
    "manual_language",
    "timezone_mode",
    "manual_timezone",
    "os_fingerprint",
    "extension_support",
    "launch_current_form",
    "save_config",
    "create_config",
    "duplicate_config",
    "delete_config",
    "delete_profile_data",
    "saved_configurations",
    "running_sessions",
    "session_controls",
    "stop_selected",
    "stop_all",
    "diagnostic_log",
    "portable_data_warning",
)

ZH_UI_STRINGS = {
    "window_title": "脐橙浏览器",
    "configuration_editor": "配置编辑",
    "config_name": "配置名称",
    "proxy_enabled": "启用代理",
    "proxy_protocol": "代理协议",
    "proxy_host": "代理主机",
    "proxy_port": "代理端口",
    "start_page": "启动页面",
    "language_mode": "语言设置",
    "manual_language": "手动语言",
    "timezone_mode": "时区设置",
    "manual_timezone": "手动时区",
    "os_fingerprint": "系统指纹",
    "extension_support": "扩展支持",
    "launch_current_form": "启动当前配置",
    "save_config": "保存配置",
    "create_config": "新建配置",
    "duplicate_config": "复制配置",
    "delete_config": "删除配置",
    "delete_profile_data": "删除浏览器数据",
    "saved_configurations": "已保存配置",
    "running_sessions": "运行中的会话",
    "session_controls": "会话控制",
    "stop_selected": "停止选中会话",
    "stop_all": "停止全部会话",
    "diagnostic_log": "诊断日志",
    "portable_data_warning": "便携数据未加密，请妥善保管本文件夹。",
}


@dataclass
class DesktopLaunchedSession:
    session_id: str
    launcher: ChromiumLauncher
    launch_result: ChromiumLaunchResult
    profile_manager: ProfileManager | None = None
    profile: ProfileHandle | None = None
    saved_config_id: str | None = None
    fingerprint_controller: BrowserFingerprintController | None = None

    def stop(self) -> None:
        if self.fingerprint_controller is not None:
            self.fingerprint_controller.stop()
        self.launcher.stop(self.launch_result)
        if self.profile_manager is not None and self.profile is not None:
            self.profile_manager.cleanup_temporary(self.profile)


def create_main_window(
    *,
    launch_handler: Callable[..., object] | None = None,
    state_store: StateStore | None = None,
    geo_probe: Callable[[LaunchConfig], ProxyGeoResult | None] | None = None,
):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QFormLayout,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QPushButton,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )

    paths = resolve_portable_paths(create=True)
    store = state_store or StateStore(paths)
    window = QMainWindow()
    window.setWindowTitle(ZH_UI_STRINGS["window_title"])
    icon_path = _asset_icon_path()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.setMinimumSize(*MINIMUM_WINDOW_SIZE)
    window.setStyleSheet(_desktop_stylesheet())
    running_sessions: list[object] = []
    running_saved_config_ids: set[str] = set()

    content = QWidget()
    shell = QHBoxLayout(content)
    shell.setContentsMargins(18, 18, 18, 18)
    shell.setSpacing(16)

    sidebar = QFrame()
    sidebar.setObjectName("sidebar")
    sidebar_layout = QVBoxLayout(sidebar)
    sidebar_layout.setContentsMargins(16, 16, 16, 16)
    title = QLabel(ZH_UI_STRINGS["window_title"])
    title.setObjectName("app_title")
    subtitle = QLabel("代理会话工作台")
    subtitle.setObjectName("app_subtitle")
    sidebar_layout.addWidget(title)
    sidebar_layout.addWidget(subtitle)
    sidebar_layout.addSpacing(16)
    sidebar_layout.addWidget(QLabel("运行状态"))
    session_summary = QLabel("未启动")
    session_summary.setObjectName("session_summary")
    sidebar_layout.addWidget(session_summary)
    sidebar_layout.addSpacing(12)
    sidebar_layout.addWidget(QLabel("数据位置"))
    data_hint = QLabel(str(resolve_portable_paths().data))
    data_hint.setObjectName("data_hint")
    data_hint.setWordWrap(True)
    sidebar_layout.addWidget(data_hint)
    sidebar_layout.addSpacing(12)
    sidebar_layout.addWidget(QLabel(ZH_UI_STRINGS["saved_configurations"]))
    config_list = QListWidget()
    config_list.setObjectName("saved_configurations")
    sidebar_layout.addWidget(config_list, 1)
    config_button_grid = QGridLayout()
    create_button = QPushButton(ZH_UI_STRINGS["create_config"])
    create_button.setObjectName("create_config")
    save_button = QPushButton(ZH_UI_STRINGS["save_config"])
    save_button.setObjectName("save_config")
    duplicate_button = QPushButton(ZH_UI_STRINGS["duplicate_config"])
    duplicate_button.setObjectName("duplicate_config")
    delete_button = QPushButton(ZH_UI_STRINGS["delete_config"])
    delete_button.setObjectName("delete_config")
    delete_data_button = QPushButton(ZH_UI_STRINGS["delete_profile_data"])
    delete_data_button.setObjectName("delete_profile_data")
    config_button_grid.addWidget(create_button, 0, 0)
    config_button_grid.addWidget(save_button, 0, 1)
    config_button_grid.addWidget(duplicate_button, 1, 0)
    config_button_grid.addWidget(delete_button, 1, 1)
    config_button_grid.addWidget(delete_data_button, 2, 0, 1, 2)
    sidebar_layout.addLayout(config_button_grid)
    sidebar_layout.addStretch()
    sidebar_layout.addWidget(QLabel(ZH_UI_STRINGS["portable_data_warning"]))
    shell.addWidget(sidebar, 0)

    main_panel = QFrame()
    main_panel.setObjectName("main_panel")
    layout = QVBoxLayout(main_panel)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)
    section_title = QLabel(ZH_UI_STRINGS["configuration_editor"])
    section_title.setObjectName("section_title")
    layout.addWidget(section_title)

    form_layout = QFormLayout()
    form_layout.setLabelAlignment(Qt.AlignRight)
    config_name = QLineEdit("默认配置")
    config_name.setObjectName("config_name")
    start_page = QLineEdit("https://www.google.com/search?q=orangelink")
    start_page.setObjectName("start_page")
    proxy_enabled = QCheckBox(ZH_UI_STRINGS["proxy_enabled"])
    proxy_enabled.setObjectName("proxy_enabled")
    proxy_protocol = QComboBox()
    proxy_protocol.setObjectName("proxy_protocol")
    proxy_protocol.addItems(["http", "https", "socks5"])
    proxy_host = QLineEdit("127.0.0.1")
    proxy_host.setObjectName("proxy_host")
    proxy_port = QComboBox()
    proxy_port.setObjectName("proxy_port")
    proxy_port.setEditable(True)
    proxy_port.addItems(["7897", "7890", "10808"])
    automatic_language = QCheckBox("自动匹配代理语言")
    automatic_language.setObjectName("language_mode")
    automatic_language.setChecked(True)
    manual_language = QLineEdit("en-US")
    manual_language.setObjectName("manual_language")
    automatic_timezone = QCheckBox("自动匹配代理时区")
    automatic_timezone.setObjectName("timezone_mode")
    automatic_timezone.setChecked(True)
    manual_timezone = QLineEdit("UTC")
    manual_timezone.setObjectName("manual_timezone")
    os_fingerprint = QComboBox()
    os_fingerprint.setObjectName("os_fingerprint")
    os_fingerprint.addItems(["windows", "macos", "linux"])
    extension_support = QCheckBox("启用扩展支持")
    extension_support.setObjectName("extension_support")
    extension_support.setChecked(True)

    form_layout.addRow(ZH_UI_STRINGS["config_name"], config_name)
    form_layout.addRow(ZH_UI_STRINGS["start_page"], start_page)
    form_layout.addRow("", proxy_enabled)
    form_layout.addRow(ZH_UI_STRINGS["proxy_protocol"], proxy_protocol)
    form_layout.addRow(ZH_UI_STRINGS["proxy_host"], proxy_host)
    form_layout.addRow(ZH_UI_STRINGS["proxy_port"], proxy_port)
    form_layout.addRow("", automatic_language)
    form_layout.addRow(ZH_UI_STRINGS["manual_language"], manual_language)
    form_layout.addRow("", automatic_timezone)
    form_layout.addRow(ZH_UI_STRINGS["manual_timezone"], manual_timezone)
    form_layout.addRow(ZH_UI_STRINGS["os_fingerprint"], os_fingerprint)
    form_layout.addRow("", extension_support)
    layout.addLayout(form_layout)

    launch_button = QPushButton(ZH_UI_STRINGS["launch_current_form"])
    launch_button.setObjectName("launch_current_form")
    probe_button = QPushButton("测试代理")
    probe_button.setObjectName("probe_proxy")
    stop_all_button = QPushButton(ZH_UI_STRINGS["stop_all"])
    stop_all_button.setObjectName("stop_all")
    status_label = QLabel("就绪")
    status_label.setObjectName("diagnostic_log")
    action_row = QGridLayout()
    action_row.addWidget(probe_button, 0, 0)
    action_row.addWidget(launch_button, 0, 1)
    action_row.addWidget(stop_all_button, 0, 2)
    layout.addLayout(action_row)
    layout.addWidget(QLabel(ZH_UI_STRINGS["running_sessions"]))
    session_list = QListWidget()
    session_list.setObjectName("running_sessions")
    layout.addWidget(session_list)
    layout.addWidget(status_label)
    shell.addWidget(main_panel, 1)

    def current_form() -> LaunchConfigForm:
        try:
            port_value = int(proxy_port.currentText().strip()) if proxy_enabled.isChecked() else None
        except ValueError:
            port_value = 0
        config_id = selected_config_id()
        existing = store.load_config(config_id) if config_id is not None else None
        return LaunchConfigForm(
            name=config_name.text(),
            proxy_enabled=proxy_enabled.isChecked(),
            proxy_protocol=proxy_protocol.currentText(),
            proxy_host=proxy_host.text() if proxy_enabled.isChecked() else "",
            proxy_port=port_value,
            start_page=start_page.text(),
            automatic_language=automatic_language.isChecked(),
            manual_language=manual_language.text(),
            automatic_timezone=automatic_timezone.isChecked(),
            manual_timezone=manual_timezone.text(),
            cached_language=existing.cached_language if existing is not None else "",
            cached_timezone=existing.cached_timezone if existing is not None else "",
            os_fingerprint=os_fingerprint.currentText(),
            extension_support=extension_support.isChecked(),
            proxy_reuse_allowed=True,
        )

    def selected_config_id() -> str | None:
        item = config_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return str(value) if value is not None else None

    def set_form(config: LaunchConfig) -> None:
        config_name.setText(config.name)
        start_page.setText(config.start_page)
        proxy_enabled.setChecked(config.proxy_enabled)
        proxy_protocol.setCurrentText(config.proxy_protocol)
        proxy_host.setText(config.proxy_host or "127.0.0.1")
        proxy_port.setCurrentText(str(config.proxy_port or 7897))
        automatic_language.setChecked(config.automatic_language)
        manual_language.setText(config.manual_language)
        automatic_timezone.setChecked(config.automatic_timezone)
        manual_timezone.setText(config.manual_timezone)
        os_fingerprint.setCurrentText(config.os_fingerprint)
        extension_support.setChecked(config.extension_support)

    def refresh_config_list(select_id: str | None = None) -> None:
        config_list.blockSignals(True)
        config_list.clear()
        for saved in store.list_configs():
            item = QListWidgetItem(saved.config.name)
            item.setData(Qt.UserRole, saved.config_id)
            config_list.addItem(item)
            if select_id == saved.config_id:
                config_list.setCurrentItem(item)
        config_list.blockSignals(False)

    def on_config_selected() -> None:
        config_id = selected_config_id()
        if config_id is None:
            return
        set_form(store.load_config(config_id))

    def on_create_config() -> None:
        config_list.clearSelection()
        config_list.setCurrentItem(None)
        set_form(LaunchConfig(name="新配置"))
        status_label.setText("正在编辑新配置")

    def save_current_config(*, duplicate: bool = False) -> str | None:
        validation = current_form().validate()
        if not validation.ok or validation.config is None:
            status_label.setText(validation.error)
            return None
        config = _enrich_config_with_status(
            validation.config,
            status_label=status_label,
            geo_probe=geo_probe,
        )
        if duplicate:
            config = replace(config, name=f"{config.name} 副本")
        config_id = None if duplicate else selected_config_id()
        if config_id is None:
            saved = store.save_config(config)
            config_id = saved.config_id
        else:
            store.update_config(config_id, config)
        refresh_config_list(select_id=config_id)
        status_label.setText("配置已保存")
        return config_id

    def on_delete_config(*, remove_profile: bool = False) -> None:
        config_id = selected_config_id()
        if config_id is None:
            status_label.setText("请先选择配置")
            return
        profile_removed = store.delete_config(config_id, remove_profile=remove_profile)
        refresh_config_list()
        if not remove_profile:
            status_label.setText("配置已删除")
        elif profile_removed:
            status_label.setText("配置和浏览器数据已删除")
        else:
            status_label.setText("配置已删除，浏览器数据仍被占用")

    def on_probe_proxy() -> None:
        validation = current_form().validate()
        if not validation.ok or validation.config is None:
            status_label.setText(validation.error)
            return
        status_label.setText(_probe_proxy_connect(validation.config))

    def on_launch() -> None:
        form = current_form()
        validation = form.validate()
        if not validation.ok or validation.config is None:
            status_label.setText(validation.error)
            return

        config_id = selected_config_id()
        if config_id is not None and config_id in running_saved_config_ids:
            status_label.setText("该配置已在运行中")
            return
        launch_config = _enrich_config_with_status(
            validation.config,
            status_label=status_label,
            geo_probe=geo_probe,
        )
        if config_id is not None and launch_config != validation.config:
            store.update_config(config_id, launch_config)
        handler = launch_handler or _launch_browser_session
        try:
            session = _invoke_launch_handler(
                handler,
                config=launch_config,
                start_url=form.start_page or launch_config.start_page,
                saved_config_id=config_id,
            )
        except Exception as exc:
            status_label.setText(f"启动失败: {exc}")
            return

        running_sessions.append(session)
        if config_id is not None:
            running_saved_config_ids.add(config_id)
        session_item = QListWidgetItem(
            f"{launch_config.name}  {getattr(session, 'session_id', len(running_sessions))}"
        )
        session_item.setData(Qt.UserRole, id(session))
        session_list.addItem(session_item)
        session_summary.setText(f"运行中: {len(running_sessions)}")
        status_label.setText("会话已启动")

    def on_stop_selected() -> None:
        row = session_list.currentRow()
        if row < 0 or row >= len(running_sessions):
            status_label.setText("请先选择会话")
            return
        session = running_sessions.pop(row)
        _stop_session(session)
        saved_id = getattr(session, "saved_config_id", None)
        if saved_id is not None:
            running_saved_config_ids.discard(saved_id)
        session_list.takeItem(row)
        session_summary.setText(f"运行中: {len(running_sessions)}" if running_sessions else "未启动")
        status_label.setText("会话已停止")

    def on_stop_all() -> None:
        for session in list(running_sessions):
            _stop_session(session)
        running_sessions.clear()
        running_saved_config_ids.clear()
        session_list.clear()
        session_summary.setText("未启动")
        status_label.setText("全部会话已停止")

    refresh_config_list()
    config_list.currentItemChanged.connect(lambda *_: on_config_selected())
    create_button.clicked.connect(on_create_config)
    save_button.clicked.connect(lambda: save_current_config())
    duplicate_button.clicked.connect(lambda: save_current_config(duplicate=True))
    delete_button.clicked.connect(lambda: on_delete_config(remove_profile=False))
    delete_data_button.clicked.connect(lambda: on_delete_config(remove_profile=True))
    probe_button.clicked.connect(on_probe_proxy)
    launch_button.clicked.connect(on_launch)
    stop_selected_button = QPushButton(ZH_UI_STRINGS["stop_selected"])
    stop_selected_button.setObjectName("stop_selected")
    action_row.addWidget(stop_selected_button, 1, 0, 1, 3)
    stop_selected_button.clicked.connect(on_stop_selected)
    stop_all_button.clicked.connect(on_stop_all)
    window._orangelink_sessions = running_sessions

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    window.setCentralWidget(scroll)
    return window


def _probe_proxy_connect(config: LaunchConfig) -> str:
    if not config.proxy_enabled:
        return "当前为直连模式"

    try:
        if config.proxy_protocol in {"http", "https"}:
            return _probe_http_connect(config)
        if config.proxy_protocol == "socks5":
            return _probe_socks5_connect(config)
    except OSError as exc:
        return f"代理不可连接: {exc}"

    return "不支持的代理协议"


def _probe_http_connect(config: LaunchConfig) -> str:
    with socket.create_connection((config.proxy_host, int(config.proxy_port or 0)), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(
            b"CONNECT www.google.com:443 HTTP/1.1\r\n"
            b"Host: www.google.com:443\r\n\r\n"
        )
        response = sock.recv(256)

    if response.startswith((b"HTTP/1.1 200", b"HTTP/1.0 200")):
        return "代理可连接: HTTP CONNECT 成功"
    return f"代理返回异常: {response[:80]!r}"


def _probe_socks5_connect(config: LaunchConfig) -> str:
    with socket.create_connection((config.proxy_host, int(config.proxy_port or 0)), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(bytes([0x05, 0x01, 0x00]))
        greeting = _recv_exact(sock, 2)
        if greeting != bytes([0x05, 0x00]):
            return f"代理返回异常: {greeting!r}"

        target = b"www.google.com"
        request = bytes([0x05, 0x01, 0x00, 0x03, len(target)])
        request += target
        request += (443).to_bytes(2, "big")
        sock.sendall(request)
        response = _recv_exact(sock, 4)
        if len(response) < 4 or response[0] != 0x05 or response[1] != 0x00:
            return f"代理返回异常: {response!r}"
        return "代理可连接: SOCKS5 CONNECT 成功"


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _invoke_launch_handler(
    handler: Callable[..., object],
    *,
    config: LaunchConfig,
    start_url: str,
    saved_config_id: str | None,
) -> object:
    signature = inspect.signature(handler)
    accepts_saved_id = "saved_config_id" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    kwargs = {"config": config, "start_url": start_url}
    if accepts_saved_id:
        kwargs["saved_config_id"] = saved_config_id
    return handler(**kwargs)


def _stop_session(session: object) -> None:
    stop = getattr(session, "stop", None)
    if callable(stop):
        stop()


def _enrich_config_with_status(
    config: LaunchConfig,
    *,
    status_label: object,
    geo_probe: Callable[[LaunchConfig], ProxyGeoResult | None] | None,
) -> LaunchConfig:
    if not config.proxy_enabled or not (config.automatic_language or config.automatic_timezone):
        return config
    enriched = enrich_config_with_proxy_geo(config, probe=geo_probe or probe_proxy_geo)
    if enriched.cached_timezone and enriched.cached_timezone != config.cached_timezone:
        status_label.setText(f"已匹配代理时区: {enriched.cached_timezone}")
    elif config.automatic_timezone and not config.cached_timezone:
        status_label.setText("自动时区未获取，可使用手动时区")
    return enriched


def _asset_icon_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "favicon.ico"


def _desktop_stylesheet() -> str:
    return """
    QMainWindow {
        background: #f5f7f8;
        color: #2f3a42;
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 13px;
    }
    QFrame#sidebar {
        background: #e8edf1;
        border: 1px solid #cbd5dc;
        border-radius: 8px;
        min-width: 250px;
        max-width: 300px;
    }
    QFrame#main_panel {
        background: #fbfcfc;
        border: 1px solid #d3dde3;
        border-radius: 8px;
    }
    QLabel#app_title {
        font-size: 22px;
        font-weight: 700;
    }
    QLabel#app_subtitle, QLabel#data_hint, QLabel#diagnostic_log {
        color: #64717a;
    }
    QLabel#section_title {
        font-size: 17px;
        font-weight: 650;
    }
    QLineEdit, QSpinBox, QComboBox {
        min-height: 30px;
        padding: 4px 8px;
        border: 1px solid #b8c4cb;
        border-radius: 6px;
        background: #ffffff;
    }
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
        border: 1px solid #2866b6;
    }
    QPushButton {
        min-height: 32px;
        padding: 4px 12px;
        border-radius: 6px;
        border: 1px solid #aebbc4;
        background: #e8eef2;
    }
    QPushButton:hover {
        background: #dce5eb;
    }
    QPushButton#launch_current_form {
        color: #ffffff;
        background: #2866b6;
        border-color: #235aa2;
    }
    """


def _launch_browser_session(
    *,
    config: LaunchConfig,
    start_url: str,
    saved_config_id: str | None = None,
) -> DesktopLaunchedSession:
    paths = resolve_portable_paths(create=True)
    profile_manager = ProfileManager(paths)
    launcher = ChromiumLauncher(
        chrome_executable=paths.base / "runtime" / "chromium" / "chrome.exe",
        relay_executable=_resolve_relay_executable(paths.base),
        paths=paths,
    )
    session_id = f"desktop-{int(time.time() * 1000)}"
    profile = (
        profile_manager.saved_config_profile(saved_config_id)
        if saved_config_id is not None
        else profile_manager.temporary_profile(session_id)
    )
    launch_result = launcher.launch(
        config=config,
        session_id=session_id,
        start_url="about:blank",
        profile_dir=profile.path,
    )
    fingerprint_controller = None
    try:
        fingerprint_controller = _start_fingerprint_controller(
            launch_result=launch_result,
            config=config,
            chrome_executable=launcher.chrome_executable,
            start_url=start_url,
            session_id=session_id,
        )
    except Exception:
        launcher.stop(launch_result)
        profile_manager.cleanup_temporary(profile)
        raise
    return DesktopLaunchedSession(
        session_id=session_id,
        launcher=launcher,
        launch_result=launch_result,
        profile_manager=profile_manager,
        profile=profile,
        saved_config_id=saved_config_id,
        fingerprint_controller=fingerprint_controller,
    )


def _resolve_relay_executable(base: Path) -> Path:
    candidates = (
        base / "proxy-relay.exe",
        base / "relay" / "target" / "release" / "proxy-relay.exe",
        base / "relay" / "target" / "debug" / "proxy-relay.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _start_fingerprint_controller(
    *,
    launch_result: ChromiumLaunchResult,
    config: LaunchConfig,
    chrome_executable: Path,
    start_url: str,
    session_id: str,
) -> BrowserFingerprintController:
    version = wait_for_version(launch_result.cdp_port, timeout_s=15)
    engine = read_chromium_version(chrome_executable)
    fingerprint_profile = build_fingerprint_profile(config, actual_engine=engine)
    controller = BrowserFingerprintController(
        connection_factory=lambda: connect_browser(version.web_socket_debugger_url),
        profile=fingerprint_profile,
        start_url=start_url,
    )
    controller.start()
    try:
        controller.wait_ready(timeout_s=10)
    except Exception:
        controller.stop()
        raise
    return controller

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import queue
import sys
import threading
import time
from typing import Any
from uuid import uuid4
from urllib.parse import urlparse

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.worker.runtime import WorkerRuntime


EventPayload = tuple[str, str, Any]


@dataclass(slots=True)
class SavedLaunchConfig:
    id: str
    name: str
    use_proxy: bool
    proxy_scheme: str
    proxy_host: str
    proxy_port: int
    start_url: str
    auto_fingerprint: bool
    locale: str
    timezone_id: str

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "SavedLaunchConfig":
        id_value = str(raw.get("id", "")).strip() or uuid4().hex[:10]
        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError("saved config name is required")
        use_proxy = bool(raw.get("use_proxy", True))
        proxy_scheme = str(raw.get("proxy_scheme", "http")).strip().lower() or "http"
        if proxy_scheme not in {"http", "https", "socks5"}:
            proxy_scheme = "http"
        proxy_host = str(raw.get("proxy_host", "127.0.0.1")).strip() or "127.0.0.1"
        proxy_port = int(raw.get("proxy_port", 7897))
        proxy_port = max(1, min(65535, proxy_port))
        start_url = _normalize_saved_start_url(str(raw.get("start_url", "about:blank")).strip() or "about:blank")
        auto_fingerprint = bool(raw.get("auto_fingerprint", True))
        locale = str(raw.get("locale", "")).strip()
        timezone_id = str(raw.get("timezone_id", "")).strip()
        return cls(
            id=id_value,
            name=name,
            use_proxy=use_proxy,
            proxy_scheme=proxy_scheme,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            start_url=start_url,
            auto_fingerprint=auto_fingerprint,
            locale=locale,
            timezone_id=timezone_id,
        )

    def proxy_label(self) -> str:
        if not self.use_proxy:
            return "direct"
        return f"{self.proxy_scheme}://{self.proxy_host}:{self.proxy_port}"


def _normalize_saved_start_url(value: str) -> str:
    raw = (value or "").strip() or "about:blank"
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if host == "www.browserscan.org":
        return raw.replace("//www.browserscan.org", "//browserscan.org", 1)
    return raw


def read_saved_configs(config_path: Path) -> list[SavedLaunchConfig]:
    if not config_path.exists():
        return []
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(payload, list):
        return []

    result: list[SavedLaunchConfig] = []
    for node in payload:
        if not isinstance(node, dict):
            continue
        try:
            result.append(SavedLaunchConfig.from_mapping(node))
        except Exception:  # noqa: BLE001
            continue
    return result


def write_saved_configs(config_path: Path, configs: list[SavedLaunchConfig]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(item) for item in configs]
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class DesktopLauncherWindow(QMainWindow):
    I18N: dict[str, dict[str, str]] = {
        "zh": {
            "window_title": "脐橙浏览器启动器",
            "hero_title": "脐橙浏览器启动器",
            "hero_subtitle": "配置代理、指纹参数与会话管理的一体化桌面控制台",
            "legal_notice": "本软件为开源免费软件，仅适用于学习交流，请勿将其使用于任何违法活动。",
            "hero_chip": "桌面界面",
            "lang_label": "语言",
            "group_config_editor": "配置编辑器",
            "group_session_actions": "会话操作",
            "group_saved_configs": "已保存配置",
            "group_running_sessions": "运行中会话",
            "group_event_log": "事件日志",
            "label_config_name": "配置名称",
            "label_scheme": "代理协议",
            "label_host": "主机",
            "label_port": "端口",
            "label_start_url": "启动地址",
            "label_locale_optional": "语言区域（可选）",
            "label_timezone_optional": "时区（可选）",
            "label_kernel": "内核",
            "checkbox_use_proxy": "启用代理",
            "checkbox_auto_fp": "自动同步指纹语言/时区",
            "btn_preset_org": "BrowserScan.org",
            "btn_preset_net": "BrowserScan.net",
            "btn_preset_blank": "空白页",
            "btn_save_update": "保存 / 更新",
            "btn_load_selected": "加载选中",
            "btn_delete_selected": "删除选中",
            "btn_clear_editor": "清空编辑器",
            "btn_launch_current": "启动当前表单",
            "btn_launch_selected": "启动选中配置",
            "btn_stop_selected": "停止选中会话",
            "btn_stop_all": "停止全部会话",
            "placeholder_config_name": "例如: home-proxy-7897",
            "placeholder_proxy_host": "127.0.0.1",
            "placeholder_proxy_port": "1 - 65535",
            "placeholder_start_url": "https://example.com/",
            "placeholder_locale": "zh-CN / en-US",
            "placeholder_timezone": "Asia/Shanghai",
            "saved_header_id": "ID",
            "saved_header_name": "名称",
            "saved_header_proxy": "代理",
            "saved_header_start_url": "启动地址",
            "saved_header_auto": "指纹",
            "saved_header_locale": "语言区域",
            "saved_header_timezone": "时区",
            "session_header_session": "会话ID",
            "session_header_config": "配置",
            "session_header_status": "状态",
            "session_header_proxy": "代理",
            "session_header_started": "启动时间",
            "text_auto": "自动",
            "text_manual": "手动",
            "status_launching": "启动中",
            "status_running": "运行中",
            "status_failed": "失败",
            "status_stopping": "停止中",
            "status_stopped": "已停止",
            "status_stop_failed": "停止失败",
            "msg_invalid_config_title": "配置无效",
            "msg_kernel_missing_title": "内核缺失",
            "msg_kernel_missing_body": "未找到内置 Chrome 内核。\n预期路径：\n{path}",
            "msg_launch_failed_title": "启动失败",
            "msg_launch_failed_body": "未找到内置 Chrome 内核。",
            "msg_load_config_title": "加载配置",
            "msg_load_need_one": "请只选择一条保存配置进行加载。",
            "msg_load_missing": "选中的配置已不存在。",
            "msg_delete_config_title": "删除配置",
            "msg_delete_need_select": "请至少选择一条保存配置后再删除。",
            "msg_launch_config_title": "启动配置",
            "msg_launch_need_select": "请至少选择一条保存配置后再启动。",
            "err_config_name_required": "配置名称不能为空。",
            "err_proxy_port_int": "代理端口必须是整数。",
            "err_proxy_port_range": "代理端口必须在 1-65535 之间。",
            "log_error_missing_chrome": "[错误] 缺少内置 Chrome 内核: {path}",
            "log_ok_embedded_chrome": "[就绪] 内置 Chrome: {path}",
            "log_ok_loaded_configs": "[就绪] 已加载 {count} 条保存配置。",
            "log_editor_cleared": "[编辑器] 已清空",
            "log_config_added": "[配置] 已新增: {name}",
            "log_config_updated": "[配置] 已更新: {name}",
            "log_config_loaded": "[配置] 已加载: {name}",
            "log_config_deleted": "[配置] 已删除: {count}",
            "log_launch": "[启动] {session_id} ({config_label}) -> {proxy}",
            "log_running": "[运行] {session_id}",
            "log_failed": "[失败] {session_id}: {error}",
            "log_stopped": "[停止] {session_id}",
            "log_stop_failed": "[停止失败] {session_id}: {error}",
            "config_label_current_form": "（当前表单）",
        },
        "en": {
            "window_title": "Navel Orange Browser Launcher",
            "hero_title": "Navel Orange Browser Launcher",
            "hero_subtitle": "Desktop control panel for proxy, fingerprint and session management",
            "legal_notice": "This open-source software is free for learning and technical exchange only. Do not use it for any illegal activities.",
            "hero_chip": "Desktop GUI",
            "lang_label": "Language",
            "group_config_editor": "Config Editor",
            "group_session_actions": "Session Actions",
            "group_saved_configs": "Saved Configs",
            "group_running_sessions": "Running Sessions",
            "group_event_log": "Event Log",
            "label_config_name": "Config Name",
            "label_scheme": "Scheme",
            "label_host": "Host",
            "label_port": "Port",
            "label_start_url": "Start URL",
            "label_locale_optional": "Locale (optional)",
            "label_timezone_optional": "Timezone (optional)",
            "label_kernel": "Kernel",
            "checkbox_use_proxy": "Use Proxy",
            "checkbox_auto_fp": "Auto fingerprint locale/timezone",
            "btn_preset_org": "BrowserScan.org",
            "btn_preset_net": "BrowserScan.net",
            "btn_preset_blank": "Blank",
            "btn_save_update": "Save / Update",
            "btn_load_selected": "Load Selected",
            "btn_delete_selected": "Delete Selected",
            "btn_clear_editor": "Clear Editor",
            "btn_launch_current": "Launch Current Form",
            "btn_launch_selected": "Launch Selected Config",
            "btn_stop_selected": "Stop Selected Session",
            "btn_stop_all": "Stop All Sessions",
            "placeholder_config_name": "e.g. home-proxy-7897",
            "placeholder_proxy_host": "127.0.0.1",
            "placeholder_proxy_port": "1 - 65535",
            "placeholder_start_url": "https://example.com/",
            "placeholder_locale": "zh-CN / en-US",
            "placeholder_timezone": "Asia/Shanghai",
            "saved_header_id": "ID",
            "saved_header_name": "Name",
            "saved_header_proxy": "Proxy",
            "saved_header_start_url": "Start URL",
            "saved_header_auto": "Auto",
            "saved_header_locale": "Locale",
            "saved_header_timezone": "Timezone",
            "session_header_session": "Session",
            "session_header_config": "Config",
            "session_header_status": "Status",
            "session_header_proxy": "Proxy",
            "session_header_started": "Started",
            "text_auto": "auto",
            "text_manual": "manual",
            "status_launching": "launching",
            "status_running": "running",
            "status_failed": "failed",
            "status_stopping": "stopping",
            "status_stopped": "stopped",
            "status_stop_failed": "stop-failed",
            "msg_invalid_config_title": "Invalid Config",
            "msg_kernel_missing_title": "Kernel Missing",
            "msg_kernel_missing_body": "Embedded chrome kernel was not found.\nExpected path:\n{path}",
            "msg_launch_failed_title": "Launch Failed",
            "msg_launch_failed_body": "Embedded chrome kernel not found.",
            "msg_load_config_title": "Load Config",
            "msg_load_need_one": "Select exactly one saved config to load.",
            "msg_load_missing": "Selected config no longer exists.",
            "msg_delete_config_title": "Delete Config",
            "msg_delete_need_select": "Select at least one saved config to delete.",
            "msg_launch_config_title": "Launch Config",
            "msg_launch_need_select": "Select at least one saved config to launch.",
            "err_config_name_required": "Config name is required.",
            "err_proxy_port_int": "Proxy port must be integer.",
            "err_proxy_port_range": "Proxy port must be in range 1-65535.",
            "log_error_missing_chrome": "[ERROR] Missing embedded chrome: {path}",
            "log_ok_embedded_chrome": "[OK] Embedded chrome: {path}",
            "log_ok_loaded_configs": "[OK] Loaded {count} saved launch configs.",
            "log_editor_cleared": "[EDITOR] cleared",
            "log_config_added": "[CONFIG] added: {name}",
            "log_config_updated": "[CONFIG] updated: {name}",
            "log_config_loaded": "[CONFIG] loaded: {name}",
            "log_config_deleted": "[CONFIG] deleted: {count}",
            "log_launch": "[LAUNCH] {session_id} ({config_label}) -> {proxy}",
            "log_running": "[RUNNING] {session_id}",
            "log_failed": "[FAILED] {session_id}: {error}",
            "log_stopped": "[STOPPED] {session_id}",
            "log_stop_failed": "[STOP-FAILED] {session_id}: {error}",
            "config_label_current_form": "(current-form)",
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self.current_language = "zh"
        self.setWindowTitle(self._t("window_title"))
        self.resize(1200, 780)

        self.base_dir = self._resolve_base_dir()
        self.chrome_path = (self.base_dir / ".playwright" / "chrome-win64" / "chrome.exe").resolve()
        self.data_dir = (self.base_dir / "data").resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "profiles").mkdir(parents=True, exist_ok=True)
        self.saved_configs_path = (self.data_dir / "desktop-launch-configs.json").resolve()

        self.events: queue.Queue[EventPayload] = queue.Queue()
        self.sessions: dict[str, WorkerRuntime] = {}
        self.row_by_session_id: dict[str, int] = {}
        self.session_status_by_id: dict[str, str] = {}
        self.saved_configs: list[SavedLaunchConfig] = read_saved_configs(self.saved_configs_path)
        self.saved_row_by_id: dict[str, int] = {}
        self.editing_config_id: str | None = None

        self._build_ui()
        self._refresh_saved_config_table()
        self._build_timer()

        if not self.chrome_path.exists():
            self._append_log(self._t("log_error_missing_chrome").format(path=self.chrome_path))
            QMessageBox.critical(
                self,
                self._t("msg_kernel_missing_title"),
                self._t("msg_kernel_missing_body").format(path=self.chrome_path),
            )
        else:
            self._append_log(self._t("log_ok_embedded_chrome").format(path=self.chrome_path))
        self._append_log(self._t("log_ok_loaded_configs").format(count=len(self.saved_configs)))

    @staticmethod
    def _resolve_base_dir() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path.cwd()

    def _build_timer(self) -> None:
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(200)
        self.poll_timer.timeout.connect(self._poll_events)
        self.poll_timer.start()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self._apply_styles()

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)

        hero_card = QWidget()
        hero_card.setObjectName("HeroCard")
        hero_layout = QHBoxLayout(hero_card)
        hero_layout.setContentsMargins(18, 14, 18, 14)
        title_col = QVBoxLayout()
        self.app_title_label = QLabel()
        self.app_title_label.setObjectName("AppTitle")
        self.app_subtitle_label = QLabel()
        self.app_subtitle_label.setObjectName("AppSubtitle")
        title_col.addWidget(self.app_title_label)
        title_col.addWidget(self.app_subtitle_label)
        hero_layout.addLayout(title_col, stretch=1)
        hero_right = QVBoxLayout()
        hero_right.setSpacing(8)
        self.info_chip_label = QLabel()
        self.info_chip_label.setObjectName("InfoChip")
        self.info_chip_label.setAlignment(Qt.AlignCenter)
        self.info_chip_label.setFixedHeight(30)
        hero_right.addWidget(self.info_chip_label)
        lang_row = QHBoxLayout()
        self.lang_hint_label = QLabel()
        self.lang_hint_label.setObjectName("LanguageHint")
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("LanguageCombo")
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("English", "en")
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row.addWidget(self.lang_hint_label)
        lang_row.addWidget(self.language_combo)
        hero_right.addLayout(lang_row)
        hero_layout.addLayout(hero_right)
        main_layout.addWidget(hero_card)

        self.legal_notice_label = QLabel()
        self.legal_notice_label.setObjectName("LegalNotice")
        self.legal_notice_label.setWordWrap(True)
        self.legal_notice_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.legal_notice_label)

        self.launch_group = QGroupBox()
        self.launch_group.setObjectName("CardGroup")
        launch_layout = QGridLayout(self.launch_group)
        launch_layout.setContentsMargins(14, 20, 14, 14)
        launch_layout.setHorizontalSpacing(10)
        launch_layout.setVerticalSpacing(10)

        self.config_name_label = QLabel()
        launch_layout.addWidget(self.config_name_label, 0, 0)
        self.config_name_edit = QLineEdit("default-7897")
        launch_layout.addWidget(self.config_name_edit, 0, 1, 1, 3)

        self.use_proxy_checkbox = QCheckBox()
        self.use_proxy_checkbox.setChecked(True)
        launch_layout.addWidget(self.use_proxy_checkbox, 0, 4)

        self.proxy_scheme_label = QLabel()
        launch_layout.addWidget(self.proxy_scheme_label, 0, 5)
        self.proxy_scheme_combo = QComboBox()
        self.proxy_scheme_combo.addItems(["http", "https", "socks5"])
        launch_layout.addWidget(self.proxy_scheme_combo, 0, 6)

        self.proxy_host_label = QLabel()
        launch_layout.addWidget(self.proxy_host_label, 1, 0)
        self.proxy_host_edit = QLineEdit("127.0.0.1")
        launch_layout.addWidget(self.proxy_host_edit, 1, 1)

        self.proxy_port_label = QLabel()
        launch_layout.addWidget(self.proxy_port_label, 1, 2)
        self.proxy_port_edit = QLineEdit("7897")
        launch_layout.addWidget(self.proxy_port_edit, 1, 3)

        self.start_url_label = QLabel()
        launch_layout.addWidget(self.start_url_label, 1, 4)
        self.start_url_edit = QLineEdit("about:blank")
        launch_layout.addWidget(self.start_url_edit, 1, 5, 1, 2)

        preset_row = QHBoxLayout()
        self.preset_browserscan_org_btn = self._create_button("", role="ghost")
        self.preset_browserscan_org_btn.clicked.connect(self._preset_browserscan_org)
        preset_row.addWidget(self.preset_browserscan_org_btn)
        self.preset_browserscan_net_btn = self._create_button("", role="ghost")
        self.preset_browserscan_net_btn.clicked.connect(self._preset_browserscan_net)
        preset_row.addWidget(self.preset_browserscan_net_btn)
        self.preset_blank_btn = self._create_button("", role="ghost")
        self.preset_blank_btn.clicked.connect(self._preset_blank)
        preset_row.addWidget(self.preset_blank_btn)
        preset_row.addStretch(1)
        launch_layout.addLayout(preset_row, 2, 0, 1, 3)

        self.auto_fingerprint_checkbox = QCheckBox()
        self.auto_fingerprint_checkbox.setChecked(True)
        launch_layout.addWidget(self.auto_fingerprint_checkbox, 2, 3, 1, 2)

        self.locale_label = QLabel()
        launch_layout.addWidget(self.locale_label, 2, 5)
        self.locale_edit = QLineEdit("")
        launch_layout.addWidget(self.locale_edit, 2, 6)

        self.timezone_label = QLabel()
        launch_layout.addWidget(self.timezone_label, 3, 0)
        self.timezone_edit = QLineEdit("")
        launch_layout.addWidget(self.timezone_edit, 3, 1, 1, 2)

        self.save_btn = self._create_button("", role="primary")
        self.save_btn.clicked.connect(self._save_current_form_config)
        launch_layout.addWidget(self.save_btn, 3, 3)

        self.load_btn = self._create_button("", role="secondary")
        self.load_btn.clicked.connect(self._load_selected_config_to_form)
        launch_layout.addWidget(self.load_btn, 3, 4)

        self.delete_btn = self._create_button("", role="danger")
        self.delete_btn.clicked.connect(self._delete_selected_configs)
        launch_layout.addWidget(self.delete_btn, 3, 5)

        self.clear_btn = self._create_button("", role="secondary")
        self.clear_btn.clicked.connect(self._clear_form)
        launch_layout.addWidget(self.clear_btn, 3, 6)

        main_layout.addWidget(self.launch_group)

        self.action_group = QGroupBox()
        self.action_group.setObjectName("CardGroup")
        action_row = QHBoxLayout()
        action_row.setContentsMargins(14, 18, 14, 12)
        self.launch_from_form_btn = self._create_button("", role="primary")
        self.launch_from_form_btn.clicked.connect(self._on_launch_current_form_clicked)
        action_row.addWidget(self.launch_from_form_btn)
        self.launch_saved_btn = self._create_button("", role="primary")
        self.launch_saved_btn.clicked.connect(self._launch_selected_saved_configs)
        action_row.addWidget(self.launch_saved_btn)
        self.stop_selected_btn = self._create_button("", role="secondary")
        self.stop_selected_btn.clicked.connect(self._on_stop_selected_clicked)
        action_row.addWidget(self.stop_selected_btn)
        self.stop_all_btn = self._create_button("", role="danger")
        self.stop_all_btn.clicked.connect(self._on_stop_all_clicked)
        action_row.addWidget(self.stop_all_btn)
        action_row.addStretch(1)
        self.action_group.setLayout(action_row)
        main_layout.addWidget(self.action_group)

        kernel_row = QWidget()
        kernel_row.setObjectName("KernelRow")
        kernel_layout = QHBoxLayout(kernel_row)
        kernel_layout.setContentsMargins(14, 10, 14, 10)
        self.kernel_hint_label = QLabel()
        self.kernel_hint_label.setObjectName("KernelHint")
        kernel_layout.addWidget(self.kernel_hint_label)
        self.kernel_path_label = QLabel(str(self.chrome_path))
        self.kernel_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.kernel_path_label.setObjectName("KernelPath")
        kernel_layout.addWidget(self.kernel_path_label, stretch=1)
        main_layout.addWidget(kernel_row)

        self.saved_group = QGroupBox()
        self.saved_group.setObjectName("CardGroup")
        saved_layout = QVBoxLayout(self.saved_group)
        saved_layout.setContentsMargins(10, 18, 10, 10)
        self.saved_table = QTableWidget(0, 7)
        self._configure_table(self.saved_table)
        self.saved_table.setColumnHidden(0, True)
        saved_layout.addWidget(self.saved_table)

        self.session_group = QGroupBox()
        self.session_group.setObjectName("CardGroup")
        session_layout = QVBoxLayout(self.session_group)
        session_layout.setContentsMargins(10, 18, 10, 10)
        self.session_table = QTableWidget(0, 5)
        self._configure_table(self.session_table)
        session_layout.addWidget(self.session_table)

        table_row = QHBoxLayout()
        table_row.setSpacing(12)
        table_row.addWidget(self.saved_group, stretch=3)
        table_row.addWidget(self.session_group, stretch=2)
        main_layout.addLayout(table_row, stretch=2)

        self.log_group = QGroupBox()
        self.log_group.setObjectName("CardGroup")
        log_layout = QVBoxLayout(self.log_group)
        log_layout.setContentsMargins(10, 18, 10, 10)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("LogView")
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(self.log_group, stretch=1)

        self._apply_language(self.current_language)

    def _create_button(self, text: str, *, role: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("role", role)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(34)
        return btn

    def _configure_table(self, table: QTableWidget) -> None:
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setMinimumSectionSize(90)
        table.horizontalHeader().setSectionResizeMode(table.columnCount() - 1, QHeaderView.Stretch)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget#AppRoot {
                background: #f6f1e8;
            }
            QWidget#HeroCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b85a23, stop:0.58 #d37b32, stop:1 #7f8a52);
                border-radius: 16px;
            }
            QLabel#AppTitle {
                color: #fff8ee;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#AppSubtitle {
                color: #ffe6c9;
                font-size: 13px;
                padding-top: 2px;
            }
            QLabel#LegalNotice {
                color: #9a4d1f;
                background: #fff3df;
                border: 1px solid #efc78f;
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#InfoChip {
                color: #7b3f1d;
                background: #fff2dc;
                border: 1px solid #efc78f;
                border-radius: 14px;
                font-size: 12px;
                font-weight: 700;
                min-width: 98px;
                padding: 0 12px;
            }
            QLabel#LanguageHint {
                color: #fff2df;
                font-size: 12px;
                font-weight: 700;
            }
            QComboBox#LanguageCombo {
                min-width: 110px;
                background: #fff7eb;
                border-color: #efc78f;
                color: #6f3a1f;
                font-weight: 600;
            }
            QGroupBox#CardGroup {
                background: #fffdf8;
                border: 1px solid #e8d8c3;
                border-radius: 14px;
                margin-top: 8px;
            }
            QGroupBox#CardGroup::title {
                color: #925128;
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                background: #fffdf8;
                font-weight: 700;
                font-size: 12px;
            }
            QWidget#KernelRow {
                background: #fffdf8;
                border: 1px solid #e8d8c3;
                border-radius: 12px;
            }
            QLabel#KernelHint {
                color: #925128;
                font-size: 12px;
                font-weight: 700;
                padding-right: 8px;
            }
            QLabel#KernelPath {
                color: #554737;
                font-size: 12px;
            }
            QLabel {
                color: #5b4433;
            }
            QLineEdit, QComboBox, QTextEdit, QTableWidget {
                background: #fffaf2;
                border: 1px solid #e3c9a7;
                border-radius: 8px;
                color: #4c3b2d;
                padding: 6px 8px;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QTableWidget:focus {
                border: 1px solid #cd7a35;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QCheckBox {
                color: #5b4433;
                spacing: 6px;
                font-weight: 600;
            }
            QPushButton {
                border-radius: 9px;
                border: 1px solid #dfc29f;
                background: #fff4e4;
                color: #6b4425;
                padding: 7px 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #ffe8cb;
            }
            QPushButton:pressed {
                background: #f8d9b5;
            }
            QPushButton[role="primary"] {
                background: #c86c2f;
                border-color: #a75425;
                color: #fff9ef;
            }
            QPushButton[role="primary"]:hover {
                background: #b6612b;
            }
            QPushButton[role="danger"] {
                background: #f9ece2;
                border-color: #d7ab8b;
                color: #8f3b24;
            }
            QPushButton[role="danger"]:hover {
                background: #f4ddcd;
            }
            QPushButton[role="ghost"] {
                background: #fffdf8;
                border-color: #e3c9a7;
                color: #7b4f2d;
                padding-left: 10px;
                padding-right: 10px;
            }
            QHeaderView::section {
                background: #f8ead7;
                color: #8d4c24;
                border: none;
                border-bottom: 1px solid #e3c9a7;
                padding: 8px;
                font-weight: 700;
            }
            QTableWidget {
                alternate-background-color: #fff6ea;
                selection-background-color: #fbdab5;
                selection-color: #5a381f;
            }
            QTextEdit#LogView {
                background: #3f3128;
                color: #f9ead5;
                border: 1px solid #2f251e;
            }
            """
        )

    def _t(self, key: str) -> str:
        lang = self.I18N.get(self.current_language, self.I18N["zh"])
        return lang.get(key, self.I18N["zh"].get(key, key))

    def _on_language_changed(self, _: int) -> None:
        language = self.language_combo.currentData()
        if isinstance(language, str):
            self._apply_language(language)

    def _apply_language(self, language: str) -> None:
        if language not in self.I18N:
            language = "zh"
        self.current_language = language
        self.setWindowTitle(self._t("window_title"))

        target_index = self.language_combo.findData(language)
        if target_index >= 0 and target_index != self.language_combo.currentIndex():
            self.language_combo.setCurrentIndex(target_index)

        self.app_title_label.setText(self._t("hero_title"))
        self.app_subtitle_label.setText(self._t("hero_subtitle"))
        self.legal_notice_label.setText(self._t("legal_notice"))
        self.info_chip_label.setText(self._t("hero_chip"))
        self.lang_hint_label.setText(self._t("lang_label"))

        self.launch_group.setTitle(self._t("group_config_editor"))
        self.action_group.setTitle(self._t("group_session_actions"))
        self.saved_group.setTitle(self._t("group_saved_configs"))
        self.session_group.setTitle(self._t("group_running_sessions"))
        self.log_group.setTitle(self._t("group_event_log"))

        self.config_name_label.setText(self._t("label_config_name"))
        self.proxy_scheme_label.setText(self._t("label_scheme"))
        self.proxy_host_label.setText(self._t("label_host"))
        self.proxy_port_label.setText(self._t("label_port"))
        self.start_url_label.setText(self._t("label_start_url"))
        self.locale_label.setText(self._t("label_locale_optional"))
        self.timezone_label.setText(self._t("label_timezone_optional"))
        self.kernel_hint_label.setText(self._t("label_kernel"))

        self.use_proxy_checkbox.setText(self._t("checkbox_use_proxy"))
        self.auto_fingerprint_checkbox.setText(self._t("checkbox_auto_fp"))

        self.preset_browserscan_org_btn.setText(self._t("btn_preset_org"))
        self.preset_browserscan_net_btn.setText(self._t("btn_preset_net"))
        self.preset_blank_btn.setText(self._t("btn_preset_blank"))
        self.save_btn.setText(self._t("btn_save_update"))
        self.load_btn.setText(self._t("btn_load_selected"))
        self.delete_btn.setText(self._t("btn_delete_selected"))
        self.clear_btn.setText(self._t("btn_clear_editor"))
        self.launch_from_form_btn.setText(self._t("btn_launch_current"))
        self.launch_saved_btn.setText(self._t("btn_launch_selected"))
        self.stop_selected_btn.setText(self._t("btn_stop_selected"))
        self.stop_all_btn.setText(self._t("btn_stop_all"))

        self.config_name_edit.setPlaceholderText(self._t("placeholder_config_name"))
        self.proxy_host_edit.setPlaceholderText(self._t("placeholder_proxy_host"))
        self.proxy_port_edit.setPlaceholderText(self._t("placeholder_proxy_port"))
        self.start_url_edit.setPlaceholderText(self._t("placeholder_start_url"))
        self.locale_edit.setPlaceholderText(self._t("placeholder_locale"))
        self.timezone_edit.setPlaceholderText(self._t("placeholder_timezone"))

        self.saved_table.setHorizontalHeaderLabels(
            [
                self._t("saved_header_id"),
                self._t("saved_header_name"),
                self._t("saved_header_proxy"),
                self._t("saved_header_start_url"),
                self._t("saved_header_auto"),
                self._t("saved_header_locale"),
                self._t("saved_header_timezone"),
            ]
        )
        self.session_table.setHorizontalHeaderLabels(
            [
                self._t("session_header_session"),
                self._t("session_header_config"),
                self._t("session_header_status"),
                self._t("session_header_proxy"),
                self._t("session_header_started"),
            ]
        )
        self._refresh_saved_config_table()
        self._refresh_session_status_texts()

    def _append_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{stamp}] {message}")

    def _status_text(self, status: str) -> str:
        key = f"status_{status.replace('-', '_')}"
        return self._t(key)

    def _refresh_session_status_texts(self) -> None:
        for session_id, status in self.session_status_by_id.items():
            row = self.row_by_session_id.get(session_id)
            if row is None:
                continue
            item = self.session_table.item(row, 2)
            if item is None:
                continue
            item.setText(self._status_text(status))

    def _preset_browserscan_org(self) -> None:
        self.start_url_edit.setText("https://browserscan.org/")

    def _preset_browserscan_net(self) -> None:
        self.start_url_edit.setText("https://www.browserscan.net/")

    def _preset_blank(self) -> None:
        self.start_url_edit.setText("about:blank")

    def _clear_form(self) -> None:
        self.editing_config_id = None
        self.config_name_edit.setText("")
        self.use_proxy_checkbox.setChecked(True)
        self.proxy_scheme_combo.setCurrentText("http")
        self.proxy_host_edit.setText("127.0.0.1")
        self.proxy_port_edit.setText("7897")
        self.start_url_edit.setText("about:blank")
        self.auto_fingerprint_checkbox.setChecked(True)
        self.locale_edit.setText("")
        self.timezone_edit.setText("")
        self._append_log(self._t("log_editor_cleared"))

    def _selected_saved_config_ids(self) -> list[str]:
        rows = sorted({index.row() for index in self.saved_table.selectionModel().selectedRows()})
        output: list[str] = []
        for row in rows:
            id_item = self.saved_table.item(row, 0)
            if id_item is None:
                continue
            config_id = id_item.text().strip()
            if config_id:
                output.append(config_id)
        return output

    def _refresh_saved_config_table(self) -> None:
        self.saved_table.setRowCount(0)
        self.saved_row_by_id.clear()
        for index, cfg in enumerate(self.saved_configs):
            self.saved_table.insertRow(index)
            self.saved_table.setItem(index, 0, QTableWidgetItem(cfg.id))
            self.saved_table.setItem(index, 1, QTableWidgetItem(cfg.name))
            self.saved_table.setItem(index, 2, QTableWidgetItem(cfg.proxy_label()))
            self.saved_table.setItem(index, 3, QTableWidgetItem(cfg.start_url))
            auto_text = self._t("text_auto") if cfg.auto_fingerprint else self._t("text_manual")
            self.saved_table.setItem(index, 4, QTableWidgetItem(auto_text))
            self.saved_table.setItem(index, 5, QTableWidgetItem(cfg.locale or "-"))
            self.saved_table.setItem(index, 6, QTableWidgetItem(cfg.timezone_id or "-"))
            self.saved_row_by_id[cfg.id] = index

    def _find_saved_config_by_id(self, config_id: str) -> SavedLaunchConfig | None:
        for cfg in self.saved_configs:
            if cfg.id == config_id:
                return cfg
        return None

    def _collect_form_as_saved_config(self, *, config_id: str) -> SavedLaunchConfig:
        name = self.config_name_edit.text().strip()
        if not name:
            raise ValueError(self._t("err_config_name_required"))

        use_proxy = self.use_proxy_checkbox.isChecked()
        proxy_scheme = self.proxy_scheme_combo.currentText().strip() or "http"
        proxy_host = self.proxy_host_edit.text().strip() or "127.0.0.1"
        try:
            proxy_port = int(self.proxy_port_edit.text().strip())
        except ValueError as exc:
            raise ValueError(self._t("err_proxy_port_int")) from exc
        if not (1 <= proxy_port <= 65535):
            raise ValueError(self._t("err_proxy_port_range"))

        start_url = _normalize_saved_start_url(self.start_url_edit.text().strip() or "about:blank")
        auto_fingerprint = self.auto_fingerprint_checkbox.isChecked()
        locale = self.locale_edit.text().strip()
        timezone_id = self.timezone_edit.text().strip()

        return SavedLaunchConfig(
            id=config_id,
            name=name,
            use_proxy=use_proxy,
            proxy_scheme=proxy_scheme,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            start_url=start_url,
            auto_fingerprint=auto_fingerprint,
            locale=locale,
            timezone_id=timezone_id,
        )

    def _save_current_form_config(self) -> None:
        target_id = self.editing_config_id or uuid4().hex[:10]
        try:
            candidate = self._collect_form_as_saved_config(config_id=target_id)
        except ValueError as exc:
            QMessageBox.warning(self, self._t("msg_invalid_config_title"), str(exc))
            return

        target_index: int | None = None
        if self.editing_config_id:
            for idx, cfg in enumerate(self.saved_configs):
                if cfg.id == self.editing_config_id:
                    target_index = idx
                    break
        if target_index is None:
            for idx, cfg in enumerate(self.saved_configs):
                if cfg.name == candidate.name:
                    target_index = idx
                    candidate.id = cfg.id
                    break

        if target_index is None:
            self.saved_configs.append(candidate)
            self._append_log(self._t("log_config_added").format(name=candidate.name))
        else:
            self.saved_configs[target_index] = candidate
            self._append_log(self._t("log_config_updated").format(name=candidate.name))

        self.editing_config_id = candidate.id
        write_saved_configs(self.saved_configs_path, self.saved_configs)
        self._refresh_saved_config_table()

    def _load_selected_config_to_form(self) -> None:
        ids = self._selected_saved_config_ids()
        if len(ids) != 1:
            QMessageBox.information(self, self._t("msg_load_config_title"), self._t("msg_load_need_one"))
            return
        config = self._find_saved_config_by_id(ids[0])
        if config is None:
            QMessageBox.warning(self, self._t("msg_load_config_title"), self._t("msg_load_missing"))
            return

        self.editing_config_id = config.id
        self.config_name_edit.setText(config.name)
        self.use_proxy_checkbox.setChecked(config.use_proxy)
        self.proxy_scheme_combo.setCurrentText(config.proxy_scheme)
        self.proxy_host_edit.setText(config.proxy_host)
        self.proxy_port_edit.setText(str(config.proxy_port))
        self.start_url_edit.setText(config.start_url)
        self.auto_fingerprint_checkbox.setChecked(config.auto_fingerprint)
        self.locale_edit.setText(config.locale)
        self.timezone_edit.setText(config.timezone_id)
        self._append_log(self._t("log_config_loaded").format(name=config.name))

    def _delete_selected_configs(self) -> None:
        ids = set(self._selected_saved_config_ids())
        if not ids:
            QMessageBox.information(self, self._t("msg_delete_config_title"), self._t("msg_delete_need_select"))
            return

        before = len(self.saved_configs)
        self.saved_configs = [cfg for cfg in self.saved_configs if cfg.id not in ids]
        removed = before - len(self.saved_configs)
        if removed == 0:
            return

        if self.editing_config_id and self.editing_config_id in ids:
            self.editing_config_id = None
        write_saved_configs(self.saved_configs_path, self.saved_configs)
        self._refresh_saved_config_table()
        self._append_log(self._t("log_config_deleted").format(count=removed))

    @staticmethod
    def _next_session_id() -> str:
        millis = int(time.time() * 1000)
        return f"session-{millis}"

    def _runtime_config_from_saved(self, config: SavedLaunchConfig, *, session_id: str) -> dict[str, Any]:
        runtime_config: dict[str, Any] = {
            "profile_id": session_id,
            "user_data_dir": str((self.data_dir / "profiles" / f"cfg-{config.id}").resolve()),
            "start_url": config.start_url or "about:blank",
            "headless": False,
            "chrome_executable_path": str(self.chrome_path),
            "auto_locale": bool(config.auto_fingerprint),
            "auto_timezone": bool(config.auto_fingerprint),
            "timezone_probe_timeout_ms": 12000,
            "launch_args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--disable-features=AsyncDns,DnsOverHttps,UseDnsHttpsSvcb",
                "--proxy-bypass-list=<-loopback>",
            ],
        }
        if config.locale:
            runtime_config["locale"] = config.locale
        if config.timezone_id:
            runtime_config["timezone_id"] = config.timezone_id
        if config.use_proxy:
            runtime_config["proxy_server"] = config.proxy_label()
        return runtime_config

    def _runtime_config_from_form(self, *, session_id: str) -> dict[str, Any]:
        temp = self._collect_form_as_saved_config(config_id=f"temp-{session_id}")
        return self._runtime_config_from_saved(temp, session_id=session_id)

    def _launch_with_runtime_config(self, *, session_id: str, config_label: str, runtime_config: dict[str, Any]) -> None:
        proxy_label = str(runtime_config.get("proxy_server", "direct"))
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        self._add_session_row(session_id, config_label, "launching", proxy_label, started)
        self._append_log(self._t("log_launch").format(session_id=session_id, config_label=config_label, proxy=proxy_label))
        thread = threading.Thread(
            target=self._launch_runtime_worker,
            args=(session_id, runtime_config),
            daemon=True,
        )
        thread.start()

    def _on_launch_current_form_clicked(self) -> None:
        if not self.chrome_path.exists():
            QMessageBox.critical(self, self._t("msg_launch_failed_title"), self._t("msg_launch_failed_body"))
            return
        session_id = self._next_session_id()
        try:
            runtime_config = self._runtime_config_from_form(session_id=session_id)
        except ValueError as exc:
            QMessageBox.warning(self, self._t("msg_invalid_config_title"), str(exc))
            return
        self._launch_with_runtime_config(
            session_id=session_id,
            config_label=self._t("config_label_current_form"),
            runtime_config=runtime_config,
        )

    def _launch_selected_saved_configs(self) -> None:
        if not self.chrome_path.exists():
            QMessageBox.critical(self, self._t("msg_launch_failed_title"), self._t("msg_launch_failed_body"))
            return
        ids = self._selected_saved_config_ids()
        if not ids:
            QMessageBox.information(self, self._t("msg_launch_config_title"), self._t("msg_launch_need_select"))
            return
        for config_id in ids:
            cfg = self._find_saved_config_by_id(config_id)
            if cfg is None:
                continue
            session_id = self._next_session_id()
            runtime_config = self._runtime_config_from_saved(cfg, session_id=session_id)
            self._launch_with_runtime_config(session_id=session_id, config_label=cfg.name, runtime_config=runtime_config)
            time.sleep(0.01)

    def _add_session_row(self, session_id: str, config_name: str, status: str, proxy: str, started: str) -> None:
        row = self.session_table.rowCount()
        self.session_table.insertRow(row)
        self.session_table.setItem(row, 0, QTableWidgetItem(session_id))
        self.session_table.setItem(row, 1, QTableWidgetItem(config_name))
        self.session_table.setItem(row, 2, QTableWidgetItem(self._status_text(status)))
        self.session_table.setItem(row, 3, QTableWidgetItem(proxy))
        self.session_table.setItem(row, 4, QTableWidgetItem(started))
        self.row_by_session_id[session_id] = row
        self.session_status_by_id[session_id] = status

    def _launch_runtime_worker(self, session_id: str, runtime_config: dict[str, Any]) -> None:
        try:
            runtime = WorkerRuntime(runtime_config)
            runtime.launch()
            self.events.put(("launched", session_id, runtime))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("launch_failed", session_id, str(exc)))

    def _on_stop_selected_clicked(self) -> None:
        rows = sorted({index.row() for index in self.session_table.selectionModel().selectedRows()})
        for row in rows:
            session_item = self.session_table.item(row, 0)
            if session_item is None:
                continue
            self._stop_session_async(session_item.text())

    def _on_stop_all_clicked(self) -> None:
        for session_id in list(self.sessions.keys()):
            self._stop_session_async(session_id)

    def _stop_session_async(self, session_id: str) -> None:
        runtime = self.sessions.pop(session_id, None)
        if runtime is None:
            self._set_session_status(session_id, "stopped")
            return
        self._set_session_status(session_id, "stopping")
        thread = threading.Thread(target=self._stop_runtime_worker, args=(session_id, runtime), daemon=True)
        thread.start()

    def _stop_runtime_worker(self, session_id: str, runtime: WorkerRuntime) -> None:
        try:
            runtime.stop()
            self.events.put(("stopped", session_id, None))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("stop_failed", session_id, str(exc)))

    def _set_session_status(self, session_id: str, status: str) -> None:
        row = self.row_by_session_id.get(session_id)
        if row is None:
            return
        self.session_status_by_id[session_id] = status
        status_item = self.session_table.item(row, 2)
        if status_item is None:
            return
        status_item.setText(self._status_text(status))

    def _poll_events(self) -> None:
        while True:
            try:
                event_type, session_id, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event_type == "launched":
                runtime = payload
                if isinstance(runtime, WorkerRuntime):
                    self.sessions[session_id] = runtime
                    self._set_session_status(session_id, "running")
                    self._append_log(self._t("log_running").format(session_id=session_id))
            elif event_type == "launch_failed":
                self._set_session_status(session_id, "failed")
                self._append_log(self._t("log_failed").format(session_id=session_id, error=payload))
            elif event_type == "stopped":
                self._set_session_status(session_id, "stopped")
                self._append_log(self._t("log_stopped").format(session_id=session_id))
            elif event_type == "stop_failed":
                self._set_session_status(session_id, "stop-failed")
                self._append_log(self._t("log_stop_failed").format(session_id=session_id, error=payload))

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        for session_id, runtime in list(self.sessions.items()):
            try:
                runtime.stop()
                self._append_log(self._t("log_stopped").format(session_id=session_id))
            except Exception as exc:  # noqa: BLE001
                self._append_log(self._t("log_stop_failed").format(session_id=session_id, error=exc))
        self.sessions.clear()
        super().closeEvent(event)


def run_desktop_gui() -> int:
    app = QApplication(sys.argv)
    window = DesktopLauncherWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_desktop_gui())

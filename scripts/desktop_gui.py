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
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Privacy Browser Framework")
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
        self.saved_configs: list[SavedLaunchConfig] = read_saved_configs(self.saved_configs_path)
        self.saved_row_by_id: dict[str, int] = {}
        self.editing_config_id: str | None = None

        self._build_ui()
        self._refresh_saved_config_table()
        self._build_timer()

        if not self.chrome_path.exists():
            self._append_log(f"[ERROR] Missing embedded chrome: {self.chrome_path}")
            QMessageBox.critical(
                self,
                "Kernel Missing",
                f"Embedded chrome kernel was not found.\nExpected path:\n{self.chrome_path}",
            )
        else:
            self._append_log(f"[OK] Embedded chrome: {self.chrome_path}")
        self._append_log(f"[OK] Loaded {len(self.saved_configs)} saved launch configs.")

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
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)

        launch_group = QGroupBox("Config Editor")
        launch_layout = QGridLayout(launch_group)

        launch_layout.addWidget(QLabel("Config Name"), 0, 0)
        self.config_name_edit = QLineEdit("default-7897")
        launch_layout.addWidget(self.config_name_edit, 0, 1, 1, 3)

        self.use_proxy_checkbox = QCheckBox("Use Proxy")
        self.use_proxy_checkbox.setChecked(True)
        launch_layout.addWidget(self.use_proxy_checkbox, 0, 4)

        launch_layout.addWidget(QLabel("Scheme"), 0, 5)
        self.proxy_scheme_combo = QComboBox()
        self.proxy_scheme_combo.addItems(["http", "https", "socks5"])
        launch_layout.addWidget(self.proxy_scheme_combo, 0, 6)

        launch_layout.addWidget(QLabel("Host"), 1, 0)
        self.proxy_host_edit = QLineEdit("127.0.0.1")
        launch_layout.addWidget(self.proxy_host_edit, 1, 1)

        launch_layout.addWidget(QLabel("Port"), 1, 2)
        self.proxy_port_edit = QLineEdit("7897")
        launch_layout.addWidget(self.proxy_port_edit, 1, 3)

        launch_layout.addWidget(QLabel("Start URL"), 1, 4)
        self.start_url_edit = QLineEdit("about:blank")
        launch_layout.addWidget(self.start_url_edit, 1, 5, 1, 2)

        preset_row = QHBoxLayout()
        preset_browserscan_org_btn = QPushButton("BrowserScan.org")
        preset_browserscan_org_btn.clicked.connect(self._preset_browserscan_org)
        preset_row.addWidget(preset_browserscan_org_btn)
        preset_browserscan_net_btn = QPushButton("BrowserScan.net")
        preset_browserscan_net_btn.clicked.connect(self._preset_browserscan_net)
        preset_row.addWidget(preset_browserscan_net_btn)
        preset_blank_btn = QPushButton("Blank")
        preset_blank_btn.clicked.connect(self._preset_blank)
        preset_row.addWidget(preset_blank_btn)
        preset_row.addStretch(1)
        launch_layout.addLayout(preset_row, 2, 0, 1, 3)

        self.auto_fingerprint_checkbox = QCheckBox("Auto fingerprint locale/timezone")
        self.auto_fingerprint_checkbox.setChecked(True)
        launch_layout.addWidget(self.auto_fingerprint_checkbox, 2, 3, 1, 2)

        launch_layout.addWidget(QLabel("Locale (optional)"), 2, 5)
        self.locale_edit = QLineEdit("")
        launch_layout.addWidget(self.locale_edit, 2, 6)

        launch_layout.addWidget(QLabel("Timezone (optional)"), 3, 0)
        self.timezone_edit = QLineEdit("")
        launch_layout.addWidget(self.timezone_edit, 3, 1, 1, 2)

        save_btn = QPushButton("Save/Update Config")
        save_btn.clicked.connect(self._save_current_form_config)
        launch_layout.addWidget(save_btn, 3, 3)

        load_btn = QPushButton("Load Selected Config")
        load_btn.clicked.connect(self._load_selected_config_to_form)
        launch_layout.addWidget(load_btn, 3, 4)

        delete_btn = QPushButton("Delete Selected Config")
        delete_btn.clicked.connect(self._delete_selected_configs)
        launch_layout.addWidget(delete_btn, 3, 5)

        clear_btn = QPushButton("Clear Editor")
        clear_btn.clicked.connect(self._clear_form)
        launch_layout.addWidget(clear_btn, 3, 6)

        main_layout.addWidget(launch_group)

        action_row = QHBoxLayout()
        launch_from_form_btn = QPushButton("Launch Current Form")
        launch_from_form_btn.clicked.connect(self._on_launch_current_form_clicked)
        action_row.addWidget(launch_from_form_btn)
        launch_saved_btn = QPushButton("Launch Selected Config")
        launch_saved_btn.clicked.connect(self._launch_selected_saved_configs)
        action_row.addWidget(launch_saved_btn)
        stop_selected_btn = QPushButton("Stop Selected Session")
        stop_selected_btn.clicked.connect(self._on_stop_selected_clicked)
        action_row.addWidget(stop_selected_btn)
        stop_all_btn = QPushButton("Stop All Sessions")
        stop_all_btn.clicked.connect(self._on_stop_all_clicked)
        action_row.addWidget(stop_all_btn)
        action_row.addStretch(1)
        main_layout.addLayout(action_row)

        kernel_label = QLabel(f"Kernel: {self.chrome_path}")
        kernel_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        main_layout.addWidget(kernel_label)

        saved_group = QGroupBox("Saved Configs")
        saved_layout = QVBoxLayout(saved_group)
        self.saved_table = QTableWidget(0, 7)
        self.saved_table.setHorizontalHeaderLabels(["ID", "Name", "Proxy", "Start URL", "Auto", "Locale", "Timezone"])
        self.saved_table.horizontalHeader().setStretchLastSection(True)
        self.saved_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.saved_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.saved_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.saved_table.setColumnHidden(0, True)
        saved_layout.addWidget(self.saved_table)
        main_layout.addWidget(saved_group, stretch=2)

        self.session_table = QTableWidget(0, 5)
        self.session_table.setHorizontalHeaderLabels(["Session", "Config", "Status", "Proxy", "Started"])
        self.session_table.horizontalHeader().setStretchLastSection(True)
        self.session_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.session_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.session_table.setEditTriggers(QTableWidget.NoEditTriggers)
        main_layout.addWidget(self.session_table, stretch=2)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text, stretch=2)

    def _append_log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{stamp}] {message}")

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
        self._append_log("[EDITOR] cleared")

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
            self.saved_table.setItem(index, 4, QTableWidgetItem("auto" if cfg.auto_fingerprint else "manual"))
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
            raise ValueError("Config name is required.")

        use_proxy = self.use_proxy_checkbox.isChecked()
        proxy_scheme = self.proxy_scheme_combo.currentText().strip() or "http"
        proxy_host = self.proxy_host_edit.text().strip() or "127.0.0.1"
        try:
            proxy_port = int(self.proxy_port_edit.text().strip())
        except ValueError as exc:
            raise ValueError("Proxy port must be integer.") from exc
        if not (1 <= proxy_port <= 65535):
            raise ValueError("Proxy port must be in range 1-65535.")

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
            QMessageBox.warning(self, "Invalid Config", str(exc))
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
            self._append_log(f"[CONFIG] added: {candidate.name}")
        else:
            self.saved_configs[target_index] = candidate
            self._append_log(f"[CONFIG] updated: {candidate.name}")

        self.editing_config_id = candidate.id
        write_saved_configs(self.saved_configs_path, self.saved_configs)
        self._refresh_saved_config_table()

    def _load_selected_config_to_form(self) -> None:
        ids = self._selected_saved_config_ids()
        if len(ids) != 1:
            QMessageBox.information(self, "Load Config", "Select exactly one saved config to load.")
            return
        config = self._find_saved_config_by_id(ids[0])
        if config is None:
            QMessageBox.warning(self, "Load Config", "Selected config no longer exists.")
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
        self._append_log(f"[CONFIG] loaded: {config.name}")

    def _delete_selected_configs(self) -> None:
        ids = set(self._selected_saved_config_ids())
        if not ids:
            QMessageBox.information(self, "Delete Config", "Select at least one saved config to delete.")
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
        self._append_log(f"[CONFIG] deleted: {removed}")

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
        self._append_log(f"[LAUNCH] {session_id} ({config_label}) -> {proxy_label}")
        thread = threading.Thread(
            target=self._launch_runtime_worker,
            args=(session_id, runtime_config),
            daemon=True,
        )
        thread.start()

    def _on_launch_current_form_clicked(self) -> None:
        if not self.chrome_path.exists():
            QMessageBox.critical(self, "Launch Failed", "Embedded chrome kernel not found.")
            return
        session_id = self._next_session_id()
        try:
            runtime_config = self._runtime_config_from_form(session_id=session_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Config", str(exc))
            return
        self._launch_with_runtime_config(session_id=session_id, config_label="(current-form)", runtime_config=runtime_config)

    def _launch_selected_saved_configs(self) -> None:
        if not self.chrome_path.exists():
            QMessageBox.critical(self, "Launch Failed", "Embedded chrome kernel not found.")
            return
        ids = self._selected_saved_config_ids()
        if not ids:
            QMessageBox.information(self, "Launch Config", "Select at least one saved config to launch.")
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
        self.session_table.setItem(row, 2, QTableWidgetItem(status))
        self.session_table.setItem(row, 3, QTableWidgetItem(proxy))
        self.session_table.setItem(row, 4, QTableWidgetItem(started))
        self.row_by_session_id[session_id] = row

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
        status_item = self.session_table.item(row, 2)
        if status_item is None:
            return
        status_item.setText(status)

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
                    self._append_log(f"[RUNNING] {session_id}")
            elif event_type == "launch_failed":
                self._set_session_status(session_id, "failed")
                self._append_log(f"[FAILED] {session_id}: {payload}")
            elif event_type == "stopped":
                self._set_session_status(session_id, "stopped")
                self._append_log(f"[STOPPED] {session_id}")
            elif event_type == "stop_failed":
                self._set_session_status(session_id, "stop-failed")
                self._append_log(f"[STOP-FAILED] {session_id}: {payload}")

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        for session_id, runtime in list(self.sessions.items()):
            try:
                runtime.stop()
                self._append_log(f"[STOPPED] {session_id}")
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"[STOP-FAILED] {session_id}: {exc}")
        self.sessions.clear()
        super().closeEvent(event)


def run_desktop_gui() -> int:
    app = QApplication(sys.argv)
    window = DesktopLauncherWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_desktop_gui())

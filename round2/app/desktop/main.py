from __future__ import annotations

import json
import sys
import time
from typing import Callable
from urllib.request import urlopen

from app.desktop.window import create_main_window


def run_desktop_gui(
    *,
    smoke: bool = False,
    launch_smoke: bool = False,
    launch_smoke_proxy: bool = False,
    launch_handler: Callable[..., object] | None = None,
) -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QPushButton
    except ImportError:
        _emit_status("缺少 PySide6，无法启动桌面界面。")
        return 2

    app = QApplication.instance() or QApplication(sys.argv)
    window = create_main_window(launch_handler=launch_handler)
    if smoke:
        _emit_status(
            f"GUI smoke ok: {window.windowTitle()} "
            f"{window.minimumWidth()}x{window.minimumHeight()}"
        )
        window.close()
        app.quit()
        return 0
    if launch_smoke:
        if launch_smoke_proxy:
            proxy_enabled = window.findChild(QCheckBox, "proxy_enabled")
            proxy_host = window.findChild(QLineEdit, "proxy_host")
            proxy_port = window.findChild(QComboBox, "proxy_port")
            if proxy_enabled is None or proxy_host is None or proxy_port is None:
                window.close()
                app.quit()
                return 1
            proxy_enabled.setCheckState(Qt.Checked)
            proxy_host.setText("127.0.0.1")
            proxy_port.setCurrentText("7897")
        button = window.findChild(QPushButton, "launch_current_form")
        if button is None:
            window.close()
            app.quit()
            return 1
        button.click()
        sessions = list(getattr(window, "_orangelink_sessions", []))
        smoke_ok = bool(sessions)
        for session in sessions:
            launch_result = getattr(session, "launch_result", None)
            if launch_result is not None:
                if not _wait_for_cdp_version(launch_result.cdp_port, timeout_s=20):
                    smoke_ok = False
        for session in sessions:
            stop = getattr(session, "stop", None)
            if callable(stop):
                stop()
        window.close()
        app.quit()
        return 0 if smoke_ok else 1
    window.show()
    return int(app.exec())


def _wait_for_cdp_version(port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() <= deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("Browser"))
        except Exception:
            time.sleep(0.05)
    return False


def _emit_status(message: str) -> None:
    if sys.stdout is not None:
        print(message)
